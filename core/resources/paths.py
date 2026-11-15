##############################
# core/resources/paths.py - 本地缓存目录
##############################

import os
from pathlib import Path

APP_DIR_NAME = "Moge"
RESOURCE_DIR_NAME = "resources"


def resource_root() -> Path:
    """ 资源根目录；默认写入用户本地应用数据，不进入 Git 仓库 """
    override = os.environ.get("MOGE_RESOURCE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_DIR_NAME / RESOURCE_DIR_NAME
    return Path.home() / ".moge" / RESOURCE_DIR_NAME


def ensure_layout(root: Path = None) -> Path:
    root = Path(root) if root else resource_root()
    for child in ("cache", "textures", "java", "bedrock"):
        (root / child).mkdir(parents=True, exist_ok=True)
    return root


def database_path(root: Path = None) -> Path:
    root = ensure_layout(root)
    return root / "index.db"


def cache_dir(root: Path = None) -> Path:
    return ensure_layout(root) / "cache"


def textures_dir(root: Path = None) -> Path:
    return ensure_layout(root) / "textures"


def java_cache_dir(root: Path = None) -> Path:
    return ensure_layout(root) / "java"


def bedrock_cache_dir(root: Path = None) -> Path:
    return ensure_layout(root) / "bedrock"
