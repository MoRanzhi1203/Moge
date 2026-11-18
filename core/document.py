##############################
# core/document.py - 画布统一文档模型（查看/编辑共用）
##############################

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from Moge.core.models import GridSpec, RenderResult
from Moge.core.render import render_document


@dataclass
class GridDocument:
    """ 网格文档：查看模式与编辑模式共享同一份数据与编辑历史 """

    spec: GridSpec
    mode: str
    labels: np.ndarray
    entries: list
    materials: list = field(default_factory=list)
    locked: Optional[np.ndarray] = None
    selection: Optional[tuple[int, int, int, int]] = None
    max_history: int = 50
    _history: list = field(default_factory=list, repr=False)
    _redo: list = field(default_factory=list, repr=False)

    def __post_init__(self):
        self.labels = np.asarray(self.labels, dtype=np.int32)
        if self.labels.shape != (self.spec.height, self.spec.width):
            raise ValueError("文档网格尺寸与 spec 不一致")
        if self.locked is None:
            self.locked = np.zeros(self.labels.shape, dtype=bool)
        else:
            self.locked = np.asarray(self.locked, dtype=bool)
            if self.locked.shape != self.labels.shape:
                raise ValueError("锁定掩码尺寸与网格不一致")
        self._history = []
        self._redo = []

    # ---------- 构造 ---------- #
    @classmethod
    def from_result(cls, result: RenderResult) -> "GridDocument":
        """ 复用结果中的 labels 引用，保证渲染与导出读取同一份数据 """
        locked = None
        cells = result.grid.cells
        if cells:
            height, width = result.grid.spec.height, result.grid.spec.width
            if len(cells) == height * width:
                locked = np.array([bool(cell.get("locked", False)) for cell in cells], dtype=bool)
                locked = locked.reshape(height, width)
        return cls(
            spec=result.grid.spec,
            mode=result.mode,
            labels=result.grid.labels,
            entries=list(result.grid.entries),
            materials=list(result.grid.materials),
            locked=locked,
        )

    # ---------- 编辑历史 ---------- #
    @property
    def can_undo(self) -> bool:
        return bool(self._history)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def push_history(self):
        """ 在修改 labels 之前记录快照 """
        self._history.append(self.labels.copy())
        if len(self._history) > self.max_history:
            self._history.pop(0)
        self._redo.clear()

    def undo(self) -> bool:
        if not self._history:
            return False
        self._redo.append(self.labels.copy())
        self.labels = self._history.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._history.append(self.labels.copy())
        self.labels = self._redo.pop()
        return True

    def clear_history(self):
        """ 调色板整体替换等结构变化后清空历史，避免撤销回到不兼容的调色板 """
        self._history.clear()
        self._redo.clear()

    # ---------- 区域锁定 ---------- #
    def is_locked(self, col: int, row: int) -> bool:
        if self.locked is None or not (0 <= row < self.locked.shape[0] and 0 <= col < self.locked.shape[1]):
            return False
        return bool(self.locked[row, col])

    def toggle_lock(self, col: int, row: int) -> bool:
        if not (0 <= row < self.spec.height and 0 <= col < self.spec.width):
            return False
        self.locked[row, col] = not self.locked[row, col]
        return bool(self.locked[row, col])

    def lock_selection(self, locked: bool = True):
        if self.selection is None:
            return
        x0, y0, x1, y1 = self.selection
        self.locked[min(y0, y1):max(y0, y1) + 1, min(x0, x1):max(x0, x1) + 1] = bool(locked)

    # ---------- 选区 ---------- #
    def set_selection(self, start: tuple[int, int], end: tuple[int, int]):
        col0, row0 = start
        col1, row1 = end
        self.selection = (min(col0, col1), min(row0, row1), max(col0, col1), max(row0, row1))

    def clear_selection(self):
        self.selection = None

    # ---------- 渲染 ---------- #
    def render(self, style: str = "solid") -> np.ndarray:
        return render_document(self, style)
