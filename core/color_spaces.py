##############################
# core/color_spaces.py - 色彩空间与感知色差
##############################

import numpy as np

# sRGB (D65) -> XYZ 转换矩阵
_RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)
_XYZ_TO_RGB = np.linalg.inv(_RGB_TO_XYZ)
_WHITE_D65 = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)
_EPSILON = 216.0 / 24389.0
_KAPPA = 24389.0 / 27.0


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """ sRGB(0~255) 转 CIE Lab(D65)，支持 (3,) 或 (N,3) """
    values = np.asarray(rgb, dtype=np.float64)
    single = values.ndim == 1
    channels = values.reshape(-1, 3) / 255.0

    linear = np.where(
        channels <= 0.04045,
        channels / 12.92,
        ((channels + 0.055) / 1.055) ** 2.4,
    )
    xyz = (linear @ _RGB_TO_XYZ.T) / _WHITE_D65
    f = np.where(xyz > _EPSILON, np.cbrt(xyz), (_KAPPA * xyz + 16.0) / 116.0)

    lab = np.stack(
        [
            116.0 * f[:, 1] - 16.0,
            500.0 * (f[:, 0] - f[:, 1]),
            200.0 * (f[:, 1] - f[:, 2]),
        ],
        axis=1,
    )
    return lab[0] if single else lab


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """ CIE Lab(D65) 转 sRGB(0~255)，返回 uint8 """
    values = np.asarray(lab, dtype=np.float64)
    single = values.ndim == 1
    channels = values.reshape(-1, 3)

    fy = (channels[:, 0] + 16.0) / 116.0
    fx = fy + channels[:, 1] / 500.0
    fz = fy - channels[:, 2] / 200.0

    xyz = np.stack(
        [
            np.where(fx ** 3 > _EPSILON, fx ** 3, (116.0 * fx - 16.0) / _KAPPA),
            np.where(channels[:, 0] > _KAPPA * _EPSILON, fy ** 3, channels[:, 0] / _KAPPA),
            np.where(fz ** 3 > _EPSILON, fz ** 3, (116.0 * fz - 16.0) / _KAPPA),
        ],
        axis=1,
    ) * _WHITE_D65

    linear = xyz @ _XYZ_TO_RGB.T
    srgb = np.where(
        linear <= 0.0031308,
        12.92 * linear,
        1.055 * np.maximum(linear, 0.0) ** (1.0 / 2.4) - 0.055,
    )
    result = np.clip(np.rint(srgb * 255.0), 0, 255).astype(np.uint8)
    return result[0] if single else result


def delta_e_76(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """ CIE76 色差（Lab 欧氏距离） """
    diff = np.asarray(lab1, dtype=np.float64) - np.asarray(lab2, dtype=np.float64)
    return np.sqrt(np.sum(diff * diff, axis=-1))


def delta_e_00(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """ CIEDE2000 色差，支持成对数组 (N,3) 或单点 (3,) """
    first = np.asarray(lab1, dtype=np.float64)
    second = np.asarray(lab2, dtype=np.float64)
    first, second = np.broadcast_arrays(first, second)

    l1, a1, b1 = first[..., 0], first[..., 1], first[..., 2]
    l2, a2, b2 = second[..., 0], second[..., 1], second[..., 2]

    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    c_mean = (c1 + c2) / 2.0
    c_mean7 = c_mean ** 7
    g = 0.5 * (1.0 - np.sqrt(c_mean7 / (c_mean7 + 25.0 ** 7)))

    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2
    c1p = np.hypot(a1p, b1)
    c2p = np.hypot(a2p, b2)

    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    h1p = np.where(c1p == 0, 0.0, h1p)
    h2p = np.where(c2p == 0, 0.0, h2p)

    delta_l = l2 - l1
    delta_c = c2p - c1p

    delta_h_angle = h2p - h1p
    delta_h_angle = np.where(delta_h_angle > 180.0, delta_h_angle - 360.0, delta_h_angle)
    delta_h_angle = np.where(delta_h_angle < -180.0, delta_h_angle + 360.0, delta_h_angle)
    delta_h_angle = np.where(c1p * c2p == 0, 0.0, delta_h_angle)
    delta_h = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(delta_h_angle / 2.0))

    l_mean = (l1 + l2) / 2.0
    c_mean_p = (c1p + c2p) / 2.0

    h_sum = h1p + h2p
    h_mean = np.where(
        np.abs(h1p - h2p) <= 180.0,
        h_sum / 2.0,
        np.where(h_sum < 360.0, (h_sum + 360.0) / 2.0, (h_sum - 360.0) / 2.0),
    )
    h_mean = np.where(c1p * c2p == 0, h_sum, h_mean)

    t = (
        1.0
        - 0.17 * np.cos(np.radians(h_mean - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * h_mean))
        + 0.32 * np.cos(np.radians(3.0 * h_mean + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * h_mean - 63.0))
    )
    delta_theta = 30.0 * np.exp(-(((h_mean - 275.0) / 25.0) ** 2))
    c_mean_p7 = c_mean_p ** 7
    r_c = 2.0 * np.sqrt(c_mean_p7 / (c_mean_p7 + 25.0 ** 7))
    s_l = 1.0 + (0.015 * (l_mean - 50.0) ** 2) / np.sqrt(20.0 + (l_mean - 50.0) ** 2)
    s_c = 1.0 + 0.045 * c_mean_p
    s_h = 1.0 + 0.015 * c_mean_p * t
    r_t = -np.sin(np.radians(2.0 * delta_theta)) * r_c

    term_l = delta_l / s_l
    term_c = delta_c / s_c
    term_h = delta_h / s_h
    return np.sqrt(term_l ** 2 + term_c ** 2 + term_h ** 2 + r_t * term_c * term_h)


def nearest_lab_index(palette_lab: np.ndarray, targets_lab: np.ndarray, batch_size: int = 200000) -> np.ndarray:
    """ 在 Lab 空间为每个目标色找最近调色板索引（分批控制内存） """
    palette = np.asarray(palette_lab, dtype=np.float32)
    targets = np.asarray(targets_lab, dtype=np.float32)
    single = targets.ndim == 1
    rows = targets.reshape(-1, 3)

    palette_sq = np.sum(palette * palette, axis=1)
    result = np.empty(len(rows), dtype=np.int32)
    for start in range(0, len(rows), batch_size):
        chunk = rows[start:start + batch_size]
        distances = np.sum(chunk * chunk, axis=1)[:, None] - 2.0 * chunk @ palette.T + palette_sq[None, :]
        result[start:start + len(chunk)] = np.argmin(distances, axis=1)

    return result[0] if single else result
