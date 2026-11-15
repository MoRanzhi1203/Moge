##############################
# core/resources/java.py - Java 版版本清单、客户端 JAR 与方块解析
##############################

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from Moge.core.resources.catalog import choose_face, metadata_for
from Moge.core.resources.features import analyze_texture_bytes
from Moge.core.resources.network import cached_json, download_file
from Moge.core.resources.paths import cache_dir, java_cache_dir, textures_dir
from Moge.core.resources.safezip import validate_members

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
BLOCKSTATES_PREFIX = "assets/minecraft/blockstates/"
MODELS_PREFIX = "assets/minecraft/models/"
TEXTURES_PREFIX = "assets/minecraft/textures/"


def load_manifest(root: Path = None, force: bool = False) -> dict:
    return cached_json(Path(cache_dir(root)) / "java_version_manifest.json", MANIFEST_URL, force=force)


def parse_version_tuple(value: str) -> Optional[tuple]:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(value))
    if not match:
        return None
    return tuple(int(part) for part in match.groups() if part is not None)


def list_versions(manifest: dict, release_only: bool = True) -> list[dict]:
    versions = manifest.get("versions", [])
    if release_only:
        versions = [item for item in versions if item.get("type") == "release"]
    return list(versions)


def find_version(manifest: dict, version: str) -> Optional[dict]:
    for item in manifest.get("versions", []):
        if item.get("id") == version:
            return item
    return None


def version_metadata(manifest: dict, version: str, root: Path = None, force: bool = False) -> dict:
    entry = find_version(manifest, version)
    if entry is None:
        raise ValueError(f"官方清单中没有版本 {version}")
    cache_path = Path(cache_dir(root)) / "java" / f"{version}.json"
    return cached_json(cache_path, entry["url"], force=force)


def find_local_client_jar(version: str) -> Optional[Path]:
    candidates = []
    env_home = os.environ.get("MOGE_MINECRAFT_HOME")
    if env_home:
        candidates.append(Path(env_home))
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / ".minecraft")
    candidates.append(Path.cwd() / ".minecraft")
    for root in candidates:
        jar = root / "versions" / version / f"{version}.jar"
        if jar.is_file():
            return jar
    return None


def ensure_client_jar(version: str, metadata: dict, root: Path = None,
                      progress: Optional[Callable[[int, int], None]] = None,
                      should_cancel: Optional[Callable[[], bool]] = None) -> tuple:
    """ 返回 (jar_path, sha256, 来源说明)；优先本地安装，缺失时按官方元数据下载校验 """
    local = find_local_client_jar(version)
    client = (metadata.get("downloads") or {}).get("client") or {}
    expected_sha1 = client.get("sha1")
    expected_size = client.get("size")
    if local is not None:
        if expected_sha1:
            digest = hashlib.sha1(local.read_bytes()).hexdigest()
            if digest.lower() == expected_sha1.lower():
                return local, _sha256_file(local), "local-install"
        else:
            return local, _sha256_file(local), "local-install"

    url = client.get("url")
    if not url:
        raise ValueError(f"版本 {version} 元数据缺少客户端下载地址")
    target = Path(java_cache_dir(root)) / version / "client.jar"
    downloaded = download_file(
        url, target,
        expected_size=expected_size,
        sha1=expected_sha1,
        progress=progress,
        should_cancel=should_cancel,
        timeout=60,
    )
    return downloaded, _sha256_file(downloaded), "mojang-piston"


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _safe_json(data: bytes) -> Optional[dict]:
    try:
        value = json.loads(data.decode("utf-8-sig"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _resolve_ref(value: str, textures: dict[str, str], depth: int = 0) -> str:
    while isinstance(value, str) and value.startswith("#") and depth < 12:
        key = value[1:]
        if key not in textures:
            return value
        value = textures[key]
        depth += 1
    return value


def _resolve_model(name: str, models: dict[str, dict], seen=None) -> dict:
    """ 解析 parent 继承，保留原始面引用，最终统一解析纹理变量 """
    name = str(name).replace("minecraft:", "")
    seen = seen or set()
    if name in seen:
        return {"textures": {}, "elements": [], "parents": []}
    seen.add(name)
    model = (
        models.get(name)
        or models.get(f"block/{name}")
        or models.get(f"blocks/{name}")
        or models.get(name.replace("block/", "blocks/"))
    )
    if not model:
        return {"textures": {}, "elements": [], "parents": []}

    textures: dict[str, str] = {}
    elements: list[dict] = []
    parents: list[str] = [name]
    parent = model.get("parent")
    if isinstance(parent, str):
        parent_data = _resolve_model(parent, models, seen)
        textures.update(parent_data["textures"])
        elements = parent_data["elements"]
        parents.extend(parent_data["parents"])
    textures.update(model.get("textures") or {})
    if isinstance(model.get("elements"), list):
        elements = model["elements"]
    return {"textures": textures, "elements": elements, "parents": parents}


def _resolve_texture_map(textures: dict[str, str]) -> dict[str, str]:
    resolved = {}
    for key, value in textures.items():
        resolved[key] = _resolve_ref(str(value), textures)
    return resolved


def _resolve_elements(elements: list[dict], textures: dict[str, str]) -> list[dict]:
    resolved_elements = []
    for element in elements:
        faces = {}
        for face_name, face in (element.get("faces") or {}).items():
            if not isinstance(face, dict):
                continue
            faces[face_name] = dict(
                face, texture=_resolve_ref(str(face.get("texture", "")), textures)
            )
        resolved_elements.append(dict(element, faces=faces))
    return resolved_elements


def _face_refs(model_data: dict) -> dict[str, str]:
    """ 将模型面映射到 top/side/bottom/front """
    faces: dict[str, str] = {}
    for element in model_data.get("elements") or []:
        for face_name, face in (element.get("faces") or {}).items():
            ref = face.get("texture", "")
            if not ref or ref.startswith("#"):
                continue
            if face_name == "up":
                faces.setdefault("top", ref)
            elif face_name == "down":
                faces.setdefault("bottom", ref)
            elif face_name == "north":
                faces.setdefault("front", ref)
                faces.setdefault("side", ref)
            elif face_name in ("east", "south", "west"):
                faces.setdefault("side", ref)
    if not faces:
        textures = model_data.get("textures") or {}
        for key in ("all", "side", "top", "bottom", "front"):
            if isinstance(textures.get(key), str) and not textures[key].startswith("#"):
                faces[key] = textures[key]
    return faces


def _normalize_texture_ref(ref: str) -> str:
    ref = ref.replace("minecraft:", "")
    if ref.startswith("textures/"):
        ref = ref[len("textures/"):]
    if not ref.startswith(("block/", "blocks/")):
        ref = "block/" + ref
    return ref


def _find_texture_info(ref: str, texture_infos: dict[str, zipfile.ZipInfo]):
    normalized = _normalize_texture_ref(ref)
    candidates = [normalized]
    if normalized.startswith("block/"):
        candidates.append("blocks/" + normalized[len("block/"):])
    elif normalized.startswith("blocks/"):
        candidates.append("block/" + normalized[len("blocks/"):])
    for candidate in candidates:
        info = texture_infos.get(candidate)
        if info is not None:
            return info, candidate
    return None, normalized


CUBE_TEXTURE_KEYS = (
    frozenset({"all"}),
    frozenset({"top", "side"}),
    frozenset({"end", "side"}),
    frozenset({"down", "up"}),
    frozenset({"north", "south", "east", "west"}),
)


def _elements_cover_cube(elements: list[dict]) -> bool:
    """ 由模型元素的实际包围盒判断是否填满 16³ 立方体 """
    covered = np.zeros((16, 16, 16), dtype=bool)
    for element in elements:
        rotation = element.get("rotation")
        if isinstance(rotation, dict) and float(rotation.get("angle", 0) or 0) % 360:
            return False
        start = element.get("from") or [0, 0, 0]
        end = element.get("to") or [16, 16, 16]
        try:
            axis_ranges = [sorted((float(start[i]), float(end[i]))) for i in range(3)]
        except (TypeError, ValueError, IndexError):
            return False
        ranges = []
        for low, high in axis_ranges:
            low_i = max(0, min(16, int(round(low))))
            high_i = max(0, min(16, int(round(high))))
            if high_i <= low_i:
                return False
            ranges.append((low_i, high_i))
        (x0, x1), (y0, y1), (z0, z1) = ranges
        covered[x0:x1, y0:y1, z0:z1] = True
    return bool(covered.all())


def _is_full_cube_model(resolved: dict) -> bool:
    """ 无 elements 的模型按贴图槽位判断是否为原版完整立方体模板 """
    elements = resolved.get("elements") or []
    if elements:
        return _elements_cover_cube(elements)
    textures = resolved.get("textures") or {}
    keys = {key for key, value in textures.items() if isinstance(value, str)}
    if any(required.issubset(keys) for required in CUBE_TEXTURE_KEYS):
        return True
    for parent in resolved.get("parents") or []:
        name = str(parent)
        if name == "block/cube" or name.startswith("block/cube_") or name.startswith("block/cube"):
            return True
    return False


def _state_label(state: dict, chosen_model: str) -> str:
    """ 记录实际取面的 blockstate 变体键，便于追溯方块状态 """
    variants = state.get("variants") or {}
    if isinstance(variants, dict):
        for key, value in variants.items():
            models = []
            if isinstance(value, dict) and isinstance(value.get("model"), str):
                models.append(value["model"])
            elif isinstance(value, list):
                models = [
                    item["model"] for item in value
                    if isinstance(item, dict) and isinstance(item.get("model"), str)
                ]
            if chosen_model in models:
                return str(key)
    if state.get("multipart"):
        return "multipart"
    return ""


def parse_client_jar(
    jar_path: Path,
    version_id: int,
    db,
    root: Path = None,
    progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> dict:
    """ 解析 blockstate → model → texture，写入 SQLite 与内容寻址贴图目录 """
    root = Path(root) if root else None
    tex_dir = Path(textures_dir(root))
    tex_dir.mkdir(parents=True, exist_ok=True)
    blockstates: dict[str, dict] = {}
    models: dict[str, dict] = {}
    texture_infos: dict[str, zipfile.ZipInfo] = {}
    animated_refs = set()

    with zipfile.ZipFile(jar_path) as archive:
        infos = validate_members(archive, (BLOCKSTATES_PREFIX, MODELS_PREFIX, TEXTURES_PREFIX))
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith(BLOCKSTATES_PREFIX) and name.endswith(".json"):
                data = _safe_json(archive.read(info))
                if data is not None:
                    blockstates[name[len(BLOCKSTATES_PREFIX):-5]] = data
            elif name.startswith(MODELS_PREFIX) and name.endswith(".json"):
                data = _safe_json(archive.read(info))
                if data is not None:
                    models[name[len(MODELS_PREFIX):-5]] = data
            elif name.startswith(TEXTURES_PREFIX) and name.endswith(".png"):
                texture_infos[name[len(TEXTURES_PREFIX):-4]] = info
            elif name.startswith(TEXTURES_PREFIX) and name.endswith(".png.mcmeta"):
                animated_refs.add(name[len(TEXTURES_PREFIX):-len(".png.mcmeta")])

        block_records = []
        texture_cache: dict[str, dict] = {}
        missing_textures = set()
        total = len(blockstates)
        for index, (block_id, state) in enumerate(sorted(blockstates.items())):
            if should_cancel is not None and should_cancel():
                raise RuntimeError("cancelled")
            model_names = _collect_models(state)
            face_refs: dict[str, str] = {}
            tinted = False
            chosen_model = ""
            resolved_models: list[dict] = []
            for model_name in model_names:
                raw = _resolve_model(model_name, models)
                resolved_models.append(raw)
                resolved_textures = _resolve_texture_map(raw["textures"])
                resolved = {
                    "textures": resolved_textures,
                    "elements": _resolve_elements(raw["elements"], resolved_textures),
                }
                if not face_refs:
                    refs = _face_refs(resolved)
                    if refs:
                        face_refs = refs
                        chosen_model = model_name
                for element in resolved.get("elements") or []:
                    for face in (element.get("faces") or {}).values():
                        if int(face.get("tintindex", -1)) >= 0:
                            tinted = True
            full_cube = bool(model_names) and all(_is_full_cube_model(item) for item in resolved_models)
            geometry = "full_cube" if full_cube else ("partial" if face_refs else "unknown")

            faces = {}
            block_missing = 0
            for face_name, ref in face_refs.items():
                info, normalized = _find_texture_info(ref, texture_infos)
                if info is None:
                    missing_textures.add(normalized)
                    block_missing += 1
                    continue
                key = info.filename
                if key not in texture_cache:
                    data = archive.read(info)
                    digest = hashlib.sha256(data).hexdigest()
                    features = analyze_texture_bytes(data)
                    target = tex_dir / f"{digest}.png"
                    if not target.exists():
                        target.write_bytes(data)
                    db.upsert_texture(digest, str(target), len(data), features, animated=normalized in animated_refs)
                    texture_cache[key] = {
                        "sha256": digest,
                        "rgb": features["mean_rgb"],
                        "lab": features["lab"],
                    }
                faces[face_name] = texture_cache[key]

            metadata = metadata_for(block_id)
            chosen = choose_face(faces, metadata["visible_face"])
            if chosen:
                faces.setdefault("all", chosen)
            complete = bool(faces)
            verified = complete and block_missing == 0
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
                    "tinted": tinted,
                    "geometry": geometry,
                    "block_state": _state_label(state, chosen_model),
                    "verified": verified,
                    "notes": metadata["notes"] + ("" if complete else "；缺少可用贴图引用"),
                    "faces": faces,
                }
            )
            if progress and total:
                progress(index + 1, total)

    db.replace_blocks(version_id, block_records)
    complete = sum(1 for block in block_records if block["complete"])
    return {
        "total_blocks": len(block_records),
        "complete_blocks": complete,
        "incomplete_blocks": len(block_records) - complete,
        "full_cube_blocks": sum(1 for block in block_records if block["geometry"] == "full_cube"),
        "verified_blocks": sum(1 for block in block_records if block["verified"]),
        "textures": len({face["sha256"] for block in block_records for face in block["faces"].values()}),
        "missing_textures": len(missing_textures),
        "tinted_blocks": sum(1 for block in block_records if block["tinted"]),
    }


def _collect_models(state: dict) -> list[str]:
    names = []
    variants = state.get("variants") or {}
    if isinstance(variants, dict):
        for value in variants.values():
            if isinstance(value, dict):
                if isinstance(value.get("model"), str):
                    names.append(value["model"])
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and isinstance(item.get("model"), str):
                        names.append(item["model"])
    multipart = state.get("multipart") or []
    if isinstance(multipart, list):
        for part in multipart:
            apply = part.get("apply") if isinstance(part, dict) else None
            if isinstance(apply, dict) and isinstance(apply.get("model"), str):
                names.append(apply["model"])
            elif isinstance(apply, list):
                for item in apply:
                    if isinstance(item, dict) and isinstance(item.get("model"), str):
                        names.append(item["model"])
    return list(dict.fromkeys(names))
