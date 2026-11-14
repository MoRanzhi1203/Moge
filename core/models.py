##############################
# core/models.py - 数据模型（兼容层 + Moge 2.0 模型）
##############################

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import numpy as np

from Moge.core.image_processor import ResizeMode


class PixelMethod(Enum):
    """ 像素化计算方法（旧接口） """

    MEAN = '平均值'
    MODE = '频数值'


@dataclass(frozen=True)
class ProcessingParams:
    """ 旧版一次图像处理所需的全部参数（保持兼容） """

    block_size: int
    resize_mode: ResizeMode
    pixel_method: PixelMethod
    n_clusters: int
    seed: int


RGB = tuple[int, int, int]


@dataclass(frozen=True)
class GridSpec:
    """ 逻辑网格尺寸（与源图像像素尺寸解耦） """

    width: int
    height: int

    def __post_init__(self):
        if self.width < 1 or self.height < 1:
            raise ValueError("网格宽高必须大于 0")

    @property
    def cells(self) -> int:
        return self.width * self.height

    @classmethod
    def from_block_size(cls, image_shape: Sequence[int], block_size: int, mode: ResizeMode = ResizeMode.FLOOR) -> "GridSpec":
        """ 按旧版像素块大小推导网格尺寸 """
        if block_size < 1:
            raise ValueError("像素块大小必须大于 0")
        height, width = image_shape[:2]
        if mode is ResizeMode.CEIL:
            cols = math.ceil(width / block_size)
            rows = math.ceil(height / block_size)
        elif mode is ResizeMode.ROUND:
            cols = max(1, math.floor(width / block_size + 0.5))
            rows = max(1, math.floor(height / block_size + 0.5))
        else:
            cols = max(1, width // block_size)
            rows = max(1, height // block_size)
        return cls(width=cols, height=rows)


@dataclass(frozen=True)
class PaletteEntry:
    """ 可渲染的颜色/材料项，id 稳定用于网格索引与工程文件 """

    id: str
    name: str
    rgb: RGB
    source: str = "generated"
    meta: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def __post_init__(self):
        if len(self.rgb) != 3:
            raise ValueError("rgb 必须为三元组")
        for channel in self.rgb:
            if not 0 <= int(channel) <= 255:
                raise ValueError("rgb 通道必须在 0~255 之间")


@dataclass(frozen=True)
class MaterialRef:
    """ 真实材料引用（Minecraft 方块 / 拼豆色号） """

    id: str
    name: str
    rgb: RGB
    kind: str
    category: str = ""
    source: str = "builtin-approx"
    verified: bool = False
    meta: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def to_palette_entry(self) -> PaletteEntry:
        return PaletteEntry(
            id=self.id,
            name=self.name,
            rgb=self.rgb,
            source=self.source,
            meta=dict(self.meta, kind=self.kind, category=self.category, verified=self.verified),
        )


@dataclass
class PixelGrid:
    """ 逻辑像素网格：labels 为 entries 下标，-1 表示透明/空单元 """

    spec: GridSpec
    labels: np.ndarray
    entries: list[PaletteEntry]
    mode: str = "pixel"
    materials: list[MaterialRef] = field(default_factory=list)

    def __post_init__(self):
        if self.labels.shape != (self.spec.height, self.spec.width):
            raise ValueError(
                f"labels 形状 {self.labels.shape} 与网格 {self.spec.height}x{self.spec.width} 不一致"
            )
        if self.labels.size and self.labels.max() >= len(self.entries):
            raise ValueError("labels 中存在越界的颜色/材料索引")

    def copy(self) -> "PixelGrid":
        return PixelGrid(
            spec=self.spec,
            labels=self.labels.copy(),
            entries=list(self.entries),
            mode=self.mode,
            materials=list(self.materials),
        )

    def counts(self) -> dict[str, int]:
        """ 各颜色/材料的单元数量（忽略透明单元） """
        flat = self.labels.reshape(-1)
        flat = flat[flat >= 0]
        if flat.size == 0:
            return {}
        values, counts = np.unique(flat, return_counts=True)
        return {
            self.entries[int(value)].id: int(count)
            for value, count in zip(values, counts)
        }

    def validate(self) -> bool:
        if self.labels.shape != (self.spec.height, self.spec.width):
            return False
        if self.labels.size and self.labels.min() < -1:
            return False
        if self.labels.size and self.labels.max() >= len(self.entries):
            return False
        return True


@dataclass
class PipelineConfig:
    """ 统一管线配置：阶段名来自 pipeline.STAGES 注册表 """

    mode: str
    grid: GridSpec
    stages: tuple[str, ...]
    sampling: str = "mean"
    quantizer: str = "kmeans_lab"
    target_colors: int = 16
    seed: int = 42
    preset: str = "custom"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RenderResult:
    """ 一次处理的完整结果（预览图不是唯一真相，网格才是） """

    image: np.ndarray
    grid: PixelGrid
    stats: dict[str, Any]
    algorithm: str
    mode: str
    elapsed_ms: float
    diagnostics: dict[str, Any] = field(default_factory=dict)
    source_size: tuple[int, int] = (0, 0)
    settings: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def palette(self) -> list[PaletteEntry]:
        return list(self.grid.entries)


@dataclass
class ProjectDocument:
    """ .moge 工程文件的逻辑内容 """

    version: int = 1
    app_version: str = "2.0.0"
    mode: str = "pixel"
    grid: Optional[PixelGrid] = None
    settings: dict[str, Any] = field(default_factory=dict)
    source_path: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass(frozen=True)
class ExportJob:
    """ 导出任务描述 """

    kind: str
    path: str
    options: dict[str, Any] = field(default_factory=dict)
