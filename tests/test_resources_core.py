import json
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pytest
from Moge.core.resources import bedrock, java
from Moge.core.resources.database import ResourceDatabase
from Moge.core.resources.features import analyze_texture_array
from Moge.core.resources.manager import ResourceManager
from Moge.core.resources.safezip import UnsafeArchiveError, validate_members


def _png_bytes(color=(200, 40, 40), size=4) -> bytes:
    image = np.zeros((size, size, 4), np.uint8)
    image[..., :3] = color
    image[..., 3] = 255
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _java_jar(tmp_path: Path) -> Path:
    jar = tmp_path / "client.jar"
    with zipfile.ZipFile(jar, "w") as archive:
        archive.writestr(
            "assets/minecraft/blockstates/test_block.json",
            json.dumps({"variants": {"": {"model": "block/test_block"}}}),
        )
        archive.writestr(
            "assets/minecraft/blockstates/missing_block.json",
            json.dumps({"variants": {"": {"model": "block/not_found"}}}),
        )
        archive.writestr(
            "assets/minecraft/models/block/test_block.json",
            json.dumps({"parent": "block/cube_all", "textures": {"all": "block/test_texture"}}),
        )
        archive.writestr(
            "assets/minecraft/models/block/cube_all.json",
            json.dumps(
                {
                    "elements": [
                        {
                            "from": [0, 0, 0],
                            "to": [16, 16, 16],
                            "faces": {
                                "up": {"texture": "#all"},
                                "down": {"texture": "#all"},
                                "north": {"texture": "#all"},
                                "south": {"texture": "#all"},
                                "east": {"texture": "#all"},
                                "west": {"texture": "#all"},
                            },
                        }
                    ],
                    "textures": {"particle": "#all"},
                }
            ),
        )
        archive.writestr("assets/minecraft/textures/block/test_texture.png", _png_bytes())
    return jar


def _bedrock_zip(tmp_path: Path) -> Path:
    path = tmp_path / "bedrock.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "resource_pack/textures/terrain_texture.json",
            json.dumps({"texture_data": {"stone": {"textures": "textures/blocks/stone"}}}),
        )
        archive.writestr("resource_pack/textures/blocks/stone.png", _png_bytes((120, 120, 120)))
        archive.writestr(
            "resource_pack/blocks/stone.json",
            json.dumps(
                {
                    "minecraft:block": {
                        "description": {"identifier": "minecraft:stone"},
                        "components": {
                            "minecraft:material_instances": {"*": {"texture": "stone"}}
                        },
                    }
                }
            ),
        )
    return path


def test_analyze_texture_features():
    features = analyze_texture_array(cv2.imdecode(np.frombuffer(_png_bytes(), np.uint8), cv2.IMREAD_UNCHANGED))
    assert features["width"] == 4
    assert features["mean_rgb"] == (40, 40, 200)
    assert features["has_alpha"] == 1
    assert features["lab"][0] > 0


def test_safe_zip_rejects_traversal(tmp_path):
    path = tmp_path / "evil.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../evil.txt", "x")
    with zipfile.ZipFile(path) as archive:
        with pytest.raises(UnsafeArchiveError):
            validate_members(archive)


def test_parse_java_jar_and_build_catalog(tmp_path):
    jar = _java_jar(tmp_path)
    manager = ResourceManager(tmp_path / "root")
    version_id = manager.db.upsert_version("java", "1.20.1", "release", "test")
    stats = java.parse_client_jar(jar, version_id, manager.db, manager.root)

    assert stats["total_blocks"] == 2
    assert stats["complete_blocks"] == 1
    assert stats["incomplete_blocks"] == 1
    assert stats["textures"] == 1

    catalog = manager.build_catalog("java", "1.20.1")
    assert [block.block_id for block in catalog] == ["test_block"]
    assert catalog[0].source == "mojang-resource"
    assert catalog[0].rgb == (40, 40, 200)

    blocks = manager.db.get_blocks("java", "1.20.1")
    target = next(block for block in blocks if block["block_id"] == "test_block")
    assert "top" in target["faces"] and "side" in target["faces"]
    manager.close()


def test_parse_bedrock_zip_and_build_catalog(tmp_path):
    path = _bedrock_zip(tmp_path)
    manager = ResourceManager(tmp_path / "root")
    version_id = manager.db.upsert_version("bedrock", "1.20.80", "release", "test")
    stats = bedrock.parse_bedrock_zip(path, version_id, manager.db, manager.root)

    assert stats["total_blocks"] == 1
    assert stats["complete_blocks"] == 1
    catalog = manager.build_catalog("bedrock", "1.20.80")
    assert catalog[0].block_id == "stone"
    assert catalog[0].source == "mojang-resource"
    assert catalog[0].rgb == (120, 120, 120)
    manager.close()


def test_bedrock_legacy_blocks_json(tmp_path):
    path = tmp_path / "legacy.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Pack/textures/terrain_texture.json",
            '// comment\n{"texture_data":{"stone":{"textures":"textures/blocks/stone"},},}',
        )
        archive.writestr("Pack/textures/blocks/stone.png", _png_bytes((70, 70, 70)))
        archive.writestr(
            "Pack/resource_pack/blocks.json",
            '// legacy mapping\n{"format_version":"1.20.80","stone":{"textures":"stone"},}',
        )
    manager = ResourceManager(tmp_path / "legacy-root")
    version_id = manager.db.upsert_version("bedrock", "1.20.80", "release", "test")
    stats = bedrock.parse_bedrock_zip(path, version_id, manager.db, manager.root)
    assert stats["complete_blocks"] == 1
    catalog = manager.build_catalog("bedrock", "1.20.80")
    assert catalog[0].block_id == "stone"
    manager.close()


def test_jsonc_comments_and_trailing_commas():
    from Moge.core.resources.jsonc import loads_jsonc

    payload = '// head\n{"a": 1, /* block */ "b": "http://x", "c": [1,2,],}'
    assert loads_jsonc(payload) == {"a": 1, "b": "http://x", "c": [1, 2]}


def test_texture_dedup_and_prune(tmp_path):
    database = ResourceDatabase(tmp_path / "index.db")
    features = {"mean_rgb": (1, 2, 3), "median_rgb": (1, 2, 3), "lab": (1.0, 2.0, 3.0)}
    texture_file = tmp_path / "tex.png"
    texture_file.write_bytes(_png_bytes())
    database.upsert_texture("abc", str(texture_file), 10, features)
    database.upsert_texture("abc", str(texture_file), 10, features)
    assert database.texture_count() == 1
    assert database.orphan_textures()
    removed = database.prune_orphan_textures()
    assert removed == 1
    assert not texture_file.exists()
    database.close()


def test_java_version_range_parser():
    assert java.parse_version_tuple("1.20") == (1, 20)
    assert java.parse_version_tuple("1.20.1") == (1, 20, 1)
    assert java.parse_version_tuple("snapshot-24w14a") is None


def test_real_resource_mode_uses_database(tmp_path, monkeypatch):
    from Moge.core.modes import minecraft as minecraft_mode
    from Moge.core.modes import registry

    jar = _java_jar(tmp_path)
    root = tmp_path / "resource-root"
    manager = ResourceManager(root)
    version_id = manager.db.upsert_version("java", "1.20.1", "release", "test", status="ready")
    java.parse_client_jar(jar, version_id, manager.db, manager.root)
    manager.close()

    monkeypatch.setenv("MOGE_RESOURCE_DIR", str(root))
    settings = dict(registry.default_settings("minecraft"))
    settings.update({"version": "1.20.1", "resource_mode": "real"})
    blocks = minecraft_mode.candidate_blocks(settings)
    assert any(block.source == "mojang-resource" for block in blocks)
    assert any(block.block_id == "test_block" for block in blocks)


def test_real_resource_mode_without_download_raises(tmp_path, monkeypatch):
    from Moge.core.modes import minecraft as minecraft_mode
    from Moge.core.modes import registry

    monkeypatch.setenv("MOGE_RESOURCE_DIR", str(tmp_path / "empty-resource-root"))
    settings = dict(registry.default_settings("minecraft"))
    settings.update({"version": "1.20.1", "resource_mode": "real"})
    with pytest.raises(ValueError):
        minecraft_mode.candidate_blocks(settings)


def test_resource_worker_reports_progress_and_cancel(qapp, monkeypatch):
    from Moge.ui import resource_dialog

    class FakeManager:
        def __init__(self, root):
            self.root = root

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def fetch_java(self, version, force=False, progress=None, should_cancel=None):
            if progress:
                progress(50, "half")
                progress(100, "done")
            return {"edition": "java", "version": version, "status": "ready"}

    monkeypatch.setattr(resource_dialog, "ResourceManager", FakeManager)
    worker = resource_dialog.ResourceTaskWorker("root", [("java", "1.20.1")])
    events = {"progress": [], "finished": [], "cancelled": []}
    worker.progress.connect(lambda percent, text: events["progress"].append(percent))
    worker.finished.connect(events["finished"].append)
    worker.cancelled.connect(lambda: events["cancelled"].append(True))
    worker.run()

    assert events["finished"]
    assert 100 in events["progress"]
    assert not events["cancelled"]

    cancelled_worker = resource_dialog.ResourceTaskWorker("root", [("java", "1.20.1")])
    cancelled_worker.cancel()
    cancelled_worker.cancelled.connect(lambda: events["cancelled"].append(True))
    cancelled_worker.run()
    assert events["cancelled"]


def test_safezip_extract(tmp_path):
    from Moge.core.resources.safezip import extract

    archive = tmp_path / "data.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("assets/keep.txt", "ok")
        handle.writestr("assets/sub/nested.txt", "nested")
        handle.writestr("other/skip.txt", "skip")
    destination = tmp_path / "out"
    written = extract(archive, destination, allowed_prefixes=("assets/",))
    assert len(written) == 2
    assert (destination / "assets" / "keep.txt").read_text() == "ok"
    assert not (destination / "other" / "skip.txt").exists()


def test_bedrock_release_mapping_and_asset_choice():
    releases = [
        {"tag_name": "v1.20.80.5", "name": "1.20.80.5", "assets": [], "zipball_url": "https://example/src.zip"},
        {"tag_name": "v1.21.0.3-preview", "name": "preview", "assets": []},
        {
            "tag_name": "v1.21.0.3",
            "name": "1.21.0.3",
            "assets": [
                {"name": "bedrock-samples-v1.21.0.3-min.zip", "browser_download_url": "min"},
                {"name": "bedrock-samples-v1.21.0.3-full.zip", "browser_download_url": "full"},
            ],
        },
    ]
    source = bedrock.find_release(releases, "1.20.80")
    assert source["tag_name"] == "v1.20.80.5"
    asset = bedrock.choose_asset(source)
    assert asset["source_kind"] == "github-source"
    assert asset["browser_download_url"] == "https://example/src.zip"

    release = bedrock.find_release(releases, "1.21.0")
    asset = bedrock.choose_asset(release)
    assert asset["source_kind"] == "release-asset"
    assert asset["browser_download_url"] == "full"


def test_java_local_client_jar_and_download(tmp_path, monkeypatch):
    home = tmp_path / "mc"
    local_jar = home / "versions" / "1.20.1" / "1.20.1.jar"
    local_jar.parent.mkdir(parents=True)
    local_jar.write_bytes(b"local-jar")
    monkeypatch.setenv("MOGE_MINECRAFT_HOME", str(home))
    assert java.find_local_client_jar("1.20.1") == local_jar
    path, sha, origin = java.ensure_client_jar("1.20.1", {"downloads": {}}, root=tmp_path)
    assert path == local_jar and len(sha) == 64 and origin == "local-install"

    monkeypatch.setattr(java, "find_local_client_jar", lambda version: None)

    def fake_download(url, destination, **kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"downloaded")
        return destination

    monkeypatch.setattr(java, "download_file", fake_download)
    metadata = {"downloads": {"client": {"url": "http://example/client.jar", "size": 10, "sha1": "abc"}}}
    downloaded, _sha, origin = java.ensure_client_jar("1.20.1", metadata, root=tmp_path)
    assert downloaded.exists() and origin == "mojang-piston"


def test_network_hash_helpers(tmp_path):
    from Moge.core.resources.network import _hash_matches, file_hashes

    path = tmp_path / "file.bin"
    path.write_bytes(b"moge")
    sha1, sha256 = file_hashes(path)
    assert len(sha1) == 40 and len(sha256) == 64
    assert _hash_matches(path, sha1, sha256)
    assert not _hash_matches(path, "0" * 40, sha256)
