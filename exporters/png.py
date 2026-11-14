##############################
# exporters/png.py - PNG/JPEG 导出
##############################

from pathlib import Path

import cv2
import numpy as np

from Moge.core.grid import upscale_grid
from Moge.core.models import RenderResult


def export_png(result: RenderResult, path: str, cell_size: int = 8) -> str:
    """ 按网格最近邻放大后导出 PNG/JPEG，自动匹配扩展名 """
    target = Path(path)
    image = upscale_grid(result.image, max(1, int(cell_size)))
    suffix = target.suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg"):
        suffix = ".png"
        target = target.with_suffix(".png")

    if image.shape[2] == 4:
        if suffix == ".png":
            payload = cv2.cvtColor(image, cv2.COLOR_RGBA2BGRA)
        else:
            alpha = image[..., 3:4].astype(np.float32) / 255.0
            payload = (image[..., :3].astype(np.float32) * alpha + 255.0 * (1.0 - alpha))
            payload = cv2.cvtColor(np.clip(np.rint(payload), 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    else:
        payload = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    codec = ".png" if suffix == ".png" else ".jpg"
    params = [cv2.IMWRITE_PNG_COMPRESSION, 3] if codec == ".png" else [cv2.IMWRITE_JPEG_QUALITY, 95]
    success, buffer = cv2.imencode(codec, payload, params)
    if not success:
        raise OSError(f"图像编码失败：{codec}")
    buffer.tofile(str(target))
    return str(target)
