##############################
# core/palette_exchange.py - 普通像素调色板导入/导出
##############################

import csv
import re
from pathlib import Path

import numpy as np

from Moge.core.color_spaces import nearest_lab_index, srgb_to_lab
from Moge.core.models import PaletteEntry


def _parse_rgb(value: str):
    text = str(value or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", text):
        return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
    parts = [part for part in re.split(r"[,;\\s]+", text) if part]
    if len(parts) >= 3:
        try:
            rgb = tuple(int(round(float(part))) for part in parts[:3])
        except ValueError:
            return None
        if all(0 <= channel <= 255 for channel in rgb):
            return rgb
    return None


def load_palette_csv(path: str) -> list[tuple[str, tuple[int, int, int]]]:
    """ 读取用户调色板 CSV：支持 hex 或 r,g,b 列 """
    palette: list[tuple[str, tuple[int, int, int]]] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("调色板 CSV 缺少表头")
        for row in reader:
            name = str(row.get("name") or row.get("color") or "").strip()
            rgb = _parse_rgb(row.get("hex") or row.get("#") or "")
            if rgb is None and row.get("r") is not None:
                rgb = _parse_rgb(f"{row.get('r')},{row.get('g')},{row.get('b')}")
            if rgb is not None and rgb not in [item[1] for item in palette]:
                palette.append((name or "#{:02X}{:02X}{:02X}".format(*rgb), rgb))
    if not palette:
        raise ValueError("调色板 CSV 中没有有效颜色")
    return palette


def remap_to_palette(labels: np.ndarray, entries: list,
                     palette: list[tuple[str, tuple[int, int, int]]]):
    """ 将现有网格颜色映射到导入调色板，不重新聚类，仅做最近色替换 """
    array = np.asarray(labels)
    new_entries = [
        PaletteEntry(
            id=f"palette-{index:03d}",
            name=name,
            rgb=rgb,
            source="imported-palette",
            meta={"brand": "Pixel", "series": "导入", "code": f"{index + 1:03d}"},
        )
        for index, (name, rgb) in enumerate(palette)
    ]
    used = sorted({int(value) for value in np.unique(array) if value >= 0})
    if not used:
        return array.copy(), new_entries
    old_rgb = np.array([entries[index].rgb for index in used], dtype=np.uint8)
    new_rgb = np.array([rgb for _name, rgb in palette], dtype=np.uint8)
    mapping = nearest_lab_index(srgb_to_lab(new_rgb), srgb_to_lab(old_rgb))
    new_labels = np.full(array.shape, -1, dtype=np.int32)
    for old_index, new_index in zip(used, mapping):
        new_labels[array == old_index] = int(new_index)
    return new_labels, new_entries


def export_palette_csv(result, path: str) -> str:
    """ 导出当前作品的调色板索引、HEX、RGB 与用量 """
    target = Path(path)
    if target.suffix.lower() != ".csv":
        target = target.with_suffix(".csv")
    counts = result.stats.get("counts", {})
    fields = ["index", "name", "hex", "r", "g", "b", "count"]
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, entry in enumerate(result.grid.entries):
            count = int(counts.get(entry.id, 0))
            if count <= 0 and result.mode in ("beads", "minecraft"):
                continue
            writer.writerow(
                {
                    "index": index + 1,
                    "name": entry.name,
                    "hex": "#{:02X}{:02X}{:02X}".format(*entry.rgb),
                    "r": entry.rgb[0],
                    "g": entry.rgb[1],
                    "b": entry.rgb[2],
                    "count": count,
                }
            )
    return str(target)
