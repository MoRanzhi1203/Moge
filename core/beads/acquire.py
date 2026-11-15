##############################
# core/beads/acquire.py - 公开拼豆色卡获取、解析与数据库导入
##############################

import argparse
import colorsys
import csv
import json
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np

from Moge.core.beads.database import BeadPaletteDatabase
from Moge.core.beads.paths import database_path, raw_cache_dir, report_path
from Moge.core.color_spaces import delta_e_00, srgb_to_lab

PINDOU_BASE = "https://raw.githubusercontent.com/HansBug/pindou-color-data/main/"
BEADCOLORS_BASE = "https://raw.githubusercontent.com/maxcleme/beadcolors/master/"
USER_AGENT = "Moge-Bead-Palette-Fetcher/1.0 (public references, local-use)"
CACHE_MAX_AGE = 24 * 3600

SOURCES = [
    {
        "id": "pindou-color-data",
        "name": "HansBug/pindou-color-data",
        "url": "https://github.com/HansBug/pindou-color-data",
        "license": "MIT",
        "trust": "community",
        "notes": "公开拼豆色卡数据仓库（JSON），非品牌官方测量；Artkal 系列引用官方 PDF/色卡图。",
    },
    {
        "id": "beadcolors",
        "name": "maxcleme/beadcolors",
        "url": "https://github.com/maxcleme/beadcolors",
        "license": "MIT",
        "trust": "community",
        "notes": "社区维护色号库（v3 CSV），含贡献者字段；RGB 为屏幕参考值。",
    },
]

# path, palette id, brand, series, size, expected count
PINDOU_DATASETS = [
    ("mard-221-github/colors.json", "pindou:mard-221-github", "MARD", "MARD 221", "2.6mm", 221),
    ("mard-221-alfonse-doudou/colors.json", "pindou:mard-221-alfonse", "MARD", "MARD 221（Alfonse 参考）", "2.6mm", 221),
    ("mard-291-github/colors.json", "pindou:mard-291-github", "MARD", "MARD 291", "2.6mm", 291),
    ("coco-291/colors.json", "pindou:coco-291", "COCO", "COCO 291", "2.6mm", 291),
    ("manman-278/colors.json", "pindou:manman-278", "漫漫", "漫漫 278", "2.6mm", 278),
    ("panpan-289/colors.json", "pindou:panpan-289", "盼盼", "盼盼 289", "2.6mm", 289),
    ("mixiaowo-290/colors.json", "pindou:mixiaowo-290", "咪小窝", "咪小窝 290", "2.6mm", 290),
    ("youken-public-174/colors.json", "pindou:youken-174", "优肯", "优肯 174", "2.6mm", 174),
    ("artkal-c-197-official/colors.json", "pindou:artkal-c-197", "Artkal", "Artkal C 197", "2.6mm", 197),
    ("artkal-m-221-official/colors.json", "pindou:artkal-m-221", "Artkal", "Artkal M 221", "2.6mm", 221),
    ("artkal-c197-m221-418-official/colors.json", "pindou:artkal-cm-418", "Artkal", "Artkal C+M 418", "2.6mm", 418),
]

BEADCOLORS_DATASETS = [
    ("gen/v3/hama.csv", "beadcolors:hama", "Hama", "Hama Midi", "5mm", 92),
    ("gen/v3/hama_mini.csv", "beadcolors:hama-mini", "Hama", "Hama Mini", "2.6mm", 78),
    ("gen/v3/hama_maxi.csv", "beadcolors:hama-maxi", "Hama", "Hama Maxi", "10mm", 25),
    ("gen/v3/perler.csv", "beadcolors:perler", "Perler", "Perler Standard", "5mm", 103),
    ("gen/v3/perler_mini.csv", "beadcolors:perler-mini", "Perler", "Perler Mini", "2.6mm", 41),
    ("gen/v3/perler_caps.csv", "beadcolors:perler-caps", "Perler", "Perler Caps", "5mm", 26),
    ("gen/v3/nabbi.csv", "beadcolors:nabbi", "Nabbi", "Nabbi", "5mm", 30),
    ("gen/v3/artkal_a.csv", "beadcolors:artkal-a", "Artkal", "Artkal A", "2.6mm", 145),
    ("gen/v3/artkal_c.csv", "beadcolors:artkal-c", "Artkal", "Artkal C（社区）", "2.6mm", 174),
    ("gen/v3/artkal_m.csv", "beadcolors:artkal-m", "Artkal", "Artkal M（社区）", "2.6mm", 174),
    ("gen/v3/artkal_r.csv", "beadcolors:artkal-r", "Artkal", "Artkal R", "5mm", 89),
    ("gen/v3/artkal_s.csv", "beadcolors:artkal-s", "Artkal", "Artkal S", "5mm", 199),
    ("gen/v3/mard.csv", "beadcolors:mard", "MARD", "MARD 291（社区）", "2.6mm", 291),
    ("gen/v3/yant.csv", "beadcolors:yant", "Yant", "Yant", "", 119),
    ("gen/v3/diamondDotz.csv", "beadcolors:diamond-dotz", "Diamond Dotz", "Diamond Dotz", "drill", 461),
]

QUALITY_TRUST = {
    "official_pdf": "official",
    "official_chart_image": "official",
    "official_chart_image_sampled": "sampled",
    "third_party_public_repository": "community",
}

def _fetch(url: str, cache_file: Path, force: bool = False) -> str:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    if cache_file.is_file() and not force and time.time() - cache_file.stat().st_mtime <= CACHE_MAX_AGE:
        return cache_file.read_text(encoding="utf-8-sig")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        text = response.read().decode("utf-8-sig")
    cache_file.write_text(text, encoding="utf-8")
    return text


def color_family(rgb: tuple[int, int, int]) -> str:
    red, green, blue = (channel / 255.0 for channel in rgb)
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    if value < 0.10:
        return "黑色"
    if saturation < 0.10:
        if value > 0.9:
            return "白色"
        return "灰色" if value > 0.35 else "黑色"
    degrees = hue * 360.0
    if 15 <= degrees < 45 and value < 0.62:
        return "棕色"
    if degrees < 15 or degrees >= 345:
        return "红色"
    if degrees < 45:
        return "橙色"
    if degrees < 70:
        return "黄色"
    if degrees < 165:
        return "绿色"
    if degrees < 195:
        return "青色"
    if degrees < 255:
        return "蓝色"
    if degrees < 290:
        return "紫色"
    if degrees < 320:
        return "品红"
    return "粉色"


def classify_material(name: str, group: str = "", transparency=None, notes: str = "") -> str:
    text = f"{name} {notes}".lower()
    if transparency or group == "CT" or "transparent" in text or "clear" in text or "透明" in text:
        return "transparent"
    if group == "CG" or "glow" in text or "luminous" in text or "夜光" in text:
        return "glow"
    if group == "CP" or "pearl" in text:
        return "pearl"
    if "neon" in text or "fluorescent" in text or "荧光" in text:
        return "fluorescent"
    if "metallic" in text:
        return "metallic"
    if "silk" in text or "matte" in text:
        return "special"
    if group == "CE":
        return "special"
    return "solid"


def _hex(rgb, alpha=255) -> str:
    text = "#{:02X}{:02X}{:02X}".format(*rgb)
    return text if alpha >= 255 else text + f"{alpha:02X}"


def parse_pindou(text: str, dataset: tuple, source_meta: dict) -> dict:
    path, palette_id, brand, series, size, expected = dataset
    payload = json.loads(text)
    source_map = {item.get("id"): item for item in payload.get("sources", [])}
    colors = []
    missing = 0
    for item in payload.get("colors", []):
        rgb = item.get("rgb") or []
        if len(rgb) < 3:
            missing += 1
            continue
        red, green, blue = (max(0, min(255, int(channel))) for channel in rgb[:3])
        alpha = int(rgb[3]) if len(rgb) >= 4 else 255
        source = source_map.get(item.get("source") or "", {})
        quality = str(source.get("quality") or "")
        trust = QUALITY_TRUST.get(quality, "community")
        material = classify_material(
            str(item.get("name") or ""), str(item.get("group") or ""),
            item.get("transparency"), str(item.get("notes") or ""),
        )
        colors.append(
            {
                "code": str(item.get("code") or "").strip(),
                "name": str(item.get("name") or "").strip(),
                "r": red, "g": green, "b": blue, "alpha": alpha,
                "hex": str(item.get("hex") or _hex((red, green, blue), alpha)),
                "color_family": color_family((red, green, blue)),
                "material": material,
                "trust": trust,
                "source_url": str(source.get("url") or ""),
                "source_quality": quality,
                "notes": str(item.get("notes") or source.get("notes") or ""),
                "verified": trust == "official",
                "contributor": "",
            }
        )
    colors = [color for color in colors if color["code"]]
    duplicates = len(colors) - len({color["code"] for color in colors})
    deduped = {}
    for color in colors:
        deduped.setdefault(color["code"], color)
    colors = list(deduped.values())
    trust_counts = defaultdict(int)
    for color in colors:
        trust_counts[color["trust"]] += 1
    palette_trust = "official" if colors and all(c["trust"] == "official" for c in colors) else (
        "sampled" if any(c["trust"] == "sampled" for c in colors) else "community"
    )
    return {
        "id": palette_id,
        "brand": brand,
        "series": series,
        "size": size,
        "source_id": source_meta["id"],
        "trust": palette_trust,
        "expected_count": max(expected, int(payload.get("count") or 0)),
        "color_count": len(colors),
        "license": source_meta["license"],
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "notes": str(payload.get("description") or ""),
        "colors": colors,
        "missing": missing + max(0, expected - len(colors)),
        "duplicates": duplicates,
        "trust_counts": dict(trust_counts),
        "source_file": path,
    }


def parse_beadcolors(text: str, dataset: tuple, source_meta: dict) -> dict:
    path, palette_id, brand, series, size, expected = dataset
    colors = []
    missing = 0
    duplicates = 0
    seen = set()
    for line in text.splitlines():
        if not line.strip() or line.lower().startswith("reference_code"):
            continue
        try:
            parts = next(csv.reader([line]))
            if len(parts) < 6:
                missing += 1
                continue
            code = parts[0].strip()
            name = parts[1].strip()
            red, green, blue = (int(parts[index]) for index in (3, 4, 5))
        except Exception:
            missing += 1
            continue
        if not code:
            missing += 1
            continue
        if code in seen:
            duplicates += 1
            continue
        seen.add(code)
        red, green, blue = (max(0, min(255, channel)) for channel in (red, green, blue))
        material = classify_material(name)
        contributor = parts[12].strip() if len(parts) > 12 else ""
        colors.append(
            {
                "code": code,
                "name": name,
                "r": red, "g": green, "b": blue, "alpha": 255,
                "hex": _hex((red, green, blue)),
                "color_family": color_family((red, green, blue)),
                "material": material,
                "trust": "community",
                "source_url": f"{BEADCOLORS_BASE}{path}",
                "source_quality": "community_maintained_csv",
                "notes": f"贡献者：{contributor}" if contributor else "",
                "verified": False,
                "contributor": contributor,
            }
        )
    return {
        "id": palette_id,
        "brand": brand,
        "series": series,
        "size": size,
        "source_id": source_meta["id"],
        "trust": "community",
        "expected_count": expected,
        "color_count": len(colors),
        "license": source_meta["license"],
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "notes": "社区维护 CSV（含贡献者字段）",
        "colors": colors,
        "missing": missing + max(0, expected - len(colors)),
        "duplicates": duplicates,
        "trust_counts": {"community": len(colors)},
        "source_file": path,
    }


def compute_conflicts(palettes: list[dict], limit: int = 5000) -> list[dict]:
    """ 同品牌同色号跨来源差异；保留双份，仅记录 Delta E00 """
    grouped = defaultdict(list)
    for palette in palettes:
        for color in palette["colors"]:
            grouped[(palette["brand"], color["code"])].append((palette["id"], color))
    conflicts = []
    for (brand, code), items in grouped.items():
        if len(items) < 2:
            continue
        for index in range(len(items)):
            for other in range(index + 1, len(items)):
                palette_a, color_a = items[index]
                palette_b, color_b = items[other]
                if palette_a == palette_b:
                    continue
                rgb_a = np.array([[color_a["r"], color_a["g"], color_a["b"]]], dtype=np.uint8)
                rgb_b = np.array([[color_b["r"], color_b["g"], color_b["b"]]], dtype=np.uint8)
                distance = float(delta_e_00(srgb_to_lab(rgb_a), srgb_to_lab(rgb_b))[0])
                if distance < 0.5:
                    continue
                conflicts.append(
                    {
                        "brand": brand,
                        "code": code,
                        "palette_a": palette_a,
                        "palette_b": palette_b,
                        "hex_a": color_a["hex"],
                        "hex_b": color_b["hex"],
                        "delta_e00": round(distance, 3),
                        "resolution": "kept-separate",
                    }
                )
                if len(conflicts) >= limit:
                    return conflicts
    conflicts.sort(key=lambda item: (item["brand"], item["code"]))
    return conflicts


def acquire(force: bool = False, root: Path = None, verbose: bool = True) -> dict:
    raw_dir = raw_cache_dir(root)
    source_meta = {source["id"]: source for source in SOURCES}
    palettes = []
    for dataset in PINDOU_DATASETS:
        path = dataset[0]
        url = PINDOU_BASE + path
        text = _fetch(url, raw_dir / "pindou" / path.replace("/", "_"), force)
        palettes.append(parse_pindou(text, dataset, source_meta["pindou-color-data"]))
    for dataset in BEADCOLORS_DATASETS:
        path = dataset[0]
        url = BEADCOLORS_BASE + path
        text = _fetch(url, raw_dir / "beadcolors" / path.replace("/", "_"), force)
        palettes.append(parse_beadcolors(text, dataset, source_meta["beadcolors"]))

    conflicts = compute_conflicts(palettes)
    meta = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "schema": "moge-bead-palette/1",
        "palette_count": len(palettes),
        "color_count": sum(palette["color_count"] for palette in palettes),
        "licenses": json.dumps({source["id"]: source["license"] for source in SOURCES}),
    }
    db_path = database_path(root)
    with BeadPaletteDatabase(db_path) as database:
        database.replace_all(palettes, SOURCES, conflicts, meta)
        metadata = database.metadata()

    report = {
        "generated_at": meta["updated_at"],
        "database": str(db_path),
        "licenses": {source["id"]: source["license"] for source in SOURCES},
        "sources": SOURCES,
        "palettes": [
            {
                "id": palette["id"],
                "brand": palette["brand"],
                "series": palette["series"],
                "size": palette["size"],
                "source_id": palette["source_id"],
                "trust": palette["trust"],
                "expected_count": palette["expected_count"],
                "color_count": palette["color_count"],
                "missing_count": palette["missing"],
                "duplicates": palette["duplicates"],
                "trust_counts": palette["trust_counts"],
                "license": palette["license"],
                "source_file": palette["source_file"],
            }
            for palette in palettes
        ],
        "totals": {
            "palettes": len(metadata["palettes"]),
            "colors": metadata["colors"],
            "brands": sorted({palette["brand"] for palette in palettes}),
            "trust_counts": metadata["trust_counts"],
            "material_counts": metadata["material_counts"],
            "conflicts": metadata["conflicts"],
        },
        "conflicts": metadata["conflict_examples"],
    }
    report_file = report_path(root)
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if verbose:
        print(f"database: {db_path}")
        print(f"palettes: {metadata['palettes']} colors: {metadata['colors']}")
        print(f"brands: {', '.join(report['totals']['brands'])}")
        print(f"trust: {metadata['trust_counts']}")
        print(f"materials: {metadata['material_counts']}")
        print(f"conflicts: {metadata['conflicts']} -> {report_file}")
    return report


def main():
    parser = argparse.ArgumentParser(description="Fetch public bead palettes into the Moge SQLite database.")
    parser.add_argument("--force", action="store_true", help="ignore the 24h raw cache and re-download")
    parser.add_argument("--root", default="", help="palette data root (default: %%LOCALAPPDATA%%/Moge/palettes)")
    args = parser.parse_args()
    report = acquire(force=args.force, root=Path(args.root) if args.root else None)
    return 0 if report["totals"]["colors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
