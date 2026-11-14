##############################
# core/grid.py - 逻辑网格采样与渲染
##############################

import cv2
import numpy as np

from Moge.core.models import GridSpec, PixelGrid


def ensure_rgb(image: np.ndarray) -> tuple:
    """ 将输入规范为 RGB uint8；透明像素按白底合成并返回 alpha 诊断信息 """
    if image is None:
        raise ValueError("图像为空")
    array = np.asarray(image)
    if array.ndim == 2:
        array = np.stack([array, array, array], axis=-1)
    if array.shape[2] == 4:
        alpha = array[..., 3]
        transparent = int(np.count_nonzero(alpha == 0))
        rgb = array[..., :3].astype(np.float32) * (alpha[..., None].astype(np.float32) / 255.0)
        rgb += 255.0 * (1.0 - alpha[..., None].astype(np.float32) / 255.0)
        return np.clip(np.rint(rgb), 0, 255).astype(np.uint8), {"transparent_pixels": transparent}
    if array.shape[2] < 3:
        raise ValueError("图像通道数不足")
    return np.ascontiguousarray(array[..., :3].astype(np.uint8)), {"transparent_pixels": 0}


def _block_modes(image: np.ndarray, spec: GridSpec) -> np.ndarray:
    """ 逐格取众数颜色（平局取最先出现的颜色） """
    height, width = image.shape[:2]
    output = np.empty((spec.height, spec.width, 3), dtype=np.uint8)
    for row in range(spec.height):
        y0 = int(row * height / spec.height)
        y1 = max(y0 + 1, int((row + 1) * height / spec.height))
        for col in range(spec.width):
            x0 = int(col * width / spec.width)
            x1 = max(x0 + 1, int((col + 1) * width / spec.width))
            block = image[y0:y1, x0:x1].reshape(-1, 3)
            colors, counts = np.unique(block, axis=0, return_counts=True)
            output[row, col] = colors[int(np.argmax(counts))]
    return output


def _edge_mask(image: np.ndarray, spec: GridSpec) -> np.ndarray:
    """ 将梯度强度缩放到网格分辨率，作为细节保护掩码 """
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(grad_x, grad_y)
    reduced = cv2.resize(magnitude, (spec.width, spec.height), interpolation=cv2.INTER_AREA)
    threshold = max(8.0, float(reduced.mean()) * 1.5)
    return reduced >= threshold


def sample_grid(image: np.ndarray, spec: GridSpec, method: str = "mean") -> np.ndarray:
    """
    将源图采样为逻辑网格颜色
    :param method: mean / mode / center / edge
    """
    rgb, _ = ensure_rgb(image)
    if method == "mean":
        return cv2.resize(rgb, (spec.width, spec.height), interpolation=cv2.INTER_AREA)
    if method == "center":
        return cv2.resize(rgb, (spec.width, spec.height), interpolation=cv2.INTER_NEAREST)
    if method == "mode":
        return _block_modes(rgb, spec)
    if method == "edge":
        base = cv2.resize(rgb, (spec.width, spec.height), interpolation=cv2.INTER_AREA)
        detail = cv2.resize(rgb, (spec.width, spec.height), interpolation=cv2.INTER_NEAREST)
        mask = _edge_mask(rgb, spec)
        result = base.copy()
        result[mask] = detail[mask]
        return result
    raise ValueError(f"未知采样方式：{method}")


def render_grid(labels: np.ndarray, entries: list, transparent: bool = False) -> np.ndarray:
    """ 按网格标签渲染逻辑分辨率图像；labels=-1 视为透明 """
    array = np.asarray(labels)
    if array.ndim != 2:
        raise ValueError("labels 必须为二维数组")
    height, width = array.shape
    channels = 4 if transparent else 3
    output = np.zeros((height, width, channels), dtype=np.uint8)

    colors = np.array([entry.rgb for entry in entries], dtype=np.uint8) if entries else np.zeros((0, 3), np.uint8)
    valid = array >= 0
    if np.any(valid):
        output[valid, :3] = colors[array[valid]]
    if transparent:
        output[..., 3] = np.where(valid, 255, 0)
    return output


def upscale_grid(image: np.ndarray, cell_size: int) -> np.ndarray:
    """ 最近邻放大到导出分辨率 """
    if cell_size < 1:
        raise ValueError("单元格尺寸必须大于 0")
    return np.repeat(np.repeat(image, cell_size, axis=0), cell_size, axis=1)


def build_pixel_grid(
    labels: np.ndarray,
    entries: list,
    spec: GridSpec,
    mode: str,
    materials: list = None,
) -> PixelGrid:
    """ 构造并校验逻辑网格 """
    grid = PixelGrid(
        spec=spec,
        labels=np.asarray(labels, dtype=np.int32),
        entries=list(entries),
        mode=mode,
        materials=list(materials or []),
    )
    if not grid.validate():
        raise ValueError("网格数据不合法")
    return grid


def isolated_cells(labels: np.ndarray) -> int:
    """ 统计四邻域均与自身不同的孤立单元数量 """
    array = np.asarray(labels)
    if array.shape[0] < 3 or array.shape[1] < 3:
        return 0
    center = array[1:-1, 1:-1]
    same = (
        (center == array[:-2, 1:-1])
        | (center == array[2:, 1:-1])
        | (center == array[1:-1, :-2])
        | (center == array[1:-1, 2:])
    )
    return int(np.count_nonzero(~same))
