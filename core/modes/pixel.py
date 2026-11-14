##############################
# core/modes/pixel.py - 普通像素化模式
##############################

from typing import Optional

import cv2
import numpy as np

from Moge.core.models import GridSpec, PipelineConfig

MODE_KEY = "pixel"
MODE_LABEL = "普通像素化"

PIXEL_DEFAULTS: dict[str, object] = {
    "sampling": "mean",
    "algorithm": "kmeans_lab",
    "colors": 16,
    "seed": 42,
    "preset": "custom",
    "optimize": False,
    "max_delta": 6.0,
}

PRESET_OPTIONS = (
    ("custom", "自定义"),
    ("quick", "快速预览"),
    ("fidelity", "色彩保真"),
    ("smooth", "平整色块"),
    ("auto", "自动选择"),
)

SAMPLING_OPTIONS = (
    ("mean", "块均值"),
    ("mode", "块频数"),
    ("center", "最近像素"),
)


def _auto_preset(settings: dict[str, object], image_rgb: np.ndarray, spec: GridSpec) -> dict[str, object]:
    """ 基于网格规模、边缘密度与颜色复杂度的透明规则，不伪装为训练模型 """
    height, width = image_rgb.shape[:2]
    small = cv2.resize(
        image_rgb,
        (min(64, max(8, width)), min(64, max(8, height))),
        interpolation=cv2.INTER_AREA,
    )
    unique_ratio = len(np.unique(small.reshape(-1, 3), axis=0)) / float(small.shape[0] * small.shape[1])

    resolved = dict(settings)
    if spec.width * spec.height >= 65536:
        resolved.update(preset="quick", algorithm="minibatch_rgb", colors=min(int(settings.get("colors", 16)), 32))
        reason = "网格很大，选择 MiniBatch 以控制耗时"
    elif unique_ratio < 0.06:
        resolved.update(preset="fidelity", algorithm="kmeans_lab")
        reason = "颜色复杂度低，优先色差精度"
    else:
        resolved.update(preset="fidelity", algorithm="kmeans_lab")
        reason = "常规图像，采用 Lab K-Means 基线（边缘保护采样经基准未显示稳定收益）"
    resolved["auto_reason"] = reason
    return resolved


def resolve_settings(
    settings: dict[str, object],
    image_rgb: Optional[np.ndarray] = None,
    spec: Optional[GridSpec] = None,
) -> dict[str, object]:
    """ 展开效果预设为用户可检查的具体参数 """
    resolved = dict(PIXEL_DEFAULTS)
    resolved.update(settings or {})
    preset = str(resolved.get("preset", "custom"))

    if preset == "auto" and image_rgb is not None and spec is not None:
        resolved = _auto_preset(resolved, image_rgb, spec)
        preset = str(resolved.get("preset", "fidelity"))
        resolved["requested_preset"] = "auto"
    elif preset == "quick":
        resolved.update(algorithm="minibatch_rgb", colors=min(int(resolved.get("colors", 16)), 16))
    elif preset == "fidelity":
        resolved.update(algorithm="kmeans_lab")
    elif preset == "detail":
        resolved.update(algorithm="kmeans_lab", sampling="edge")
    elif preset == "smooth":
        resolved.update(algorithm="kmeans_lab", optimize=True)
    return resolved


def build_config(
    spec: GridSpec,
    settings: dict[str, object],
    image_rgb: Optional[np.ndarray] = None,
) -> PipelineConfig:
    resolved = resolve_settings(settings, image_rgb, spec)
    stages = ["sample_grid", "quantize_colors"]
    if bool(resolved.get("optimize", False)):
        stages.append("optimize_spatial")
    stages.extend(["render_preview", "build_stats"])

    return PipelineConfig(
        mode=MODE_KEY,
        grid=spec,
        stages=tuple(stages),
        sampling=str(resolved.get("sampling", "mean")),
        quantizer=str(resolved.get("algorithm", "kmeans_lab")),
        target_colors=max(1, int(resolved.get("colors", 16))),
        seed=int(resolved.get("seed", 42)),
        preset=str(resolved.get("preset", "custom")),
        params=dict(resolved),
    )
