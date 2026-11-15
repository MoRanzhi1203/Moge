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
    "orientation": "any",
    "exclude_transparent": False,
    "exclude_gravity": False,
    "resource_mode": "auto",
    "texture_overrides": {},
    "texture_pack_name": "",
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


_REAL_CATALOG_CACHE: dict = {}


def _real_catalog(edition: str, version: str) -> tuple[list, dict]:
    """ 尝试从本地资源库加载真实方块与覆盖率；按数据库更新时间缓存 """
    try:
        from Moge.core.resources.paths import database_path

        database = database_path()
        if not database.exists():
            return [], {}
        stat = database.stat()
        key = (str(database), edition, version, stat.st_mtime_ns, stat.st_size)
        cached = _REAL_CATALOG_CACHE.get(key)
        if cached is not None:
            return cached

        from Moge.core.resources.manager import ResourceManager

        with ResourceManager() as manager:
            blocks = manager.build_catalog(edition, version)
            coverage = manager.coverage(edition, version)
        payload = (blocks, coverage)
        if len(_REAL_CATALOG_CACHE) >= 4:
            _REAL_CATALOG_CACHE.clear()
        _REAL_CATALOG_CACHE[key] = payload
        return payload
    except Exception:
        return [], {}


def candidate_blocks(settings: dict[str, object]) -> list[MinecraftBlock]:
    version = str(settings.get("version", "1.20.1"))
    edition = str(settings.get("edition", "java"))
    if version not in MC_VERSIONS and edition == "java":
        # 动态扩展的 Java 版本允许由官方清单提供
        manifest_versions = set()
        try:
            from Moge.core.resources.java import list_versions, load_manifest

            manifest_versions = {item["id"] for item in list_versions(load_manifest(), release_only=False)}
        except Exception:
            manifest_versions = set()
        if version not in manifest_versions:
            raise ValueError(f"未索引的 Minecraft 版本：{version}")
    max_cost = settings.get("max_cost_tier")
    resource_mode = str(settings.get("resource_mode", "auto"))
    buildable_only = bool(settings.get("buildable_only", True))
    base_blocks = None
    has_geometry = False
    if resource_mode in ("auto", "real"):
        real, _coverage = _real_catalog(edition, version)
        if real:
            base_blocks = real
            has_geometry = any(block.geometry == "full_cube" for block in real)
        elif resource_mode == "real":
            raise ValueError(f"{edition} {version} 的真实资源尚未下载，请在“版本资源管理”中获取")
    # 仅在确有模型几何数据时启用完整立方体硬性筛选
    if base_blocks is not None and has_geometry and buildable_only:
        geometry_rule: Optional[bool] = True
    elif base_blocks is not None and not buildable_only:
        geometry_rule = False
    else:
        geometry_rule = None
    return filter_blocks(
        version=version,
        edition=edition,
        categories=settings.get("categories") or None,
        obtainability=str(settings.get("obtainability", "any")),
        buildable_only=buildable_only,
        max_cost_tier=int(max_cost) if max_cost is not None else None,
        included_ids=settings.get("included_ids") or None,
        excluded_ids=settings.get("excluded_ids") or None,
        orientation=str(settings.get("orientation", "any")),
        exclude_transparent=bool(settings.get("exclude_transparent", False)),
        exclude_gravity=bool(settings.get("exclude_gravity", False)),
        blocks=base_blocks,
        require_full_cube=geometry_rule,
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
    edition = str(settings.get("edition", "java"))
    version = str(settings.get("version", "1.20.1"))
    real_candidates = [block for block in candidates if block.source == "mojang-resource"]
    coverage = _real_catalog(edition, version)[1] if real_candidates else {}

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
                "gravity": block.gravity,
                "orientation": block.orientation,
                "visible_face": block.visible_face,
                "geometry": block.geometry,
                "block_state": block.block_state,
                "texture_sha256": block.texture_sha256,
                "texture_path": block.texture_path,
                "verified": block.verified,
                "texture": (
                    "real" if block.source == "mojang-resource" and block.texture_path
                    else ("user-average" if block.block_id in overrides else "approximate")
                ),
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
            verified=block.verified,
            meta={
                "version": version,
                "edition": edition,
                "block_state": block.block_state,
                "geometry": block.geometry,
                "texture_sha256": block.texture_sha256,
                "texture_path": block.texture_path,
            },
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

    has_real = bool(real_candidates)
    renderable = sum(1 for block in candidates if block.texture_path and block.verified)
    pack_hits = sum(1 for block in candidates if block.block_id in overrides)
    vanilla_numerator = int(coverage.get("textured_blocks", 0)) if has_real else 0
    vanilla_denominator = int(coverage.get("total_blocks", 0)) if has_real else 0
    vanilla_coverage = {
        "numerator": vanilla_numerator,
        "denominator": vanilla_denominator,
        "ratio": (vanilla_numerator / vanilla_denominator) if vanilla_denominator else 0.0,
        "label": "原版资源覆盖率",
    }
    renderable_coverage = {
        "numerator": renderable,
        "denominator": len(candidates),
        "ratio": (renderable / len(candidates)) if candidates else 0.0,
        "label": "可渲染候选覆盖率",
    }
    pack_coverage = {
        "numerator": pack_hits,
        "denominator": len(candidates),
        "ratio": (pack_hits / len(candidates)) if candidates else 0.0,
        "label": "附加资源包覆盖率",
    }

    context.stats.update(
        {
            "version": version,
            "edition": edition,
            "candidate_blocks": len(candidates),
            "block_types": len(used_ids),
            "legal_rate": 1.0,
            "mean_delta_e00": float(np.mean(deltas)),
            "p95_delta_e00": float(np.percentile(deltas, 95)),
            "texture_overrides": len(overrides),
            "texture_pack": settings.get("texture_pack_name") or "",
            "resource_source": "mojang-resource" if has_real else "builtin-approx",
            "vanilla_coverage": vanilla_coverage,
            "renderable_coverage": renderable_coverage,
            "pack_coverage": pack_coverage,
            "full_cube_blocks": int(coverage.get("full_cube_blocks", 0)),
            "verified_blocks": int(coverage.get("verified_blocks", 0)),
            "geometry_known": bool(coverage.get("full_cube_blocks", 0)),
            "note": (
                f"使用 Mojang 官方 {edition} {version} 资源解析的真实贴图；"
                f"原版覆盖 {vanilla_numerator}/{vanilla_denominator}，"
                f"候选贴图 {renderable}/{len(candidates)}。获取条件仍来自近似元数据，未逐一验证。"
                if has_real
                else DISPLAY_NOTE
            ) + (
                f" 已加载用户资源包 {settings.get('texture_pack_name') or ''} 的 {len(overrides)} 个贴图（平均色）。"
                if overrides
                else ""
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
            str(settings.get("orientation", "any")),
            bool(settings.get("exclude_transparent", False)),
            bool(settings.get("exclude_gravity", False)),
        )
        for block in MC_BLOCKS
    }
