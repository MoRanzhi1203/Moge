##############################
# core/resources/bedrock.py - Bedrock 官方样例资源与方块解析
##############################

import hashlib
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

from Moge.core.resources.catalog import choose_face, metadata_for
from Moge.core.resources.features import analyze_texture_bytes
from Moge.core.resources.jsonc import loads_jsonc
from Moge.core.resources.network import cached_json, download_file
from Moge.core.resources.paths import bedrock_cache_dir, cache_dir, textures_dir
from Moge.core.resources.safezip import validate_members

RELEASES_URL = "https://api.github.com/repos/Mojang/bedrock-samples/releases"
TARGET_VERSIONS = ("1.20.0", "1.20.80", "1.21.0", "1.21.50")


def fetch_releases(root: Path = None, force: bool = False) -> list[dict]:
    """ 分页获取 GitHub Releases，并缓存；有限页数避免触发限流 """
    cache_path = Path(cache_dir(root)) / "bedrock_releases.json"
    if not force and cache_path.exists() and time.time() - cache_path.stat().st_mtime <= 21600:
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    releases: list[dict] = []
    for page in range(1, 11):
        url = f"{RELEASES_URL}?per_page=100&page={page}"
        page_data = cached_json(
            Path(cache_dir(root)) / f"bedrock_releases_p{page}.json",
            url,
            max_age=21600,
            force=force,
            timeout=40,
        )
        if not isinstance(page_data, list):
            break
        releases.extend(page_data)
        if len(page_data) < 100:
            break
    cache_path.write_text(json.dumps(releases, ensure_ascii=False), encoding="utf-8")
    return releases


def parse_version_tuple(value: str) -> Optional[tuple]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?", str(value))
    if not match:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def find_release(releases: list[dict], target: str) -> Optional[dict]:
    """ 标签/名称都解析为数字版本，按前缀匹配，避免模糊文件名匹配 """
    target_tuple = parse_version_tuple(target)
    if target_tuple is None:
        return None
    preview_requested = "preview" in target.lower()
    best = None
    best_extra = 99
    for release in releases:
        tag = str(release.get("tag_name", ""))
        name = str(release.get("name", ""))
        if "preview" in (tag + name).lower() and not preview_requested:
            continue
        version_tuple = parse_version_tuple(tag) or parse_version_tuple(name)
        if version_tuple is None:
            continue
        if version_tuple[:len(target_tuple)] != target_tuple:
            continue
        extra = len(version_tuple) - len(target_tuple)
        if extra < best_extra:
            best = release
            best_extra = extra
    return best


def choose_asset(release: dict) -> Optional[dict]:
    assets = [asset for asset in release.get("assets", []) if str(asset.get("name", "")).lower().endswith(".zip")]
    if assets:
        full = [asset for asset in assets if "full" in asset["name"].lower()]
        selected = dict((full or assets)[0])
        selected["source_kind"] = "release-asset"
        return selected
    # 官方 tag 源码归档同样来自 Mojang/bedrock-samples，包含完整 resource_pack
    zipball = release.get("zipball_url")
    if zipball:
        return {
            "name": f"{release.get('tag_name', 'bedrock-samples')}-source.zip",
            "size": None,
            "browser_download_url": zipball,
            "digest": "",
            "source_kind": "github-source",
        }
    return None


def fetch_and_parse(
    target: str,
    version_id: int,
    db,
    root: Path = None,
    progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    dry_run: bool = False,
) -> dict:
    releases = fetch_releases(root)
    release = find_release(releases, target)
    if release is None:
        raise ValueError(f"Bedrock Samples 未发布目标版本 {target} 的资源")
    asset = choose_asset(release)
    if asset is None:
        raise ValueError(f"版本 {target} 的 Release 中没有 ZIP 资源")

    plan = {
        "edition": "bedrock",
        "version": target,
        "tag": release.get("tag_name"),
        "asset": asset.get("name"),
        "size": asset.get("size", 0),
        "url": asset.get("browser_download_url"),
        "digest": asset.get("digest", ""),
        "source_kind": asset.get("source_kind", "release-asset"),
    }
    if dry_run:
        return plan

    digest = str(asset.get("digest") or "")
    sha256 = digest.split(":")[-1] if digest.startswith("sha256:") else None
    target_path = Path(bedrock_cache_dir(root)) / f"{target}.zip"
    zip_path = download_file(
        asset["browser_download_url"],
        target_path,
        expected_size=asset.get("size"),
        sha256=sha256,
        progress=progress,
        should_cancel=should_cancel,
        timeout=90,
    )
    stats = parse_bedrock_zip(zip_path, version_id, db, root, should_cancel=should_cancel)
    stats.update(
        {
            "source": "bedrock-samples",
            "tag": release.get("tag_name"),
            "asset": asset.get("name"),
            "source_kind": asset.get("source_kind", "release-asset"),
        }
    )
    return stats


def _resolve_texture_value(value) -> Optional[str]:
    if isinstance(value, list):
        for item in value:
            resolved = _resolve_texture_value(item)
            if resolved:
                return resolved
        return None
    if isinstance(value, dict):
        for key in ("path", "textures", "texture"):
            if key in value:
                return _resolve_texture_value(value[key])
        return None
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("\\", "/")
    if text.endswith(".png"):
        text = text[:-4]
    if text.startswith("textures/"):
        text = text[len("textures/"):]
    return text


def _iter_texture_infos(infos: list[zipfile.ZipInfo]) -> dict[str, zipfile.ZipInfo]:
    mapping = {}
    for info in infos:
        name = info.filename.replace("\\", "/")
        marker = "/textures/blocks/"
        if marker in name and name.endswith(".png"):
            relative = name.split(marker, 1)[1][:-4]
            mapping[f"blocks/{relative}"] = info
            mapping.setdefault(relative.split("/")[-1], info)
    return mapping


def _find_texture(ref: str, texture_infos: dict[str, zipfile.ZipInfo]):
    if ref is None:
        return None
    normalized = ref.replace("blocks/", "", 1) if ref.startswith("blocks/") else ref
    for key in (f"blocks/{normalized}", normalized, normalized.split("/")[-1]):
        if key in texture_infos:
            return texture_infos[key]
    return None


def _legacy_face_refs(value, terrain_data: dict) -> dict[str, str]:
    """ 解析 resource_pack/blocks.json 的 textures 字段（字符串或面字典） """
    def resolve(name):
        if not isinstance(name, str):
            return None
        terrain_entry = terrain_data.get(name)
        return _resolve_texture_value(terrain_entry) if terrain_entry else _resolve_texture_value(name)

    faces: dict[str, str] = {}
    if isinstance(value, str):
        ref = resolve(value)
        if ref:
            faces = {"side": ref, "top": ref, "bottom": ref, "front": ref}
        return faces
    if isinstance(value, dict):
        for face_key, name in value.items():
            ref = resolve(name)
            if not ref:
                continue
            if face_key in ("*", "side", "east", "west", "south"):
                faces.setdefault("side", ref)
            if face_key in ("*", "up"):
                faces.setdefault("top", ref)
            if face_key in ("*", "down"):
                faces.setdefault("bottom", ref)
            if face_key in ("*", "north", "side"):
                faces.setdefault("front", ref)
    return faces


def _material_instances(data: dict) -> dict:
    root = data.get("minecraft:block") if isinstance(data.get("minecraft:block"), dict) else data
    components = root.get("components") or {}
    inner_block = components.get("minecraft:block")
    if isinstance(inner_block, dict):
        nested = inner_block.get("components") or {}
        if "minecraft:material_instances" in nested:
            return nested["minecraft:material_instances"] or {}
    return components.get("minecraft:material_instances") or {}


def _block_identifier(data: dict) -> str:
    root = data.get("minecraft:block") if isinstance(data.get("minecraft:block"), dict) else data
    return str((root.get("description") or {}).get("identifier") or root.get("identifier") or "")


def parse_bedrock_zip(
    zip_path: Path,
    version_id: int,
    db,
    root: Path = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> dict:
    """ 解析 terrain_texture → 纹理文件，以及方块定义 → 材质引用 """
    tex_dir = Path(textures_dir(root))
    tex_dir.mkdir(parents=True, exist_ok=True)
    block_records = []
    texture_cache: dict[str, dict] = {}
    missing = set()

    with zipfile.ZipFile(zip_path) as archive:
        infos = validate_members(archive)
        texture_infos = _iter_texture_infos(infos)
        terrain_info = None
        block_infos = []
        flipbook_info = None
        legacy_blocks_info = None
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.endswith("/textures/terrain_texture.json") or name == "textures/terrain_texture.json":
                terrain_info = info
            elif name.endswith("/textures/flipbook_textures.json"):
                flipbook_info = info
            elif name.endswith("/resource_pack/blocks.json"):
                legacy_blocks_info = info
            elif "/blocks/" in name and name.endswith(".json") and "/textures/" not in name:
                block_infos.append(info)

        terrain_data = {}
        if terrain_info is not None:
            payload = loads_jsonc(archive.read(terrain_info).decode("utf-8-sig"))
            terrain_data = payload.get("texture_data") or {}

        animated = set()
        if flipbook_info is not None:
            try:
                entries = loads_jsonc(archive.read(flipbook_info).decode("utf-8-sig"))
                for entry in entries if isinstance(entries, list) else []:
                    texture = entry.get("flipbook_texture") if isinstance(entry, dict) else None
                    if isinstance(texture, str):
                        animated.add(texture.replace("textures/", "").replace(".png", ""))
            except Exception:
                pass

        definitions = []
        for info in block_infos:
            try:
                data = loads_jsonc(archive.read(info).decode("utf-8-sig"))
            except Exception:
                continue
            identifier = _block_identifier(data)
            block_id = identifier.replace("minecraft:", "")
            if block_id:
                definitions.append((block_id, data))

        source_blocks = definitions
        legacy_blocks = {}
        if legacy_blocks_info is not None:
            try:
                payload = loads_jsonc(archive.read(legacy_blocks_info).decode("utf-8-sig"))
                for key, value in payload.items():
                    if key == "format_version":
                        continue
                    if isinstance(value, dict):
                        textures = value.get("textures")
                        if textures:
                            legacy_blocks[key.replace("minecraft:", "")] = textures
                    elif isinstance(value, str):
                        legacy_blocks[key.replace("minecraft:", "")] = value
            except Exception:
                legacy_blocks = {}
        if legacy_blocks:
            source_blocks = [(block_id, {"__legacy__": textures}) for block_id, textures in legacy_blocks.items()]
        elif not definitions:
            from Moge.core.resources.catalog import BUILTIN_BY_ID
            source_blocks = [
                (key, {"components": {"minecraft:material_instances": {"*": {"texture": key}}}})
                for key in terrain_data
                if key in BUILTIN_BY_ID
            ]

        for block_id, data in source_blocks:
            if should_cancel is not None and should_cancel():
                raise RuntimeError("cancelled")
            material = _material_instances(data)
            terrain_key = block_id.split(":")[-1]
            face_refs: dict[str, str] = {}
            if "__legacy__" in data:
                for face_name, ref in _legacy_face_refs(data["__legacy__"], terrain_data).items():
                    face_refs.setdefault(face_name, ref)
            elif material:
                for face_key, instance in material.items():
                    texture_key = instance.get("texture") if isinstance(instance, dict) else instance
                    terrain_entry = terrain_data.get(texture_key) if texture_key else None
                    ref = _resolve_texture_value(terrain_entry) if terrain_entry else _resolve_texture_value(texture_key)
                    if not ref:
                        continue
                    if face_key in ("*", "side", "east", "west", "south"):
                        face_refs.setdefault("side", ref)
                    if face_key in ("*", "up"):
                        face_refs.setdefault("top", ref)
                    if face_key in ("*", "down"):
                        face_refs.setdefault("bottom", ref)
                    if face_key in ("*", "north", "side"):
                        face_refs.setdefault("front", ref)
            if not face_refs and terrain_key in terrain_data:
                ref = _resolve_texture_value(terrain_data.get(terrain_key))
                if ref:
                    face_refs = {"side": ref, "top": ref, "bottom": ref, "front": ref}

            faces = {}
            for face_name, ref in face_refs.items():
                info = _find_texture(ref, texture_infos)
                if info is None:
                    missing.add(ref)
                    continue
                key = info.filename
                if key not in texture_cache:
                    data_bytes = archive.read(info)
                    digest = hashlib.sha256(data_bytes).hexdigest()
                    features = analyze_texture_bytes(data_bytes)
                    target = tex_dir / f"{digest}.png"
                    if not target.exists():
                        target.write_bytes(data_bytes)
                    animated_flag = ref.replace("blocks/", "") in animated
                    db.upsert_texture(digest, str(target), len(data_bytes), features, animated=animated_flag)
                    texture_cache[key] = {"sha256": digest, "rgb": features["mean_rgb"], "lab": features["lab"]}
                faces[face_name] = texture_cache[key]

            metadata = metadata_for(block_id)
            chosen = choose_face(faces, metadata["visible_face"])
            if chosen:
                faces.setdefault("all", chosen)
            complete = bool(faces)
            block_records.append(
                {
                    "block_id": block_id,
                    "name": metadata["name"],
                    "category": metadata["category"],
                    "obtainability": metadata["obtainability"],
                    "renewable": metadata["renewable"],
                    "buildable": metadata["buildable"],
                    "gravity": metadata["gravity"],
                    "transparent": metadata["transparent"],
                    "orientation": metadata["orientation"],
                    "visible_face": metadata["visible_face"],
                    "complete": complete,
                    "tinted": False,
                    "notes": metadata["notes"] + ("" if complete else "；缺少可用 Bedrock 纹理"),
                    "faces": faces,
                }
            )

    db.replace_blocks(version_id, block_records)
    complete = sum(1 for block in block_records if block["complete"])
    return {
        "total_blocks": len(block_records),
        "complete_blocks": complete,
        "incomplete_blocks": len(block_records) - complete,
        "textures": len({face["sha256"] for block in block_records for face in block["faces"].values()}),
        "missing_textures": len(missing),
        "tinted_blocks": 0,
    }
