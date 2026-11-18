##############################
# core/beads/pattern.py - 拼豆施工图数据模型（格子记录/符号/图例/底板分区）
##############################

import re
from typing import Optional

import numpy as np

# 黑白打印用符号表：数字、字母与常见可打印符号组合，足以覆盖大型品牌色卡
SYMBOL_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz@#$%&*+=?<>^~"

DEFAULT_BEAD_MM = 5.0


def symbol_for_index(index: int) -> str:
    """ 为调色板条目分配稳定、唯一的符号；超过符号表长度时追加序号 """
    index = int(index)
    if index < 0:
        return ""
    if index < len(SYMBOL_ALPHABET):
        return SYMBOL_ALPHABET[index]
    base = SYMBOL_ALPHABET[index % len(SYMBOL_ALPHABET)]
    return f"{base}{index // len(SYMBOL_ALPHABET)}"


def build_symbols(entries: list) -> dict[str, str]:
    """ 按条目顺序生成 id -> 符号映射 """
    return {entry.id: symbol_for_index(index) for index, entry in enumerate(entries)}


def entry_code(entry) -> str:
    return str((entry.meta or {}).get("code") or "")


def abbrev_for(entry) -> str:
    """ 格内缩写：优先色号，过长时取前 4 个字符；无符号时退回名称前 2 字 """
    code = entry_code(entry).strip()
    if code:
        return code if len(code) <= 4 else code[:4]
    return str(entry.name or "")[:2]


def _hex(rgb) -> str:
    if not rgb:
        return ""
    return "#{:02X}{:02X}{:02X}".format(*tuple(int(channel) for channel in rgb[:3]))


def _record_flags(material: str) -> tuple[bool, bool]:
    material = (material or "").lower()
    transparent = material == "transparent"
    special = material not in ("", "solid", "unknown")
    return transparent, special


def build_cells(labels: np.ndarray, entries: list, symbols: Optional[dict] = None,
                locked: Optional[np.ndarray] = None) -> list[dict]:
    """ 生成逐格统一结构；空白格与白色珠子在此层面明确区分 """
    array = np.asarray(labels)
    if array.ndim != 2:
        raise ValueError("labels 必须为二维数组")
    if symbols is None:
        symbols = build_symbols(entries)
    lock_mask = None if locked is None else np.asarray(locked, dtype=bool)
    cells: list[dict] = []
    for row in range(array.shape[0]):
        for col in range(array.shape[1]):
            value = int(array[row, col])
            is_locked = bool(lock_mask[row, col]) if lock_mask is not None and lock_mask.shape == array.shape else False
            if value < 0 or value >= len(entries):
                cells.append(
                    {
                        "x": col,
                        "y": row,
                        "bead_id": "",
                        "brand": "",
                        "series": "",
                        "code": "",
                        "name": "",
                        "rgb": None,
                        "hex": "",
                        "symbol": "",
                        "is_empty": True,
                        "material": "",
                        "transparent": False,
                        "special": False,
                        "locked": is_locked,
                    }
                )
                continue
            entry = entries[value]
            meta = entry.meta or {}
            material = str(meta.get("material") or "solid")
            transparent, special = _record_flags(material)
            transparent = transparent or bool(meta.get("transparent"))
            special = (
                special
                or bool(meta.get("special"))
                or str(meta.get("orientation") or "none") not in ("none", "")
                or str(meta.get("geometry") or "full_cube") == "partial"
            )
            cells.append(
                {
                    "x": col,
                    "y": row,
                    "bead_id": entry.id,
                    "brand": str(meta.get("brand") or ""),
                    "series": str(meta.get("series") or ""),
                    "code": str(meta.get("code") or ""),
                    "name": entry.name,
                    "rgb": list(entry.rgb),
                    "hex": _hex(entry.rgb),
                    "symbol": symbols.get(entry.id, ""),
                    "is_empty": False,
                    "material": material,
                    "transparent": transparent,
                    "special": special,
                    "locked": is_locked,
                }
            )
    return cells


def _counts(labels: np.ndarray) -> dict[int, int]:
    flat = np.asarray(labels).reshape(-1)
    valid = flat[flat >= 0]
    if valid.size == 0:
        return {}
    values, counts = np.unique(valid, return_counts=True)
    return {int(value): int(count) for value, count in zip(values, counts)}


def is_white_bead(entry) -> bool:
    """ 白色系珠子：名称含“白”且实际色值接近白色；空白格永远不算 """
    name = str(entry.name or "")
    rgb = tuple(int(channel) for channel in entry.rgb)
    near_white = min(rgb) >= 200 and (max(rgb) - min(rgb)) <= 30
    return ("白" in name or name.strip().lower() == "white") and near_white


def bead_summary(labels: np.ndarray, entries: list) -> dict:
    """ 珠子统计：空白格不计入总珠子数，白色珠子单独计数 """
    array = np.asarray(labels)
    counts = _counts(array)
    total_cells = int(array.size)
    total_beads = int(sum(counts.values()))
    white_beads = sum(count for index, count in counts.items() if is_white_bead(entries[index]))
    transparent_beads = 0
    special_beads = 0
    for index, count in counts.items():
        meta = entries[index].meta or {}
        material = str(meta.get("material") or "solid").lower()
        if material == "transparent":
            transparent_beads += count
        if material not in ("", "solid", "unknown"):
            special_beads += count
    return {
        "total_cells": total_cells,
        "filled_cells": total_beads,
        "empty_cells": total_cells - total_beads,
        "total_beads": total_beads,
        "used_colors": len(counts),
        "white_beads": int(white_beads),
        "transparent_beads": int(transparent_beads),
        "special_beads": int(special_beads),
    }


def legend_rows(labels: np.ndarray, entries: list, symbols: Optional[dict] = None,
                include_unused: bool = True) -> list[dict]:
    """ 图例行：色号、名称、数量、占比与材质标记 """
    if symbols is None:
        symbols = build_symbols(entries)
    counts = _counts(np.asarray(labels))
    total = sum(counts.values())
    rows: list[dict] = []
    for index, entry in enumerate(entries):
        count = int(counts.get(index, 0))
        if count <= 0 and not include_unused:
            continue
        meta = entry.meta or {}
        material = str(meta.get("material") or "solid")
        transparent, special = _record_flags(material)
        rows.append(
            {
                "index": index,
                "id": entry.id,
                "brand": str(meta.get("brand") or ""),
                "series": str(meta.get("series") or ""),
                "code": str(meta.get("code") or ""),
                "name": entry.name,
                "rgb": tuple(int(channel) for channel in entry.rgb),
                "hex": _hex(entry.rgb),
                "symbol": symbols.get(entry.id, ""),
                "count": count,
                "ratio": (count / total) if total else 0.0,
                "used": count > 0,
                "material": material,
                "transparent": transparent,
                "special": special,
            }
        )
    return rows


def board_label(row: int, col: int) -> str:
    """ 底板编号：行用字母，列用数字，如 A1 / B3 """
    row = max(0, int(row))
    letters = ""
    value = row
    while True:
        letters = chr(ord("A") + value % 26) + letters
        value = value // 26 - 1
        if value < 0:
            break
    return f"{letters}{int(col) + 1}"


def board_regions(width: int, height: int, board_width: int, board_height: int) -> list[dict]:
    """ 底板分区，带 A1 形式编号，供画布、统计与分页导出复用 """
    if board_width < 1 or board_height < 1:
        raise ValueError("底板尺寸必须大于 0")
    regions: list[dict] = []
    index = 0
    for row_start in range(0, height, board_height):
        for col_start in range(0, width, board_width):
            row = row_start // board_height
            col = col_start // board_width
            region = {
                "index": index,
                "row": row,
                "col": col,
                "label": board_label(row, col),
                "x0": col_start,
                "y0": row_start,
                "x1": min(col_start + board_width, width),
                "y1": min(row_start + board_height, height),
                "width": min(board_width, width - col_start),
                "height": min(board_height, height - row_start),
            }
            regions.append(region)
            index += 1
    return regions


def board_stats(labels: np.ndarray, board_width: int, board_height: int) -> list[dict]:
    """ 各底板分区的珠子/颜色/空白数量 """
    array = np.asarray(labels)
    height, width = array.shape
    result = []
    for region in board_regions(width, height, board_width, board_height):
        section = array[region["y0"]:region["y1"], region["x0"]:region["x1"]].reshape(-1)
        valid = section[section >= 0]
        values = np.unique(valid) if valid.size else np.array([])
        result.append(
            {
                "index": region["index"],
                "label": region["label"],
                "row": region["row"],
                "col": region["col"],
                "beads": int(valid.size),
                "empty": int(section.size - valid.size),
                "colors": int(len(values)),
            }
        )
    return result


def parse_bead_mm(entries: list, default: float = DEFAULT_BEAD_MM) -> float:
    """ 从色卡尺寸字段解析珠子直径（mm），失败时使用默认值 """
    for entry in entries:
        size = str((entry.meta or {}).get("size") or "")
        match = re.search(r"(\d+(?:\.\d+)?)", size)
        if match:
            try:
                value = float(match.group(1))
                if 1.0 <= value <= 20.0:
                    return value
            except ValueError:
                continue
    return float(default)


def pattern_size_mm(width: int, height: int, bead_mm: float = DEFAULT_BEAD_MM) -> tuple[float, float]:
    return float(width) * float(bead_mm), float(height) * float(bead_mm)
