##############################
# core/modes/minecraft.py - Minecraft 方块画模式
##############################

from typing import Optional

import numpy as np

from Moge.core.color_spaces import delta_e_00, nearest_lab_index, srgb_to_lab
from Moge.core.materials import (
    MC_BLOCKS,
    MC_VERSIONS,
    MinecraftBlock,
    block_rejection_reason,
    filter_blocks,
)
from Moge.core.models import GridSpec, MaterialRef, PaletteEntry, PipelineConfig
from Moge.core.pipeline import PipelineContext, register_stage

MODE_KEY = "minecraft"
MODE_LABEL = "Minecraft 方块画"

MC_DEFAULTS: dict[str, object] = {
    "edition": "java",
    "version": "1.20.1",
    "categories": [],
    "obtainability": "any",
    "buildable_only": True,
    "max_cost_tier": None,
    "included_ids": [],
    "excluded_ids": [],
}

VERSION_OPTIONS = tuple((version, version) for version in MC_VERSIONS)
OBTAINABILITY_OPTIONS = (
    ("any", "不限制"),
    ("survival", "生存可获取"),
    ("renewable", "仅可再生"),
)
COST_OPTIONS = (
    (None, "不限制"),
    (1, "低成本优先"),
    (2, "中等成本上限"),
)

DISPLAY_NOTE = "内置色值为屏幕近似，未加载真实版本贴图；版本筛选仅基于内置元数据。"


def build_config(spec: GridSpec, settings: dict[str, object]) -> PipelineConfig:
    resolved = dict(MC_DEFAULTS)
    resolved.update(settings or {})
    return PipelineConfig(
        mode=MODE_KEY,
        grid=spec,
        stages=("sample_grid", "map_materials", "render_preview", "build_stats"),
        sampling="mean",
        quantizer="material",
        target_colors=0,
        seed=42,
        preset="material",
        params=resolved,
    )


def candidate_blocks(settings: dict[str, object]) -> list[MinecraftBlock]:
    version = str(settings.get("version", "1.20.1"))
    if version not in MC_VERSIONS:
        raise ValueError(f"未索引的 Minecraft 版本：{version}")
    max_cost = settings.get("max_cost_tier")
    return filter_blocks(
        version=version,
        edition=str(settings.get("edition", "java")),
        categories=settings.get("categories") or None,
        obtainability=str(settings.get("obtainability", "any")),
        buildable_only=bool(settings.get("buildable_only", True)),
        max_cost_tier=int(max_cost) if max_cost is not None else None,
        included_ids=settings.get("included_ids") or None,
        excluded_ids=settings.get("excluded_ids") or None,
    )


@register_stage("map_materials")
def stage_map_materials(context: PipelineContext):
    if context.grid_rgb is None:
        raise ValueError("材料映射前必须完成网格采样")

    settings = context.config.params
    context.report(0.05, "正在筛选合法方块")
    candidates = candidate_blocks(settings)
    if not candidates:
        version = settings.get("version")
        raise ValueError(f"Minecraft {version} 在当前筛选条件下没有可用方块")

    context.report(0.2, "正在匹配方块颜色")
    overrides = settings.get("texture_overrides") or {}

    def block_color(block: MinecraftBlock):
        value = overrides.get(block.block_id, block.rgb)
        return tuple(int(channel) for channel in value)

    palette_rgb = np.array([block_color(block) for block in candidates], dtype=np.uint8)
    palette_lab = srgb_to_lab(palette_rgb)
    pixels = context.grid_rgb.reshape(-1, 3)
    target_lab = srgb_to_lab(pixels)
    indices = nearest_lab_index(palette_lab, target_lab)

    context.labels = indices.reshape(context.config.grid.height, context.config.grid.width)
    context.entries = [
        PaletteEntry(
            id=block.block_id,
            name=block.name,
            rgb=block_color(block),
            source="user-resource-pack" if block.block_id in overrides else block.source,
            meta={
                "category": block.category,
                "obtainability": block.obtainability,
                "renewable": block.renewable,
                "cost_tier": block.cost_tier,
                "transparent": block.transparent,
                "texture": "user-average" if block.block_id in overrides else "approximate",
            },
        )
        for block in candidates
    ]
    context.materials = [
        MaterialRef(
            id=block.block_id,
            name=block.name,
            rgb=block_color(block),
            kind="minecraft",
            category=block.category,
            source="user-resource-pack" if block.block_id in overrides else block.source,
            verified=False,
            meta={"version": settings.get("version"), "edition": settings.get("edition")},
        )
        for block in candidates
    ]

    # 合法性反向核对：每个单元都必须属于候选集
    used_ids = {context.entries[int(index)].id for index in np.unique(indices)}
    legal = used_ids.issubset({block.block_id for block in candidates})
    if not legal:
        raise ValueError("结果中出现候选集之外的方块，已中止")

    step = max(1, len(pixels) // 5000)
    matched_rgb = palette_rgb[indices[::step]]
    deltas = delta_e_00(srgb_to_lab(pixels[::step]), srgb_to_lab(matched_rgb))

    context.stats.update(
        {
            "version": settings.get("version"),
            "edition": settings.get("edition"),
            "candidate_blocks": len(candidates),
            "block_types": len(used_ids),
            "legal_rate": 1.0,
            "mean_delta_e00": float(np.mean(deltas)),
            "p95_delta_e00": float(np.percentile(deltas, 95)),
            "texture_overrides": len(overrides),
            "note": DISPLAY_NOTE + (
                f" 已加载用户资源包贴图 {len(overrides)} 个（使用平均色）。" if overrides else ""
            ),
        }
    )
    context.diagnostics["matched_blocks"] = sorted(used_ids)
    context.report(1.0, "方块映射完成")


def rejection_diagnostics(settings: dict[str, object]) -> dict[str, Optional[str]]:
    """ 返回每个内置方块在当前筛选下的排除原因，便于 UI 展示 """
    version = str(settings.get("version", "1.20.1"))
    edition = str(settings.get("edition", "java"))
    categories = settings.get("categories") or None
    max_cost = settings.get("max_cost_tier")
    return {
        block.block_id: block_rejection_reason(
            block,
            version,
            edition,
            categories,
            str(settings.get("obtainability", "any")),
            bool(settings.get("buildable_only", True)),
            int(max_cost) if max_cost is not None else None,
        )
        for block in MC_BLOCKS
    }
