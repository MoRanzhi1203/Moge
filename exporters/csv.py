##############################
# exporters/csv.py - 材料/颜色清单导出
##############################

import csv
import math
from pathlib import Path

from Moge.core.models import RenderResult


def _entry_extra(entry) -> dict:
    meta = entry.meta or {}
    return {
        "brand": meta.get("brand", ""),
        "series": meta.get("series", ""),
        "code": meta.get("code", ""),
        "category": meta.get("category", ""),
        "size": meta.get("size", ""),
        "color_family": meta.get("color_family", ""),
        "material": meta.get("material", ""),
        "trust": meta.get("trust", ""),
        "license": meta.get("license", ""),
        "source_url": meta.get("source_url", ""),
        "source": entry.source,
    }


def material_rows(result: RenderResult) -> list[dict]:
    counts = result.stats.get("counts", {})
    pack_size = int(result.stats.get("pack_size") or 0)
    rows = []
    for entry in result.grid.entries:
        count = int(counts.get(entry.id, 0))
        if count <= 0:
            continue
        rows.append(
            {
                "id": entry.id,
                "name": entry.name,
                "hex": "#{:02X}{:02X}{:02X}".format(*entry.rgb),
                "rgb": f"{entry.rgb[0]},{entry.rgb[1]},{entry.rgb[2]}",
                "count": count,
                "packs": math.ceil(count / pack_size) if pack_size else "",
                **_entry_extra(entry),
            }
        )
    rows.sort(key=lambda row: (-row["count"], row["id"]))
    return rows


def export_materials_csv(result: RenderResult, path: str) -> str:
    """ 导出 UTF-8 BOM CSV，便于 Excel 直接打开中文材料名 """
    target = Path(path)
    if target.suffix.lower() != ".csv":
        target = target.with_suffix(".csv")

    rows = material_rows(result)
    fields = [
        "id", "name", "hex", "rgb", "count", "packs", "brand", "series", "code",
        "category", "size", "color_family", "material", "trust", "license", "source_url", "source",
    ]
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return str(target)
