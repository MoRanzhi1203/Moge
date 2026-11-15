##############################
# core/beads/paths.py - 拼豆色卡数据库与缓存路径
##############################

import os
from pathlib import Path

APP_DIR_NAME = "Moge"
PALETTE_DIR_NAME = "palettes"


def palette_root() -> Path:
    override = os.environ.get("MOGE_PALETTE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_DIR_NAME / PALETTE_DIR_NAME
    return Path.home() / ".moge" / PALETTE_DIR_NAME


def database_path(root: Path = None) -> Path:
    base = Path(root) if root else palette_root()
    base.mkdir(parents=True, exist_ok=True)
    return base / "beads.db"


def raw_cache_dir(root: Path = None) -> Path:
    base = Path(root) if root else palette_root()
    target = base / "raw"
    target.mkdir(parents=True, exist_ok=True)
    return target


def report_path(root: Path = None) -> Path:
    base = Path(root) if root else palette_root()
    base.mkdir(parents=True, exist_ok=True)
    return base / "acquisition_report.json"
