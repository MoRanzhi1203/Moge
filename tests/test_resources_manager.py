import json

from Moge.core.resources import bedrock, cli, java
from Moge.core.resources.manager import ResourceManager


def test_manager_fetch_java_dry_run_and_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(
        java, "load_manifest", lambda root=None, force=False: {
            "versions": [{"id": "1.20.1", "type": "release", "url": "meta-url"}]
        }
    )
    monkeypatch.setattr(java, "version_metadata", lambda *args, **kwargs: {
        "downloads": {"client": {"url": "http://example/client.jar", "size": 1, "sha1": "abc"}}
    })
    monkeypatch.setattr(java, "find_local_client_jar", lambda version: None)

    manager = ResourceManager(tmp_path / "root")
    plan = manager.fetch_java("1.20.1", dry_run=True)
    assert plan["url"] == "http://example/client.jar"

    jar = tmp_path / "client.jar"
    jar.write_bytes(b"x")
    monkeypatch.setattr(java, "ensure_client_jar", lambda *args, **kwargs: (jar, "sha", "test"))
    monkeypatch.setattr(java, "parse_client_jar", lambda *args, **kwargs: {
        "total_blocks": 3, "complete_blocks": 2, "incomplete_blocks": 1, "textures": 2,
        "missing_textures": 0, "tinted_blocks": 0,
    })
    result = manager.fetch_java("1.20.1", force=True)
    assert result["status"] == "ready"
    assert manager.db.get_version("java", "1.20.1")["status"] == "ready"
    assert manager.fetch_java("1.20.1")["skipped"] is True
    manager.close()


def test_manager_fetch_bedrock_dry_run_and_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(bedrock, "fetch_and_parse", lambda *args, **kwargs: {
        "edition": "bedrock", "version": "1.20.80", "tag": "v1.20.80.5", "asset": "x.zip",
        "size": 1, "url": "http://example/x.zip", "digest": "", "source_kind": "github-source",
        **({"total_blocks": 2, "complete_blocks": 2, "incomplete_blocks": 0, "textures": 2,
            "missing_textures": 0, "tinted_blocks": 0} if not kwargs.get("dry_run") else {}),
    })
    manager = ResourceManager(tmp_path / "root")
    plan = manager.fetch_bedrock("1.20.80", dry_run=True)
    assert plan["tag"] == "v1.20.80.5"

    result = manager.fetch_bedrock("1.20.80", force=True)
    assert result["status"] == "ready"
    assert manager.fetch_bedrock("1.20.80")["skipped"] is True
    manager.close()


def test_manager_verify_delete_rebuild(tmp_path):
    from test_resources_core import _java_jar

    jar = _java_jar(tmp_path)
    manager = ResourceManager(tmp_path / "root")
    version_id = manager.db.upsert_version(
        "java", "1.20.1", "release", "test", status="ready", resource_path=str(jar)
    )
    stats = java.parse_client_jar(jar, version_id, manager.db, manager.root)
    assert stats["complete_blocks"] == 1
    report = manager.report()
    assert report["stats"]["blocks"] >= 1

    verified = manager.verify("java", "1.20.1")
    assert verified["ok"] is True

    rebuilt = manager.rebuild("java", "1.20.1")
    assert rebuilt["complete_blocks"] == 1

    diff = manager.diff("java", "1.20.1", "1.20.1")
    assert diff["common"] >= 1

    deleted = manager.delete("java", "1.20.1")
    assert deleted["deleted"] is True
    assert manager.db.get_version("java", "1.20.1") is None
    manager.close()


def test_manager_resolve_range_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr(java, "load_manifest", lambda root=None, force=False: {
        "versions": [
            {"id": "1.20", "type": "release", "url": ""},
            {"id": "1.20.1", "type": "release", "url": ""},
            {"id": "1.21", "type": "release", "url": ""},
        ]
    })
    manager = ResourceManager(tmp_path / "root")
    assert manager.resolve_java_range("1.20", "1.20.1") == ["1.20", "1.20.1"]
    manager.db.upsert_version("java", "1.20.1", "release", "test", status="ready")
    report = manager.report()
    assert report["versions"][0]["version"] == "1.20.1"
    manager.close()


class FakeManager:
    def __init__(self, root):
        self.root = root

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def list_java_versions(self, release_only=True, limit=0):
        return [{"edition": "java", "version": "1.20.1", "version_type": "release", "status": "ready", "blocks": 2}]

    def list_bedrock_versions(self):
        return [{"edition": "bedrock", "version": "1.20.80", "version_type": "release", "status": "ready", "blocks": 1, "tag": "v1.20.80.5"}]

    def fetch_java(self, version, force=False, dry_run=False, progress=None, should_cancel=None):
        return {"edition": "java", "version": version, "status": "ready"}

    def fetch_bedrock(self, version, force=False, dry_run=False, progress=None, should_cancel=None):
        return {"edition": "bedrock", "version": version, "status": "ready"}

    def resolve_java_range(self, start, end, release_only=True):
        return ["1.20.1"]

    def sync_java_manifest(self, force=False):
        return {"count": 1, "latest": {"release": "1.20.1"}}

    def verify(self, edition, version, full=False):
        return {"ok": True, "checked_faces": 1, "missing": []}

    def delete(self, edition, version):
        return {"deleted": True}

    def rebuild(self, edition, version):
        return {"edition": edition, "version": version, "status": "ready", "complete_blocks": 1}

    def report(self):
        return {"root": "x", "stats": {"versions": 1}, "versions": []}


def test_cli_commands_with_fake_manager(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ResourceManager", FakeManager)
    assert cli.main(["list", "--edition", "java"]) == 0
    assert "1.20.1" in capsys.readouterr().out
    assert cli.main(["list", "--edition", "bedrock"]) == 0
    assert cli.main(["fetch", "--edition", "java", "--version", "1.20.1"]) == 0
    assert cli.main(["fetch", "--edition", "bedrock", "--version", "1.20.80", "--dry-run"]) == 0
    assert cli.main(["fetch-range", "--start", "1.20", "--end", "1.20.1", "--dry-run"]) == 0
    assert cli.main(["sync-manifest"]) == 0
    assert cli.main(["verify", "--edition", "java", "--version", "1.20.1"]) == 0
    assert cli.main(["delete", "--edition", "java", "--version", "1.20.1"]) == 0
    assert cli.main(["rebuild", "--edition", "java", "--version", "1.20.1"]) == 0
    output = tmp_path / "report.json"
    assert cli.main(["report", "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["stats"]["versions"] == 1
