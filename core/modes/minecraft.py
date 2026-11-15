##############################
# core/modes/minecraft.py - Minecraft 方块画模式
##############################

from typing import Optional

import cv2
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
    "matching_strategy": "perceptual",
    "texture_overrides": {},
    "texture_pack_name": "",
}

MATCHING_OPTIONS = (
    ("perceptual", "感知色差优先（默认）"),
    ("texture", "纹理一致性优先（实验）"),
    ("contour", "轮廓细节优先（实验）"),
    ("balanced", "均衡优化（实验）"),
)

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


def _grid_features(image_rgb: np.ndarray, spec: GridSpec) -> tuple[np.ndarray, np.ndarray]:
    """ 计算每个网格单元的边缘强度与亮度标准差，用于纹理/轮廓匹配 """
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(grad_x, grad_y)
    size = (spec.width, spec.height)
    mean = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
    mean_sq = cv2.resize(gray * gray, size, interpolation=cv2.INTER_AREA)
    std = np.sqrt(np.maximum(mean_sq - mean * mean, 0.0))
    edge = cv2.resize(magnitude, size, interpolation=cv2.INTER_AREA) / 255.0
    return std.reshape(-1), edge.reshape(-1)


def _match_indices(
    target_lab: np.ndarray,
    target_std: np.ndarray,
    target_edge: np.ndarray,
    palette_lab: np.ndarray,
    palette_lab_median: np.ndarray,
    block_complexity: np.ndarray,
    block_std: np.ndarray,
    patterned: np.ndarray,
    strategy: str,
    batch_size: int = 512,
) -> np.ndarray:
    """ 按策略计算匹配代价；perceptual 保持纯 CIEDE2000 """
    rows = len(target_lab)
    result = np.empty(rows, dtype=np.int32)
    for start in range(0, rows, batch_size):
        end = min(start + batch_size, rows)
        chunk = target_lab[start:end]
        delta_mean = delta_e_00(chunk[:, None, :], palette_lab[None, :, :])
        if strategy != "perceptual" and bool(patterned.any()):
            delta_median = delta_e_00(chunk[:, None, :], palette_lab_median[None, :, :])
            delta_color = np.where(
                patterned[None, :], np.minimum(delta_mean, delta_median + 1.0), delta_mean
            )
        else:
            delta_color = delta_mean
        edge = target_edge[start:end, None]
        std = target_std[start:end, None]
        complexity = block_complexity[None, :]
        std_diff = np.abs(std - block_std[None, :])
        if strategy == "perceptual":
            # 颜色优先；在 2.0 ΔE 容差内用纹理复杂度做平局裁决
            best = np.min(delta_color, axis=1, keepdims=True)
            allowed = delta_color <= best + 2.0
            cost = np.where(allowed, delta_color + 1.5 * np.abs(edge - complexity), delta_color)
        else:
            if strategy == "texture":
                cost = delta_color + 10.0 * np.abs(edge - complexity) + 0.06 * std_diff
            elif strategy == "contour":
                cost = (
                    delta_color
                    + 18.0 * edge * np.abs(edge - complexity)
                    + 4.0 * (1.0 - edge) * complexity
                )
            else:  # balanced
                cost = delta_color + 6.0 * np.abs(edge - complexity) + 0.04 * std_diff
        result[start:end] = np.argmin(cost, axis=1)
    return result


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
    palette_lab_median = srgb_to_lab(
        np.array([block.median_rgb if any(block.median_rgb) else block.rgb for block in candidates], dtype=np.uint8)
    )
    block_complexity = np.array([float(block.complexity) for block in candidates], dtype=np.float32)
    block_std = np.array([float(block.brightness_std) for block in candidates], dtype=np.float32)
    patterned = block_complexity > 0.08
    pixels = context.grid_rgb.reshape(-1, 3)
    target_lab = srgb_to_lab(pixels)
    target_std, target_edge = _grid_features(context.image_rgb, context.config.grid)

    strategy = str(settings.get("matching_strategy") or "perceptual")
    if strategy not in {key for key, _ in MATCHING_OPTIONS}:
        strategy = "perceptual"
    if strategy == "perceptual" and not bool(patterned.any()):
        indices = nearest_lab_index(palette_lab, target_lab)
    else:
        indices = _match_indices(
            target_lab,
            target_std,
            target_edge,
            palette_lab,
            palette_lab_median,
            block_complexity,
            block_std,
            patterned,
            strategy,
        )

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
                "complexity": block.complexity,
                "brightness_std": block.brightness_std,
                "median_rgb": block.median_rgb,
                "tinted": block.tinted,
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
    mean_delta = float(np.mean(deltas))
    p95_delta = float(np.percentile(deltas, 95))
    feature_error = float(np.mean(np.abs(target_edge - block_complexity[indices])))
    palette_limited = len(candidates) < 80
    quality_warning = mean_delta > 8.0 or p95_delta > 15.0
    if quality_warning:
        quality_message = (
            f"材料集仅 {len(candidates)} 种，平均 ΔE00 {mean_delta:.1f}、P95 {p95_delta:.1f}，"
            "存在明显色差；建议放宽筛选或加入更多方块。"
        )
    else:
        quality_message = f"匹配质量可接受：平均 ΔE00 {mean_delta:.1f}、P95 {p95_delta:.1f}。"
    tinted_count = sum(1 for block in candidates if block.tinted)
    transparent_count = sum(1 for block in candidates if block.transparent)
    limitations = []
    if tinted_count:
        limitations.append(f"{tinted_count} 个方块使用生物群系染色贴图，预览显示灰度底，未应用 tint")
    if transparent_count:
        limitations.append(f"{transparent_count} 个半透明方块按不透明平均值参与匹配")
    if palette_limited:
        limitations.append(f"当前仅 {len(candidates)} 个候选材料，颜色空间覆盖有限")

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
            "mean_delta_e00": mean_delta,
            "p95_delta_e00": p95_delta,
            "matching_strategy": strategy,
            "texture_feature_error": feature_error,
            "quality_warning": quality_warning,
            "quality_message": quality_message,
            "palette_limited": palette_limited,
            "render_limitations": limitations,
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
