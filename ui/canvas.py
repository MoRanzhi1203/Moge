##############################
# ui/canvas.py - 可缩放/平移/编辑的像素网格画布
##############################

from typing import Optional

import numpy as np
from PyQt5.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QWidget


class GridCanvas(QWidget):
    """ 中央画布：查看/编辑双模式，最近邻渲染、网格叠层、缩放平移、单元格编辑信号 """

    zoomChanged = pyqtSignal(float)
    hoverCellChanged = pyqtSignal(int, int)
    strokeStarted = pyqtSignal()
    strokeFinished = pyqtSignal()
    cellPressed = pyqtSignal(int, int)
    cellDragged = pyqtSignal(int, int)
    cellInspected = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image: Optional[QImage] = None
        self._reference: Optional[QImage] = None
        self._show_reference = False
        self._grid = (0, 0)
        self._zoom = 1.0
        self._fit = True
        self._pan = QPoint(0, 0)
        self._show_grid = True
        self._editable = False
        self._interaction_mode = "view"
        self._panning = False
        self._painting = False
        self._space_down = False
        self._last_mouse = None
        self._last_hover: tuple[int, int] = (-1, -1)
        self._press_position = None
        self._press_cell: Optional[tuple[int, int]] = None
        self._locked = None
        self._selection = None

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(360, 260)
        self._checker = self._make_checker()

    @staticmethod
    def _make_checker() -> QPixmap:
        """ 预生成透明棋盘格，避免每次重绘逐格绘制 """
        pixmap = QPixmap(16, 16)
        painter = QPainter(pixmap)
        painter.fillRect(0, 0, 16, 16, QColor("#cfcfcf"))
        painter.fillRect(0, 0, 8, 8, QColor("#f2f2f2"))
        painter.fillRect(8, 8, 8, 8, QColor("#f2f2f2"))
        painter.end()
        return pixmap

    # ---------- 数据 ---------- #
    def set_image(self, image: Optional[np.ndarray], grid: Optional[tuple[int, int]] = None):
        if image is None:
            self._image = None
            self._grid = (0, 0)
            self.update()
            return

        array = np.ascontiguousarray(image)
        if array.ndim == 2:
            array = np.stack([array, array, array], axis=-1)
        height, width = array.shape[:2]
        self._image = self._to_qimage(array)
        self._grid = grid if grid else (width, height)
        self.update()

    def image(self) -> Optional[QImage]:
        return self._image

    def set_reference_image(self, image: Optional[np.ndarray]):
        """ 设置对比原图；与结果图分开保存，缩放不触发任何量化 """
        self._reference = self._to_qimage(image)
        if self._reference is None:
            self._show_reference = False
        self.update()

    def set_compare_enabled(self, enabled: bool):
        self._show_reference = bool(enabled and self._reference is not None)
        self.update()

    def compare_enabled(self) -> bool:
        return self._show_reference

    def _to_qimage(self, image: Optional[np.ndarray]) -> Optional[QImage]:
        if image is None:
            return None
        array = np.ascontiguousarray(image)
        if array.ndim == 2:
            array = np.stack([array, array, array], axis=-1)
        height, width = array.shape[:2]
        if array.shape[2] == 4:
            qimage = QImage(array.data, width, height, array.strides[0], QImage.Format_RGBA8888)
        else:
            qimage = QImage(array.data, width, height, array.strides[0], QImage.Format_RGB888)
        return qimage.copy()

    def grid_shape(self) -> tuple[int, int]:
        return self._grid

    def set_editable(self, editable: bool):
        self._editable = editable

    def set_grid_visible(self, visible: bool):
        self._show_grid = bool(visible)
        self.update()

    def grid_visible(self) -> bool:
        return self._show_grid

    # ---------- 查看/编辑 ---------- #
    def set_interaction_mode(self, mode: str):
        """ view：仅查看与平移；edit：允许修改网格数据 """
        self._interaction_mode = "edit" if mode == "edit" else "view"
        self._painting = False
        self._panning = False
        self._press_position = None
        self._press_cell = None
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def interaction_mode(self) -> str:
        return self._interaction_mode

    def set_locked_mask(self, mask):
        self._locked = None if mask is None else np.asarray(mask, dtype=bool)
        self.update()

    def set_selection(self, selection):
        self._selection = tuple(selection) if selection else None
        self.update()

    # ---------- 视图 ---------- #
    def fit_to_view(self):
        self._fit = True
        self._pan = QPoint(0, 0)
        self.update()

    def reset_view(self):
        """ 重置为适应窗口，清除手动缩放与平移 """
        self._zoom = 1.0
        self.fit_to_view()
        self.zoomChanged.emit(self._display_scale())

    def center_on_cell(self, col: int, row: int):
        """ 将指定网格单元定位到画布中央 """
        if not self._image:
            return
        if self._fit:
            self._zoom = self._display_scale()
            self._fit = False
        scale = self._zoom
        center_x = self.width() / 2.0
        center_y = self.height() / 2.0
        cell_x = (col + 0.5) * scale
        cell_y = (row + 0.5) * scale
        self._pan = QPoint(int(center_x - cell_x), int(center_y - cell_y))
        self.update()
        self.zoomChanged.emit(self._display_scale())

    def reset_zoom(self):
        self._fit = False
        self._zoom = 1.0
        self._pan = QPoint(0, 0)
        self.update()
        self.zoomChanged.emit(self._zoom)

    def set_zoom(self, zoom: float):
        self._fit = False
        self._zoom = max(0.2, min(64.0, float(zoom)))
        self.update()
        self.zoomChanged.emit(self._zoom)

    def zoom(self) -> float:
        return self._display_scale()

    def _display_scale(self) -> float:
        if not self._image:
            return 1.0
        grid_width, grid_height = self._grid
        if grid_width <= 0 or grid_height <= 0:
            return 1.0
        if self._fit:
            scale = min(
                max(1.0, self.width() - 40) / grid_width,
                max(1.0, self.height() - 40) / grid_height,
            )
            return max(0.1, scale)
        return self._zoom

    def _image_rect(self) -> QRectF:
        if not self._image:
            return QRectF()
        scale = self._display_scale()
        width = self._grid[0] * scale
        height = self._grid[1] * scale
        center_x = self.width() / 2.0 + self._pan.x()
        center_y = self.height() / 2.0 + self._pan.y()
        return QRectF(center_x - width / 2.0, center_y - height / 2.0, width, height)

    def cell_at(self, position) -> Optional[tuple[int, int]]:
        if not self._image:
            return None
        rect = self._image_rect()
        if not rect.contains(position):
            return None
        col = int((position.x() - rect.left()) / rect.width() * self._grid[0])
        row = int((position.y() - rect.top()) / rect.height() * self._grid[1])
        col = min(max(col, 0), self._grid[0] - 1)
        row = min(max(row, 0), self._grid[1] - 1)
        return col, row

    # ---------- 绘制 ---------- #
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#171920"))

        rect = self._image_rect()
        if self._image is None or rect.isEmpty():
            painter.setPen(QColor("#8a93a6"))
            painter.drawText(self.rect(), Qt.AlignCenter, "打开图片或工程开始创作")
            return

        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self._draw_checkerboard(painter, rect)
        source = self._reference if (self._show_reference and self._reference is not None) else self._image
        painter.drawImage(rect, source)

        if self._show_grid:
            scale = rect.width() / self._grid[0]
            if scale >= 6:
                pen = QPen(QColor(255, 255, 255, 40))
                pen.setWidth(0)
                painter.setPen(pen)
                for col in range(1, self._grid[0]):
                    x = rect.left() + col * scale
                    painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
                for row in range(1, self._grid[1]):
                    y = rect.top() + row * scale
                    painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))

        self._draw_locked(painter, rect)
        self._draw_selection(painter, rect)

        painter.setPen(QPen(QColor("#4a5163"), 1))
        painter.drawRect(rect)

    def _draw_locked(self, painter: QPainter, rect: QRectF):
        if self._locked is None or not self._locked.any() or self._grid[0] <= 0:
            return
        scale = rect.width() / self._grid[0]
        rows, cols = np.nonzero(self._locked)
        painter.save()
        painter.setClipRect(rect)
        painter.setPen(QPen(QColor(255, 128, 96, 190), 1))
        for row, col in zip(rows.tolist(), cols.tolist()):
            x0 = rect.left() + col * scale
            y0 = rect.top() + row * scale
            painter.fillRect(QRectF(x0, y0, scale, scale), QColor(255, 128, 96, 40))
            painter.drawLine(int(x0), int(y0), int(x0 + scale), int(y0 + scale))
        painter.restore()

    def _draw_selection(self, painter: QPainter, rect: QRectF):
        if not self._selection or self._grid[0] <= 0:
            return
        col0, row0, col1, row1 = self._selection
        scale = rect.width() / self._grid[0]
        selection = QRectF(
            rect.left() + col0 * scale,
            rect.top() + row0 * scale,
            (col1 - col0 + 1) * scale,
            (row1 - row0 + 1) * scale,
        )
        pen = QPen(QColor("#4fc3f7"), 2)
        pen.setStyle(Qt.DashLine)
        painter.save()
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(selection)
        painter.restore()

    def _draw_checkerboard(self, painter: QPainter, rect: QRectF):
        painter.save()
        painter.setClipRect(rect)
        painter.drawTiledPixmap(rect.toRect(), self._checker)
        painter.restore()

    # ---------- 交互 ---------- #
    def wheelEvent(self, event):
        if not self._image:
            return
        position = event.pos()
        old_rect = self._image_rect()
        old_scale = old_rect.width() / self._grid[0]
        image_x = (position.x() - old_rect.left()) / old_scale
        image_y = (position.y() - old_rect.top()) / old_scale

        step = 1.25 if event.angleDelta().y() > 0 else 1 / 1.25
        self._fit = False
        self._zoom = max(0.2, min(64.0, self._display_scale() * step))
        new_scale = self._zoom
        center_x = self.width() / 2.0 + self._pan.x()
        center_y = self.height() / 2.0 + self._pan.y()
        target_x = center_x - self._grid[0] * new_scale / 2.0
        target_y = center_y - self._grid[1] * new_scale / 2.0
        desired_x = position.x() - image_x * new_scale
        desired_y = position.y() - image_y * new_scale
        self._pan += QPoint(int(desired_x - target_x), int(desired_y - target_y))
        self.update()
        self.zoomChanged.emit(self._display_scale())

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and self._space_down):
            self._panning = True
            self._last_mouse = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            return
        cell = self.cell_at(event.pos())
        if event.button() == Qt.LeftButton and cell is not None:
            if self._interaction_mode == "view":
                # 查看模式：左键拖动平移，单击检查
                self._panning = True
                self._last_mouse = event.pos()
                self._press_position = event.pos()
                self._press_cell = cell
                self.setCursor(Qt.ClosedHandCursor)
                return
            if self._editable:
                self._painting = True
                self.strokeStarted.emit()
                self.cellPressed.emit(cell[0], cell[1])

    def mouseMoveEvent(self, event):
        if self._panning and self._last_mouse is not None:
            self._pan += event.pos() - self._last_mouse
            self._last_mouse = event.pos()
            self.update()
            return

        cell = self.cell_at(event.pos())
        hover = cell if cell else (-1, -1)
        if hover != self._last_hover:
            self._last_hover = hover
            self.hoverCellChanged.emit(hover[0], hover[1])

        if self._painting and cell is not None:
            self.cellDragged.emit(cell[0], cell[1])

    def mouseReleaseEvent(self, event):
        was_painting = self._painting
        if self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            if (
                self._interaction_mode == "view"
                and self._press_position is not None
                and self._press_cell is not None
                and (event.pos() - self._press_position).manhattanLength() <= 4
            ):
                self.cellInspected.emit(self._press_cell[0], self._press_cell[1])
        self._press_position = None
        self._press_cell = None
        self._painting = False
        if was_painting:
            self.strokeFinished.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self._space_down = True
            self.setCursor(Qt.OpenHandCursor)
        elif event.key() == Qt.Key_C and self._reference is not None:
            self._show_reference = True
            self.update()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space:
            self._space_down = False
            self.setCursor(Qt.ArrowCursor)
        elif event.key() == Qt.Key_C and self._reference is not None:
            self._show_reference = False
            self.update()
        super().keyReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit:
            self.update()
