##############################
# core/beads/catalog.py - 拼豆色卡查询、筛选与跨品牌近似
##############################

from pathlib import Path
from typing import Optional

import numpy as np

from Moge.core.beads.database import BeadPaletteDatabase
from Moge.core.beads.paths import database_path
from Moge.core.color_spaces import delta_e_00, srgb_to_lab
from Moge.core.materials import BeadColor

_CACHE: dict = {}


def _cache_key(path: Path) -> tuple:
    stat = path.stat()
    return str(path), stat.st_mtime_ns, stat.st_size


def load_catalog(path: Path = None) -> list[BeadColor]:
    """ 读取 SQLite 色卡；数据库不存在时返回空列表 """
    target = Path(path) if path else database_path()
    if not target.is_file():
        return []
    key = _cache_key(target)
    cached = _CACHE.get(key)
    if cached is not None:
        return list(cached)
    with BeadPaletteDatabase(target) as database:
        catalog = database.load_catalog()
    if len(_CACHE) >= 4:
        _CACHE.clear()
    _CACHE[key] = catalog
    return list(catalog)


def load_catalog_with_meta(path: Path = None) -> tuple[list[BeadColor], dict]:
    target = Path(path) if path else database_path()
    if not target.is_file():
        return [], {}
    with BeadPaletteDatabase(target) as database:
        return database.load_catalog(), database.metadata()


def available_sizes(catalog: list[BeadColor], brand: str = "", series: str = "") -> list[str]:
    return sorted(
        {
            item.size for item in catalog
            if item.size and (not brand or item.brand == brand) and (not series or item.series == series)
        }
    )


def available_families(catalog: list[BeadColor], brand: str = "", series: str = "") -> list[str]:
    return sorted(
        {
            item.color_family for item in catalog
            if item.color_family and (not brand or item.brand == brand) and (not series or item.series == series)
        }
    )


def available_materials(catalog: list[BeadColor], brand: str = "", series: str = "") -> list[str]:
    return sorted(
        {
            item.material for item in catalog
            if item.material and (not brand or item.brand == brand) and (not series or item.series == series)
        }
    )


def preferred_selection(catalog: list[BeadColor]) -> tuple[str, str]:
    """ 默认 MARD 221；不存在时回退第一个品牌/系列 """
    if not catalog:
        return "", ""
    mard_series = sorted({item.series for item in catalog if item.brand == "MARD"})
    for name in ("MARD 221",):
        if name in mard_series:
            return "MARD", name
    if mard_series:
        return "MARD", mard_series[0]
    brand = catalog[0].brand
    series = sorted({item.series for item in catalog if item.brand == brand})[0]
    return brand, series


def nearest_cross_brand(rgb: tuple[int, int, int], catalog: list[BeadColor], brand: str = "") -> Optional[tuple[BeadColor, float]]:
    """ 跨品牌 Lab/Delta E00 近似参考；仅返回参考，不视为同一色号 """
    candidates = [item for item in catalog if not brand or item.brand != brand]
    if not candidates:
        return None
    palette_rgb = np.array([item.rgb for item in candidates], dtype=np.uint8)
    target_lab = srgb_to_lab(np.array([rgb], dtype=np.uint8))
    distances = delta_e_00(target_lab, srgb_to_lab(palette_rgb))
    index = int(np.argmin(distances))
    return candidates[index], float(distances[index])


def material_label(material: str) -> str:
    return {
        "solid": "实色",
        "transparent": "透明",
        "glow": "夜光",
        "fluorescent": "荧光",
        "pearl": "珠光",
        "metallic": "金属",
        "special": "特殊",
        "unknown": "未知",
    }.get(material or "solid", material)


def trust_label(trust: str) -> str:
    return {
        "official": "官方",
        "community": "社区",
        "sampled": "采样",
        "unknown": "未知",
    }.get(trust or "unknown", trust)
