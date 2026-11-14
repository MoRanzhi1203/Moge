##############################
# core/pipeline.py - 注册式图像处理管线
##############################

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from Moge.core.grid import ensure_rgb, isolated_cells, render_grid, sample_grid
from Moge.core.image_processor import ProcessingCancelled
from Moge.core.models import (
    GridSpec,
    MaterialRef,
    PaletteEntry,
    PipelineConfig,
    PixelGrid,
    RenderResult,
)

STAGES: dict[str, Callable[["PipelineContext"], None]] = {}


def register_stage(name: str):
    """ 注册一个处理阶段 """

    def decorator(function):
        STAGES[name] = function
        return function

    return decorator


@dataclass
class PipelineContext:
    """ 阶段之间共享的上下文 """

    image_rgb: np.ndarray
    config: PipelineConfig
    image_diagnostics: dict[str, int] = field(default_factory=dict)
    grid_rgb: Optional[np.ndarray] = None
    labels: Optional[np.ndarray] = None
    entries: list[PaletteEntry] = field(default_factory=list)
    materials: list[MaterialRef] = field(default_factory=list)
    preview: Optional[np.ndarray] = None
    stats: dict[str, object] = field(default_factory=dict)
    diagnostics: dict[str, object] = field(default_factory=dict)
    progress_callback: Optional[Callable[[int, str], None]] = None
    cancel_callback: Optional[Callable[[], bool]] = None
    stage_start: float = 0.0
    stage_end: float = 100.0

    def check_cancel(self):
        if self.cancel_callback is not None and self.cancel_callback():
            raise ProcessingCancelled()

    def report(self, ratio: float, message: str):
        if self.progress_callback is None:
            return
        ratio = min(max(ratio, 0.0), 1.0)
        value = int(self.stage_start + (self.stage_end - self.stage_start) * ratio)
        self.progress_callback(value, message)


def _ensure_modes_loaded():
    """ 惰性导入模式模块以完成阶段注册，避免循环依赖 """
    import Moge.core.modes.beads  # noqa: F401
    import Moge.core.modes.minecraft  # noqa: F401
    import Moge.core.modes.pixel  # noqa: F401


@register_stage("sample_grid")
def stage_sample_grid(context: PipelineContext):
    context.report(0.0, "正在采样网格")
    context.grid_rgb = sample_grid(context.image_rgb, context.config.grid, context.config.sampling)
    context.report(1.0, "网格采样完成")


@register_stage("quantize_colors")
def stage_quantize_colors(context: PipelineContext):
    from Moge.core.clustering import quantize

    if context.grid_rgb is None:
        raise ValueError("量化前必须完成网格采样")

    context.report(0.0, "正在量化颜色")
    pixels = context.grid_rgb.reshape(-1, 3)
    output = quantize(
        pixels,
        context.config.target_colors,
        context.config.quantizer,
        context.config.seed,
        should_cancel=context.cancel_callback,
    )
    context.check_cancel()

    context.entries = [
        PaletteEntry(
            id=f"gen-{index:04d}",
            name=f"颜色 {index + 1}",
            rgb=tuple(int(channel) for channel in color),
            source="generated",
        )
        for index, color in enumerate(output.centers_rgb)
    ]
    context.labels = output.labels.reshape(context.config.grid.height, context.config.grid.width)
    context.diagnostics.update(output.diagnostics)
    context.report(1.0, "颜色量化完成")


@register_stage("optimize_spatial")
def stage_optimize_spatial(context: PipelineContext):
    from Moge.core.optimization import reduce_isolated

    if context.labels is None:
        raise ValueError("优化前必须完成颜色/材料映射")

    context.report(0.0, "正在清理孤立色块")
    before = isolated_cells(context.labels)
    max_delta = float(context.config.params.get("max_delta", 6.0))
    iterations = int(context.config.params.get("optimize_iterations", 1))
    labels, changed = reduce_isolated(
        context.labels,
        context.entries,
        max_delta=max_delta,
        iterations=iterations,
        should_cancel=context.cancel_callback,
    )
    context.labels = labels
    context.diagnostics["isolated_before"] = before
    context.diagnostics["isolated_after"] = isolated_cells(labels)
    context.diagnostics["optimized_cells"] = changed
    context.report(1.0, "孤立色块清理完成")


@register_stage("render_preview")
def stage_render_preview(context: PipelineContext):
    if context.labels is None or not context.entries:
        raise ValueError("渲染前必须完成颜色/材料映射")

    context.report(0.0, "正在渲染预览")
    transparent = context.config.mode == "pixel"
    context.preview = render_grid(context.labels, context.entries, transparent=transparent)
    context.report(1.0, "预览渲染完成")


@register_stage("build_stats")
def stage_build_stats(context: PipelineContext):
    if context.labels is None:
        raise ValueError("统计前必须完成映射")

    flat = context.labels.reshape(-1)
    valid = flat[flat >= 0]
    values, counts = np.unique(valid, return_counts=True) if valid.size else (np.array([]), np.array([]))
    by_id = {
        context.entries[int(value)].id: int(count)
        for value, count in zip(values, counts)
    }
    context.stats.update(
        {
            "total_cells": int(flat.size),
            "filled_cells": int(valid.size),
            "empty_cells": int(flat.size - valid.size),
            "used_entries": int(len(values)),
            "counts": by_id,
            "isolated_cells": isolated_cells(context.labels),
            "palette_size": len(context.entries),
        }
    )
    context.report(1.0, "统计完成")


def run_pipeline(
    image: np.ndarray,
    config: PipelineConfig,
    progress: Optional[Callable[[int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> RenderResult:
    """ 按注册阶段顺序执行完整处理链 """
    _ensure_modes_loaded()

    image_rgb, image_diagnostics = ensure_rgb(image)
    context = PipelineContext(
        image_rgb=image_rgb,
        config=config,
        image_diagnostics=image_diagnostics,
        progress_callback=progress,
        cancel_callback=should_cancel,
    )

    stages = list(config.stages)
    if not stages:
        raise ValueError("管线至少需要一个阶段")
    for name in stages:
        if name not in STAGES:
            raise ValueError(f"未注册的处理阶段：{name}")

    started = time.perf_counter()
    total = len(stages)
    for index, name in enumerate(stages):
        context.stage_start = index * 100.0 / total
        context.stage_end = (index + 1) * 100.0 / total
        context.check_cancel()
        STAGES[name](context)
        context.check_cancel()

    if context.labels is None or context.preview is None:
        raise ValueError("管线未产出有效结果")

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    grid = PixelGrid(
        spec=config.grid,
        labels=np.asarray(context.labels, dtype=np.int32),
        entries=list(context.entries),
        mode=config.mode,
        materials=list(context.materials),
    )
    if not grid.validate():
        raise ValueError("处理结果网格不合法")

    stats = dict(context.stats)
    stats["algorithm"] = config.quantizer
    stats["mode"] = config.mode
    stats["elapsed_ms"] = round(elapsed_ms, 2)
    stats.update(context.image_diagnostics)

    settings = {
        "sampling": config.sampling,
        "quantizer": config.quantizer,
        "target_colors": config.target_colors,
        "seed": config.seed,
        "preset": config.preset,
        "params": dict(config.params),
    }
    return RenderResult(
        image=context.preview,
        grid=grid,
        stats=stats,
        algorithm=config.quantizer,
        mode=config.mode,
        elapsed_ms=elapsed_ms,
        diagnostics=dict(context.diagnostics),
        source_size=(image_rgb.shape[1], image_rgb.shape[0]),
        settings=settings,
    )


def available_stages() -> list[str]:
    return sorted(STAGES.keys())


def build_grid_spec(width: int, height: int) -> GridSpec:
    return GridSpec(width=int(width), height=int(height))
