##############################
# core/render.py - 网格渲染器：纯色渲染与真实贴图渲染
##############################

from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from Moge.core.grid import render_grid

_TEXTURE_CACHE: dict = {}
_TEXTURE_CACHE_LIMIT = 256


def load_texture_tile(path: str, size: int) -> Optional[np.ndarray]:
    """ 读取并缩放贴图为 RGBA 方块；带缓存，文件缺失返回 None """
    if not path:
        return None
    key = (str(path), int(size))
    cached = _TEXTURE_CACHE.get(key)
    if cached is not None:
        return cached
    if not Path(path).is_file():
        return None
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
    elif image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    tile = cv2.resize(image, (int(size), int(size)), interpolation=cv2.INTER_NEAREST)
    tile = cv2.cvtColor(tile, cv2.COLOR_BGRA2RGBA)
    if len(_TEXTURE_CACHE) >= _TEXTURE_CACHE_LIMIT:
        _TEXTURE_CACHE.clear()
    _TEXTURE_CACHE[key] = tile
    return tile


def _solid_tile(rgb, size: int) -> np.ndarray:
    tile = np.zeros((int(size), int(size), 4), dtype=np.uint8)
    tile[..., :3] = np.array(rgb, dtype=np.uint8)
    tile[..., 3] = 255
    return tile


def render_textured(labels: np.ndarray, entries: list, cell_pixels: int = 16) -> np.ndarray:
    """ 使用每个材料的真实贴图渲染；缺失贴图时回退纯色，空单元保持透明 """
    array = np.asarray(labels)
    if array.ndim != 2:
        raise ValueError("labels 必须为二维数组")
    height, width = array.shape
    cell_pixels = max(1, int(cell_pixels))
    canvas = np.zeros((height * cell_pixels, width * cell_pixels, 4), dtype=np.uint8)
    for index, entry in enumerate(entries):
        mask = array == index
        if not mask.any():
            continue
        path = str(entry.meta.get("texture_path") or "")
        tile = load_texture_tile(path, cell_pixels)
        if tile is None:
            tile = _solid_tile(entry.rgb, cell_pixels)
        tiled = np.tile(tile, (height, width, 1))
        big_mask = np.repeat(np.repeat(mask, cell_pixels, axis=0), cell_pixels, axis=1)
        canvas[big_mask] = tiled[big_mask]
    return canvas


def render_document(document, style: str = "solid") -> np.ndarray:
    """ 根据预览风格渲染文档；切换风格不修改网格与材料统计 """
    transparent = document.mode in ("pixel", "beads")
    if style == "texture":
        return render_textured(document.labels, document.entries)
    return render_grid(document.labels, document.entries, transparent=transparent)
