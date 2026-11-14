##############################
# core/models.py - 处理参数模型
##############################

from dataclasses import dataclass
from enum import Enum

from Moge.core.image_processor import ResizeMode


class PixelMethod(Enum):
    """ 像素化计算方法 """

    MEAN = '平均值'
    MODE = '频数值'


@dataclass(frozen=True)
class ProcessingParams:
    """ 一次图像处理所需的全部参数 """

    block_size: int
    resize_mode: ResizeMode
    pixel_method: PixelMethod
    n_clusters: int
    seed: int
