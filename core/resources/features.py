##############################
# core/resources/features.py - 贴图颜色与复杂度特征
##############################


import cv2
import numpy as np

from Moge.core.color_spaces import srgb_to_lab


def analyze_texture_bytes(data: bytes) -> dict[str, object]:
    """ 解析 PNG/JPEG 字节并计算颜色、透明度和复杂度特征 """
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError("无法解析贴图")
    return analyze_texture_array(image)


def analyze_texture_array(image: np.ndarray) -> dict[str, object]:
    array = np.asarray(image)
    if array.ndim == 2:
        bgr = cv2.cvtColor(array, cv2.COLOR_GRAY2BGR)
        alpha = None
    elif array.shape[2] == 4:
        bgr = array[..., :3]
        alpha = array[..., 3]
    else:
        bgr = array[..., :3]
        alpha = None

    height, width = bgr.shape[:2]
    pixels_bgr = bgr.reshape(-1, 3)
    if alpha is not None:
        visible = alpha.reshape(-1) > 0
        pixels_bgr = pixels_bgr[visible]

    if pixels_bgr.size == 0:
        pixels_bgr = np.zeros((1, 3), np.uint8)
    pixels_rgb = pixels_bgr[:, ::-1].astype(np.uint8)
    mean_rgb = pixels_rgb.mean(axis=0)
    median_rgb = np.median(pixels_rgb, axis=0)
    lab = srgb_to_lab(np.array([mean_rgb], dtype=np.uint8))[0]

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    complexity = float(np.mean(cv2.magnitude(grad_x, grad_y)) / 255.0)
    brightness_std = float(np.std(gray))
    unique_ratio = len(np.unique(pixels_rgb, axis=0)) / max(1, len(pixels_rgb))

    return {
        "width": int(width),
        "height": int(height),
        "has_alpha": int(alpha is not None),
        "alpha_mean": float(alpha.mean()) if alpha is not None else 255.0,
        "mean_rgb": tuple(int(round(value)) for value in mean_rgb),
        "median_rgb": tuple(int(round(value)) for value in median_rgb),
        "lab": tuple(float(value) for value in lab),
        "complexity": complexity,
        "brightness_std": brightness_std,
        "unique_ratio": float(unique_ratio),
    }
