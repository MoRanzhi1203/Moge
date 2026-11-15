##############################
# core/benchmarks.py - 可复现基准数据、指标与算法对照
##############################

import platform
import sys
import tracemalloc
from collections import OrderedDict
from collections.abc import Sequence
from typing import Callable, Optional

import cv2
import numpy as np

from Moge.core.clustering import ALGORITHM_INFO, EXPERIMENTAL_ALGORITHMS, quantize
from Moge.core.color_spaces import delta_e_00, nearest_lab_index, srgb_to_lab
from Moge.core.grid import ensure_rgb, isolated_cells, render_grid, sample_grid
from Moge.core.materials import BEAD_CATALOG, filter_beads, filter_blocks
from Moge.core.models import GridSpec, PipelineConfig
from Moge.core.pipeline import run_pipeline


def _canvas(size: int = 128) -> np.ndarray:
    return np.full((size, size, 3), 235, dtype=np.uint8)


def make_benchmark_images(size: int = 128) -> "OrderedDict[str, np.ndarray]":
    """ 生成可合法存储、可复现的合成基准图，不包含第三方素材 """
    images: OrderedDict[str, np.ndarray] = OrderedDict()

    # 人像：渐变背景 + 脸部椭圆 + 五官
    portrait = _canvas(size)
    gradient = np.linspace(30, 120, size, dtype=np.float32)
    portrait[..., 0] = gradient[:, None]
    portrait[..., 1] = gradient[None, :]
    portrait[..., 2] = 100
    cv2.ellipse(portrait, (size // 2, size // 2), (size // 4, size // 3), 0, 0, 360, (224, 180, 150), -1)
    cv2.circle(portrait, (size // 2 - 16, size // 2 - 10), 5, (30, 30, 30), -1)
    cv2.circle(portrait, (size // 2 + 16, size // 2 - 10), 5, (30, 30, 30), -1)
    cv2.ellipse(portrait, (size // 2, size // 2 + 24), (14, 7), 0, 0, 180, (150, 40, 40), -1)
    images["portrait"] = portrait

    # 噪声
    images["noise"] = np.random.default_rng(11).integers(0, 256, (size, size, 3), dtype=np.uint8)

    # 卡通：大色块 + 圆
    cartoon = _canvas(size)
    cartoon[: size // 2, :] = (70, 150, 220)
    cartoon[size // 2 :, :] = (80, 180, 90)
    cv2.circle(cartoon, (size // 3, size // 3), size // 6, (250, 210, 60), -1)
    cv2.rectangle(cartoon, (size // 2, size // 2), (size - 10, size - 10), (220, 80, 120), -1)
    images["cartoon"] = cartoon

    # 低对比
    low = np.zeros((size, size, 3), np.uint8)
    for channel in range(3):
        low[..., channel] = np.linspace(100 + channel * 8, 140 + channel * 8, size, dtype=np.uint8)[:, None]
    images["low_contrast"] = low

    # 渐变
    gradient_image = np.zeros((size, size, 3), np.uint8)
    gradient_image[..., 0] = np.linspace(0, 255, size, dtype=np.uint8)[None, :]
    gradient_image[..., 1] = np.linspace(0, 255, size, dtype=np.uint8)[:, None]
    gradient_image[..., 2] = 128
    images["gradient"] = gradient_image

    # 文字/线条
    text = _canvas(size)
    for row in range(10, size - 10, 22):
        cv2.rectangle(text, (18, row), (size - 18 - (row % 30), row + 8), (20, 20, 20), -1)
    images["text"] = text

    # 透明区域
    transparent = np.zeros((size, size, 4), np.uint8)
    transparent[..., :3] = 180
    transparent[..., 3] = 255
    cv2.circle(transparent, (size // 2, size // 2), size // 3, (255, 0, 0, 0), -1)
    images["transparent"] = transparent

    return images


def _gradient(gray: np.ndarray) -> np.ndarray:
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(grad_x, grad_y)


def edge_correlation(reference_rgb: np.ndarray, output_rgb: np.ndarray) -> float:
    """ 结构保持代理指标：两幅网格图的梯度幅值相关系数 """
    reference = cv2.cvtColor(reference_rgb, cv2.COLOR_RGB2GRAY)
    output = cv2.cvtColor(output_rgb, cv2.COLOR_RGB2GRAY)
    grad_ref = _gradient(reference)
    grad_out = _gradient(output)
    if grad_ref.std() < 1e-6 and grad_out.std() < 1e-6:
        return 1.0
    if grad_ref.std() < 1e-6 or grad_out.std() < 1e-6:
        return 0.0
    return float(np.corrcoef(grad_ref.ravel(), grad_out.ravel())[0, 1])


def evaluate_result(source_rgb: np.ndarray, result) -> dict[str, float]:
    """ 在统一目标网格上比较源图与结果的色差、结构与碎片 """
    spec = result.grid.spec
    target = sample_grid(source_rgb, spec, "mean")
    output = render_grid(result.grid.labels, result.grid.entries)
    labels = result.grid.labels.reshape(-1)
    valid = labels >= 0

    reference_lab = srgb_to_lab(target.reshape(-1, 3))[valid]
    output_lab = srgb_to_lab(output.reshape(-1, 3))[valid]
    deltas = delta_e_00(reference_lab, output_lab) if len(reference_lab) else np.array([0.0])

    return {
        "mean_delta_e00": float(np.mean(deltas)),
        "p95_delta_e00": float(np.percentile(deltas, 95)),
        "edge_correlation": edge_correlation(target, output),
        "isolated_cells": int(isolated_cells(result.grid.labels)),
        "elapsed_ms": float(result.elapsed_ms),
        "actual_colors": float(len(result.grid.entries)),
    }


def _pixel_config(spec: GridSpec, algorithm: str, colors: int, sampling: str = "mean", optimize: bool = False) -> PipelineConfig:
    stages = ["sample_grid", "quantize_colors"]
    if optimize:
        stages.append("optimize_spatial")
    stages.extend(["render_preview", "build_stats"])
    return PipelineConfig(
        mode="pixel",
        grid=spec,
        stages=tuple(stages),
        sampling=sampling,
        quantizer=algorithm,
        target_colors=colors,
        seed=42,
        params={"optimize": optimize, "max_delta": 6.0},
    )


def run_clustering_suite(
    images: Optional[dict[str, np.ndarray]] = None,
    grid_sizes: Sequence[int] = (32, 64, 128),
    color_counts: Sequence[int] = (8, 16, 32, 64),
    algorithms: Sequence[str] = tuple(
        key for key in ALGORITHM_INFO if key not in EXPERIMENTAL_ALGORITHMS
    ),
    progress: Optional[Callable[[int, int], None]] = None,
) -> list[dict[str, object]]:
    """ 统一输入、种子与网格下的算法对照 """
    images = images or make_benchmark_images()
    records: list[dict[str, object]] = []
    total = len(images) * len(grid_sizes) * len(color_counts) * len(algorithms)
    index = 0
    for image_name, image in images.items():
        source_rgb, _ = ensure_rgb(image)
        for grid_size in grid_sizes:
            spec = GridSpec(grid_size, grid_size)
            for colors in color_counts:
                for algorithm in algorithms:
                    tracemalloc.start()
                    result = run_pipeline(source_rgb, _pixel_config(spec, algorithm, colors))
                    peak = tracemalloc.get_traced_memory()[1]
                    tracemalloc.stop()
                    metrics = evaluate_result(source_rgb, result)
                    records.append(
                        {
                            "image": image_name,
                            "grid": grid_size,
                            "target_colors": colors,
                            "algorithm": algorithm,
                            "peak_kb": peak / 1024.0,
                            **metrics,
                        }
                    )
                    index += 1
                    if progress:
                        progress(index, total)
    return records


def run_spectral_experiment(
    images: Optional[dict[str, np.ndarray]] = None,
    grid_size: int = 32,
    color_counts: Sequence[int] = (8, 16, 32, 64),
) -> list[dict[str, object]]:
    """ 仅在 ≤1024 个网格区域上对比谱聚类与 K-Means，不进入正式 UI """
    images = images or make_benchmark_images()
    records: list[dict[str, object]] = []
    for image_name, image in images.items():
        source_rgb, _ = ensure_rgb(image)
        spec = GridSpec(grid_size, grid_size)
        for colors in color_counts:
            for algorithm in ("kmeans_lab", "spectral_lab"):
                tracemalloc.start()
                result = run_pipeline(source_rgb, _pixel_config(spec, algorithm, colors))
                peak = tracemalloc.get_traced_memory()[1]
                tracemalloc.stop()
                records.append(
                    {
                        "image": image_name,
                        "grid": grid_size,
                        "target_colors": colors,
                        "algorithm": algorithm,
                        "peak_kb": peak / 1024.0,
                        "fallback": int(result.diagnostics.get("spectral_fallback", 0)),
                        **evaluate_result(source_rgb, result),
                    }
                )
    return records


def summarize(records: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    groups: OrderedDict[tuple, list[dict[str, object]]] = OrderedDict()
    for record in records:
        groups.setdefault((record["algorithm"], record["grid"], record["target_colors"]), []).append(record)

    summary = []
    for (algorithm, grid, colors), items in groups.items():
        summary.append(
            {
                "algorithm": algorithm,
                "grid": grid,
                "target_colors": colors,
                "runs": len(items),
                "mean_delta_e00": float(np.mean([item["mean_delta_e00"] for item in items])),
                "p95_delta_e00": float(np.mean([item["p95_delta_e00"] for item in items])),
                "edge_correlation": float(np.mean([item["edge_correlation"] for item in items])),
                "isolated_cells": float(np.mean([item["isolated_cells"] for item in items])),
                "elapsed_ms": float(np.mean([item["elapsed_ms"] for item in items])),
                "peak_kb": float(np.mean([item["peak_kb"] for item in items])),
            }
        )
    return summary


def aggregate_by_algorithm(records: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    groups: OrderedDict[str, list[dict[str, object]]] = OrderedDict()
    for record in records:
        groups.setdefault(record["algorithm"], []).append(record)
    return [
        {
            "algorithm": algorithm,
            "runs": len(items),
            "mean_delta_e00": float(np.mean([item["mean_delta_e00"] for item in items])),
            "p95_delta_e00": float(np.mean([item["p95_delta_e00"] for item in items])),
            "edge_correlation": float(np.mean([item["edge_correlation"] for item in items])),
            "isolated_cells": float(np.mean([item["isolated_cells"] for item in items])),
            "elapsed_ms": float(np.mean([item["elapsed_ms"] for item in items])),
            "peak_kb": float(np.mean([item["peak_kb"] for item in items])),
        }
        for algorithm, items in groups.items()
    ]


def run_preset_suite(
    images: Optional[dict[str, np.ndarray]] = None,
    grid_size: int = 48,
) -> list[dict[str, object]]:
    """ 对照效果预设：快速 / 保真 / 细节 / 平整 """
    from Moge.core.modes import pixel

    images = images or make_benchmark_images()
    variants = OrderedDict(
        [
            ("baseline", {"sampling": "mean", "algorithm": "kmeans_lab", "colors": 16, "preset": "custom", "optimize": False}),
            ("quick", {"preset": "quick", "colors": 16}),
            ("fidelity", {"preset": "fidelity", "colors": 16}),
            ("detail", {"preset": "detail", "colors": 16}),
            ("smooth", {"preset": "smooth", "colors": 16, "optimize": True}),
        ]
    )
    records = []
    for image_name, image in images.items():
        source_rgb, _ = ensure_rgb(image)
        spec = GridSpec(grid_size, grid_size)
        for preset_name, settings in variants.items():
            merged = dict(pixel.PIXEL_DEFAULTS)
            merged.update(settings)
            config = pixel.build_config(spec, merged, source_rgb)
            result = run_pipeline(source_rgb, config)
            records.append({"image": image_name, "preset": preset_name, **evaluate_result(source_rgb, result)})
    return records


def _match_rgb(source_rgb: np.ndarray, palette_rgb: np.ndarray) -> np.ndarray:
    labels = nearest_lab_index(srgb_to_lab(palette_rgb), srgb_to_lab(source_rgb.reshape(-1, 3)))
    return palette_rgb[labels].reshape(source_rgb.shape)


def run_material_comparison(
    images: Optional[dict[str, np.ndarray]] = None,
    grid_size: int = 32,
) -> list[dict[str, object]]:
    """ 直接合法材料匹配 vs 先 K-Means 再映射 """
    images = images or make_benchmark_images()
    blocks = filter_blocks("1.20.1")
    block_rgb = np.array([block.rgb for block in blocks], dtype=np.uint8)
    bead_rgb = np.array([item.rgb for item in filter_beads(BEAD_CATALOG, "Generic", "Approx")], dtype=np.uint8)

    records = []
    for image_name, image in images.items():
        source_rgb, _ = ensure_rgb(image)
        spec = GridSpec(grid_size, grid_size)
        sampled = sample_grid(source_rgb, spec, "mean")
        target_lab = srgb_to_lab(sampled.reshape(-1, 3))

        for family, palette_rgb in (("minecraft", block_rgb), ("beads", bead_rgb)):
            direct_rgb = _match_rgb(sampled, palette_rgb)
            direct_lab = srgb_to_lab(direct_rgb.reshape(-1, 3))
            direct_delta = float(np.mean(delta_e_00(target_lab, direct_lab)))

            quantized = quantize(sampled.reshape(-1, 3), 16, "kmeans_lab", 42)
            quantized_rgb = quantized.centers_rgb[quantized.labels].reshape(sampled.shape)
            mapped_rgb = _match_rgb(quantized_rgb, palette_rgb)
            mapped_delta = float(np.mean(delta_e_00(target_lab, srgb_to_lab(mapped_rgb.reshape(-1, 3)))))

            records.append(
                {
                    "image": image_name,
                    "family": family,
                    "direct_delta_e00": direct_delta,
                    "kmeans_delta_e00": mapped_delta,
                    "direct_colors": int(len(np.unique(direct_rgb.reshape(-1, 3), axis=0))),
                    "legal_rate": 1.0,
                }
            )
    return records


def environment_info() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": np.__version__,
        "opencv": cv2.__version__,
    }
