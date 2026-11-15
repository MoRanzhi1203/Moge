##############################
# exporters/project.py - .moge 工程文件读写
##############################

import json
import zipfile
from pathlib import Path

import cv2
import numpy as np

from Moge.core.grid import upscale_grid
from Moge.core.models import GridSpec, PaletteEntry, PixelGrid, ProjectDocument, RenderResult

SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
ALLOWED_MEMBERS = {"manifest.json", "thumbnail.png"}


def _json_safe(value):
    """ 将 dataclass/元组等转换为可 JSON 序列化的结构 """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: _json_safe(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    return str(value)


def _manifest(result: RenderResult, source_path: str = None) -> dict:
    settings = _json_safe(result.settings)
    # 色卡从 SQLite 数据库恢复，工程文件只保留筛选条件，避免重复存储整份色卡
    if isinstance(settings, dict) and isinstance(settings.get("params"), dict):
        settings["params"].pop("catalog", None)
    return {
        "schema": SCHEMA_VERSION,
        "app": "Moge",
        "app_version": "2.0.0",
        "mode": result.mode,
        "created_at": result.created_at,
        "source_path": source_path or "",
        "settings": settings,
        "grid": {
            "width": int(result.grid.spec.width),
            "height": int(result.grid.spec.height),
            "labels": result.grid.labels.astype(int).tolist(),
            "entries": [
                {
                    "id": entry.id,
                    "name": entry.name,
                    "rgb": list(entry.rgb),
                    "source": entry.source,
                    "meta": entry.meta,
                }
                for entry in result.grid.entries
            ],
        },
    }


def save_project(path: str, result: RenderResult, source_path: str = None) -> str:
    """ 保存为 .moge（ZIP：manifest.json + thumbnail.png） """
    target = Path(path)
    if target.suffix.lower() != ".moge":
        target = target.with_suffix(".moge")

    manifest = _manifest(result, source_path)
    payload = json.dumps(manifest, ensure_ascii=False).encode("utf-8")

    thumbnail = upscale_grid(result.image, 4)
    if thumbnail.shape[2] == 4:
        bgra = cv2.cvtColor(thumbnail, cv2.COLOR_RGBA2BGRA)
    else:
        bgra = cv2.cvtColor(thumbnail, cv2.COLOR_RGB2BGR)
    ok, encoded = cv2.imencode(".png", bgra)
    if not ok:
        raise OSError("缩略图编码失败")

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", payload)
        archive.writestr("thumbnail.png", encoded.tobytes())
    return str(target)


def load_project(path: str) -> ProjectDocument:
    """ 读取并校验 .moge；只允许已知成员，避免路径穿越与超大解压 """
    source = Path(path)
    with zipfile.ZipFile(source, "r") as archive:
        names = set(archive.namelist())
        unknown = names - ALLOWED_MEMBERS
        if unknown:
            raise ValueError(f"工程文件包含未知成员：{sorted(unknown)}")
        if "manifest.json" not in names:
            raise ValueError("工程文件缺少 manifest.json")

        info = archive.getinfo("manifest.json")
        if info.file_size > MAX_MANIFEST_BYTES:
            raise ValueError("工程元数据过大")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

    if not isinstance(manifest, dict):
        raise ValueError("工程元数据格式错误")
    schema = int(manifest.get("schema", 0))
    if schema < 1 or schema > SCHEMA_VERSION:
        raise ValueError(f"不支持的工程版本：{schema}")

    grid_data = manifest.get("grid") or {}
    spec = GridSpec(width=int(grid_data["width"]), height=int(grid_data["height"]))
    labels = np.array(grid_data.get("labels", []), dtype=np.int32)
    if labels.shape != (spec.height, spec.width):
        raise ValueError("工程网格尺寸与标签不一致")

    entries = []
    for item in grid_data.get("entries", []):
        entries.append(
            PaletteEntry(
                id=str(item["id"]),
                name=str(item["name"]),
                rgb=tuple(int(channel) for channel in item["rgb"]),
                source=str(item.get("source", "project")),
                meta=dict(item.get("meta") or {}),
            )
        )
    if entries and labels.size and labels.max() >= len(entries):
        raise ValueError("工程标签索引越界")

    grid = PixelGrid(spec=spec, labels=labels, entries=entries, mode=str(manifest.get("mode", "pixel")))
    return ProjectDocument(
        version=schema,
        app_version=str(manifest.get("app_version", "2.0.0")),
        mode=str(manifest.get("mode", "pixel")),
        grid=grid,
        settings=dict(manifest.get("settings") or {}),
        source_path=str(manifest.get("source_path") or "") or None,
        created_at=str(manifest.get("created_at", "")),
    )
