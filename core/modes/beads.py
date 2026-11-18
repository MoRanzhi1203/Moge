##############################
# core/modes/beads.py - 拼豆图纸模式
##############################

import numpy as np

from Moge.core.beads.pattern import (
    abbrev_for,
    bead_summary,
    board_stats,
    build_symbols,
    parse_bead_mm,
    pattern_size_mm,
)
from Moge.core.color_spaces import delta_e_00, nearest_lab_index, srgb_to_lab
from Moge.core.materials import (
    BEAD_CATALOG,
    BeadColor,
    filter_beads,
)
from Moge.core.models import GridSpec, MaterialRef, PaletteEntry, PipelineConfig
from Moge.core.pipeline import PipelineContext, apply_blank_mask, register_stage

MODE_KEY = "beads"
MODE_LABEL = "拼豆图纸"

BEAD_DEFAULTS: dict[str, object] = {
    "brand": "",
    "series": "",
    "size_filter": "",
    "family_filter": "",
    "material_filter": "",
    "catalog": None,
    "inventory_ids": None,
    "disabled_ids": [],
    "board_width": 29,
    "board_height": 29,
    "pack_size": 1000,
    "keep_blank_cells": True,
    "empty_alpha_threshold": 0.5,
}

DISPLAY_NOTE = (
    "色卡来自公开数据源（HansBug/pindou-color-data、maxcleme/beadcolors，MIT）；"
    "RGB 为屏幕参考值，不等同品牌官方测量色，透明/夜光/荧光等材质已单独标记。"
)


def _catalog(params: dict[str, object]) -> list[BeadColor]:
    catalog = params.get("catalog")
    if catalog:
        return list(catalog)
    from Moge.core.beads.catalog import load_catalog

    loaded = load_catalog()
    return loaded or list(BEAD_CATALOG)


def build_config(spec: GridSpec, settings: dict[str, object]) -> PipelineConfig:
    resolved = dict(BEAD_DEFAULTS)
    resolved.update(settings or {})
    return PipelineConfig(
        mode=MODE_KEY,
        grid=spec,
        stages=("sample_grid", "map_beads", "render_preview", "build_stats"),
        sampling="mean",
        quantizer="bead",
        target_colors=0,
        seed=42,
        preset="material",
        params=resolved,
    )


def selectable_beads(settings: dict[str, object]) -> list[BeadColor]:
    from Moge.core.beads.catalog import preferred_selection

    catalog = _catalog(dict(settings))
    preferred_brand, preferred_series = preferred_selection(catalog)
    brand = str(settings.get("brand") or preferred_brand or (catalog[0].brand if catalog else ""))
    available = [item for item in catalog if item.brand == brand]
    default_series = preferred_series if brand == preferred_brand else (available[0].series if available else "")
    series = str(settings.get("series") or default_series)
    inventory = settings.get("inventory_ids")
    disabled = settings.get("disabled_ids") or []
    return filter_beads(
        catalog,
        brand=brand,
        series=series,
        inventory_ids=inventory if inventory else None,
        disabled_ids=disabled,
        size=str(settings.get("size_filter") or "") or None,
        color_family=str(settings.get("family_filter") or "") or None,
        material=str(settings.get("material_filter") or "") or None,
    )


@register_stage("map_beads")
def stage_map_beads(context: PipelineContext):
    if context.grid_rgb is None:
        raise ValueError("拼豆映射前必须完成网格采样")

    settings = context.config.params
    context.report(0.05, "正在筛选可用拼豆色号")
    candidates = selectable_beads(settings)
    if not candidates:
        raise ValueError("当前品牌/系列/库存/禁用条件下没有可用颜色")
    # 记录实际使用的品牌/系列，便于工程保存与恢复
    settings["brand"] = candidates[0].brand
    settings["series"] = candidates[0].series

    context.report(0.2, "正在匹配拼豆色号")
    palette_rgb = np.array([item.rgb for item in candidates], dtype=np.uint8)
    palette_lab = srgb_to_lab(palette_rgb)
    pixels = context.grid_rgb.reshape(-1, 3)
    height, width = context.config.grid.height, context.config.grid.width
    indices = nearest_lab_index(palette_lab, srgb_to_lab(pixels)).reshape(height, width)
    labels = apply_blank_mask(context, indices.astype(np.int32))
    context.labels = labels

    context.entries = [
        PaletteEntry(
            id=item.id,
            name=item.display_name,
            rgb=item.rgb,
            source=item.source,
            meta={
                "brand": item.brand,
                "series": item.series,
                "code": item.code,
                "availability": item.availability,
                "verified": item.verified,
                "revision": item.revision,
                "size": item.size,
                "color_family": item.color_family,
                "material": item.material,
                "trust": item.trust,
                "source_url": item.source_url,
                "license": item.license,
            },
        )
        for item in candidates
    ]
    symbols = build_symbols(context.entries)
    for entry in context.entries:
        entry.meta["symbol"] = symbols[entry.id]
        entry.meta["abbrev"] = abbrev_for(entry)
    context.materials = [
        MaterialRef(
            id=item.id,
            name=item.display_name,
            rgb=item.rgb,
            kind="bead",
            category=item.series,
            source=item.source,
            verified=item.verified,
            meta={
                "brand": item.brand,
                "series": item.series,
                "code": item.code,
                "size": item.size,
                "material": item.material,
                "trust": item.trust,
                "license": item.license,
                "symbol": symbols.get(item.id, ""),
            },
        )
        for item in candidates
    ]

    board_width = max(1, int(settings.get("board_width", 29)))
    board_height = max(1, int(settings.get("board_height", 29)))
    region_stats = board_stats(labels, board_width, board_height)

    flat_labels = labels.reshape(-1)
    valid_positions = np.nonzero(flat_labels >= 0)[0]
    if valid_positions.size:
        step = max(1, valid_positions.size // 5000)
        sample_positions = valid_positions[::step]
        deltas = delta_e_00(
            srgb_to_lab(pixels[sample_positions]),
            srgb_to_lab(palette_rgb[flat_labels[sample_positions]]),
        )
        mean_delta = float(np.mean(deltas))
        p95_delta = float(np.percentile(deltas, 95))
    else:
        mean_delta = 0.0
        p95_delta = 0.0

    summary = bead_summary(labels, context.entries)
    values, counts = (
        np.unique(flat_labels[flat_labels >= 0], return_counts=True)
        if valid_positions.size
        else (np.array([]), np.array([]))
    )
    used_ids = {context.entries[int(index)].id for index in values}
    pack_size = max(1, int(settings.get("pack_size", 1000)))
    packs_required = int(sum(int(np.ceil(count / pack_size)) for count in counts))

    trust_counts: dict[str, int] = {}
    material_counts: dict[str, int] = {}
    for item in candidates:
        trust_counts[item.trust] = trust_counts.get(item.trust, 0) + 1
        material_counts[item.material] = material_counts.get(item.material, 0) + 1
    licenses = sorted({item.license for item in candidates if item.license})
    bead_mm = parse_bead_mm(context.entries)
    pattern_mm = pattern_size_mm(width, height, bead_mm)

    context.stats.update(
        {
            "brand": candidates[0].brand if candidates else settings.get("brand"),
            "series": candidates[0].series if candidates else settings.get("series"),
            "size": candidates[0].size if candidates else "",
            "catalog_source": candidates[0].source if candidates else "",
            "catalog_license": " / ".join(licenses),
            "catalog_trust_counts": trust_counts,
            "catalog_material_counts": material_counts,
            "candidate_colors": len(candidates),
            "used_colors": len(used_ids),
            **summary,
            "board_size": f"{board_width}x{board_height}",
            "boards": len(region_stats),
            "board_stats": region_stats,
            "bead_mm": bead_mm,
            "pattern_width_mm": pattern_mm[0],
            "pattern_height_mm": pattern_mm[1],
            "legal_rate": 1.0,
            "mean_delta_e00": mean_delta,
            "p95_delta_e00": p95_delta,
            "verified_catalog": all(item.verified for item in candidates),
            "official_catalog": all(item.trust == "official" for item in candidates),
            "pack_size": pack_size,
            "packs_required": packs_required,
            "note": DISPLAY_NOTE,
        }
    )
    context.report(1.0, "拼豆色号映射完成")
