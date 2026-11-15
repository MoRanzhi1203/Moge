##############################
# core/samples.py - 内置示例图库资源定位与清单
##############################

import json
import sys
from pathlib import Path
from typing import Optional

from Moge.core.models import GridSpec

_CACHE: dict = {}


def assets_root() -> Path:
    """ 开发环境与 PyInstaller 环境均可定位 assets 目录 """
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "assets"
    return Path(__file__).resolve().parents[1] / "assets"


def samples_root() -> Path:
    return assets_root() / "samples"


def manifest_path() -> Path:
    return samples_root() / "manifest.json"


def load_manifest(force: bool = False) -> list[dict]:
    path = manifest_path()
    if not path.is_file():
        return []
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if not force and key in _CACHE:
        return _CACHE[key]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    images = payload.get("images") if isinstance(payload, dict) else payload
    images = [item for item in images or [] if isinstance(item, dict)]
    if len(_CACHE) >= 4:
        _CACHE.clear()
    _CACHE[key] = images
    return images


def image_path(entry: dict) -> Path:
    return samples_root() / str(entry.get("filename") or "")


def thumbnail_path(entry: dict) -> Path:
    thumb = str(entry.get("thumbnail") or "")
    if thumb:
        return samples_root() / thumb
    return image_path(entry)


def categories(entries: Optional[list[dict]] = None) -> list[str]:
    return sorted({str(item.get("category") or "") for item in (entries or load_manifest()) if item.get("category")})


def recommended_grid(entry: dict) -> GridSpec:
    grid = entry.get("recommended_grid") or {}
    width = max(4, min(256, int(grid.get("width") or 64)))
    height = max(4, min(256, int(grid.get("height") or 64)))
    return GridSpec(width=width, height=height)
