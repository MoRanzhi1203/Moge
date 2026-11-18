##############################
# ui/canvas.py - 可缩放/平移/编辑的像素网格画布（拼豆施工图增强）
##############################

from typing import Optional

import numpy as np
from PyQt5.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QWidget

from Moge.core.beads.pattern import board_regions

RULER_SIZE = 24


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
        self._hover_cell: tuple[int, int] = (-1, -1)
        self._press_position = None
        self._press_cell: Optional[tuple[int, int]] = None
        self._locked = None
        self._selection = None
        self._zoom_badge_text = ""
        self._zoom_badge_timer = QTimer(self)
        self._zoom_badge_timer.setSingleShot(True)
        self._zoom_badge_timer.setInterval(900)
        self._zoom_badge_timer.timeout.connect(self._hide_zoom_badge)

        # 拼豆施工图显示状态
        self._entries: list = []
        self._symbols: dict = {}
        self._labels = None
        self._view_mode = "preview"
        self._axis_x = False
        self._axis_y = False
        self._coordinate_numbers = False
        self._coordinate_step = 1
        self._guide5 = False
        self._guide10 = False
        self._board_partitions = False
        self._board_width = 29
        self._board_height = 29
        self._cell_mode = "color"
        self._marker_color = True
        self._marker_code = False
        self._marker_symbol = False
        self._highlight_label: Optional[int] = None

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

    def set_bead_entries(self, entries: Optional[list], symbols: Optional[dict] = None, labels=None):
        """ 提供拼豆条目、符号与逐格标签，供格内标记/黑白视图/空白格绘制使用 """
        self._entries = list(entries or [])
        self._symbols = dict(symbols or {})
        self._labels = None if labels is None else np.asarray(labels)
        self.update()

    def set_highlight_label(self, label: Optional[int]):
        """ 高亮某个调色板条目在所有格子的使用位置 """
        self._highlight_label = None if label is None or label < 0 else int(label)
        self.update()

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

    def set_editable(self, editable: bool):
        self._editable = editable

    def set_grid_visible(self, visible: bool):
        self._show_grid = bool(visible)
        self.update()

    # ---------- 拼豆显示配置 ---------- #
    def configure_beads(self, options: dict):
        """ 统一更新施工图显示开关；只影响渲染，不触碰工程数据 """
        self._view_mode = str(options.get("view_mode", self._view_mode))
        self._axis_x = bool(options.get("axis_x", self._axis_x))
        self._axis_y = bool(options.get("axis_y", self._axis_y))
        self._coordinate_numbers = bool(options.get("coordinate_numbers", self._coordinate_numbers))
        self._coordinate_step = max(1, int(options.get("coordinate_step", self._coordinate_step)))
        self._show_grid = bool(options.get("grid", self._show_grid))
        self._guide5 = bool(options.get("guide5", self._guide5))
        self._guide10 = bool(options.get("guide10", self._guide10))
        self._board_partitions = bool(options.get("board_partitions", self._board_partitions))
        self._board_width = max(1, int(options.get("board_width", self._board_width)))
        self._board_height = max(1, int(options.get("board_height", self._board_height)))
        self._cell_mode = str(options.get("cell_mode", self._cell_mode))
        self._marker_color = bool(options.get("marker_color", self._marker_color))
        self._marker_code = bool(options.get("marker_code", self._marker_code))
        self._marker_symbol = bool(options.get("marker_symbol", self._marker_symbol))
        self.update()

    def bead_options(self) -> dict:
        return {
            "view_mode": self._view_mode,
            "axis_x": self._axis_x,
            "axis_y": self._axis_y,
            "coordinate_numbers": self._coordinate_numbers,
            "coordinate_step": self._coordinate_step,
            "grid": self._show_grid,
            "guide5": self._guide5,
            "guide10": self._guide10,
            "board_partitions": self._board_partitions,
            "board_width": self._board_width,
            "board_height": self._board_height,
            "cell_mode": self._cell_mode,
            "marker_color": self._marker_color,
            "marker_code": self._marker_code,
            "marker_symbol": self._marker_symbol,
        }

    def apply_view_preset(self, preset: str):
        """ 成品预览 / 施工图 / 黑白打印 / 图例统计预设 """
        preset = preset if preset in ("preview", "blueprint", "mono", "legend") else "preview"
        if preset == "preview":
            options = {
                "view_mode": "preview",
                "axis_x": False,
                "axis_y": False,
                "coordinate_numbers": False,
                "grid": False,
                "guide5": False,
                "guide10": False,
                "board_partitions": False,
                "cell_mode": "color",
                "marker_color": True,
                "marker_code": False,
                "marker_symbol": False,
            }
        elif preset == "mono":
            options = {
                "view_mode": "mono",
                "axis_x": True,
                "axis_y": True,
                "coordinate_numbers": True,
                "coordinate_step": 1,
                "grid": True,
                "guide5": True,
                "guide10": True,
                "board_partitions": True,
                "cell_mode": "symbol",
                "marker_color": False,
                "marker_code": False,
                "marker_symbol": True,
            }
        elif preset == "legend":
            options = {
                "view_mode": "legend",
                "axis_x": True,
                "axis_y": True,
                "coordinate_numbers": True,
            }
        else:
            options = {
                "view_mode": "blueprint",
                "axis_x": True,
                "axis_y": True,
                "coordinate_numbers": True,
                "coordinate_step": 1,
                "grid": True,
                "guide5": True,
                "guide10": True,
                "board_partitions": True,
                "cell_mode": "code",
                "marker_color": True,
                "marker_code": True,
                "marker_symbol": False,
            }
        self.configure_beads(options)

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
        self.zoomChanged.emit(self._display_scale())

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
        left, top = self._ruler_margins()
        center_x = (self.width() + left) / 2.0
        center_y = (self.height() + top) / 2.0
        cell_x = (col + 0.5) * scale
        cell_y = (row + 0.5) * scale
        self._pan = QPoint(int(center_x - cell_x), int(center_y - cell_y))
        self.update()
        self.zoomChanged.emit(self._display_scale())

    def zoom(self) -> float:
        return self._display_scale()

    def _ruler_margins(self) -> tuple[int, int]:
        if self._view_mode == "preview":
            return 0, 0
        left = RULER_SIZE if self._axis_y else 0
        top = RULER_SIZE if self._axis_x else 0
        return left, top

    def _display_scale(self) -> float:
        if not self._image:
            return 1.0
        grid_width, grid_height = self._grid
        if grid_width <= 0 or grid_height <= 0:
            return 1.0
        if self._fit:
            left, top = self._ruler_margins()
            scale = min(
                max(1.0, self.width() - left - 40) / grid_width,
                max(1.0, self.height() - top - 40) / grid_height,
            )
            return max(0.1, scale)
        return self._zoom

    def _image_rect(self) -> QRectF:
        if not self._image:
            return QRectF()
        scale = self._display_scale()
        width = self._grid[0] * scale
        height = self._grid[1] * scale
        left, top = self._ruler_margins()
        center_x = (self.width() + left) / 2.0 + self._pan.x()
        center_y = (self.height() + top) / 2.0 + self._pan.y()
        return QRectF(center_x - width / 2.0, center_y - height / 2.0, width, height)

    def cell_rect(self, col: int, row: int) -> QRectF:
        """ 返回单元格在控件中的矩形，供测试与坐标定位使用 """
        rect = self._image_rect()
        if rect.isEmpty() or self._grid[0] <= 0 or self._grid[1] <= 0:
            return QRectF()
        cell_w = rect.width() / self._grid[0]
        cell_h = rect.height() / self._grid[1]
        return QRectF(rect.left() + col * cell_w, rect.top() + row * cell_h, cell_w, cell_h)

    def _cell_size(self, axis: str) -> float:
        rect = self._image_rect()
        if axis == "x":
            return rect.width() / max(1, self._grid[0])
        return rect.height() / max(1, self._grid[1])

    def _effective_coordinate_step(self, cell: float) -> int:
        step = max(1, int(self._coordinate_step))
        if step == 1:
            if cell < 7:
                return 10
            if cell < 12:
                return 5
        return step

    def axis_tick_positions(self, axis: str) -> list[tuple[int, float]]:
        """ 坐标尺刻度：返回 [(格号, 像素位置)]，标签位于格子中心 """
        if not self._image:
            return []
        rect = self._image_rect()
        axis = "y" if axis == "y" else "x"
        count = self._grid[1] if axis == "y" else self._grid[0]
        cell = self._cell_size(axis)
        origin = rect.top() if axis == "y" else rect.left()
        step = self._effective_coordinate_step(cell)
        return [(index, origin + (index + 0.5) * cell) for index in range(0, count, step)]

    def guide_line_positions(self, axis: str, step: int) -> list[float]:
        """ 辅助线位置：格边界，不含 0 与末端 """
        if not self._image:
            return []
        rect = self._image_rect()
        axis = "y" if axis == "y" else "x"
        count = self._grid[1] if axis == "y" else self._grid[0]
        cell = self._cell_size(axis)
        origin = rect.top() if axis == "y" else rect.left()
        step = max(1, int(step))
        return [origin + index * cell for index in range(step, count, step)]

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

        if self._view_mode == "mono" and self._labels is not None and self._entries:
            self._draw_mono_cells(painter, rect)
        else:
            source = self._reference if (self._show_reference and self._reference is not None) else self._image
            painter.drawImage(rect, source)
            self._draw_empty_cells(painter, rect)

        self._draw_guides(painter, rect)
        self._draw_cell_markers(painter, rect)
        self._draw_highlight(painter, rect)
        self._draw_locked(painter, rect)
        self._draw_selection(painter, rect)
        self._draw_hover_cell(painter, rect)

        painter.setPen(QPen(QColor("#4a5163"), 1))
        painter.drawRect(rect)
        self._draw_axes(painter, rect)
        self._draw_zoom_badge(painter)

    def _draw_zoom_badge(self, painter: QPainter):
        """ 滚轮缩放时在画布右上角显示短暂提示，提供即时反馈 """
        if not self._zoom_badge_text:
            return
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(self._zoom_badge_text) + 18
        height = metrics.height() + 10
        badge = QRectF(self.width() - width - 12, 12, width, height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(18, 20, 26, 210))
        painter.drawRoundedRect(badge, 6, 6)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(badge, Qt.AlignCenter, self._zoom_badge_text)
        painter.restore()

    def _set_zoom_badge(self, scale: float):
        if scale <= 0.2001:
            text = f"最小缩放 {scale:.2f}×"
        elif scale >= 63.99:
            text = f"最大缩放 {scale:.2f}×"
        else:
            text = f"缩放 {scale:.2f}×"
        self._zoom_badge_text = text
        self._zoom_badge_timer.start()
        self.update()

    def _hide_zoom_badge(self):
        self._zoom_badge_text = ""
        self.update()

    def _visible_range(self, rect: QRectF):
        clip = rect.intersected(QRectF(self.rect()))
        if clip.isEmpty() or self._grid[0] <= 0 or self._grid[1] <= 0:
            return None
        cell_w = rect.width() / self._grid[0]
        cell_h = rect.height() / self._grid[1]
        col0 = max(0, int((clip.left() - rect.left()) / cell_w))
        col1 = min(self._grid[0] - 1, int((clip.right() - rect.left()) / cell_w))
        row0 = max(0, int((clip.top() - rect.top()) / cell_h))
        row1 = min(self._grid[1] - 1, int((clip.bottom() - rect.top()) / cell_h))
        return col0, row0, col1, row1

    def _draw_empty_cells(self, painter: QPainter, rect: QRectF):
        """ 空白格用浅棋盘标出，与真正的白色珠子区分 """
        if self._labels is None:
            return
        visible = self._visible_range(rect)
        if visible is None:
            return
        shape = self._labels.shape
        if shape != (self._grid[1], self._grid[0]):
            return
        cell_w = rect.width() / self._grid[0]
        cell_h = rect.height() / self._grid[1]
        if cell_w < 3 or cell_h < 3:
            return
        col0, row0, col1, row1 = visible
        half_w = cell_w / 2.0
        half_h = cell_h / 2.0
        painter.save()
        painter.setClipRect(rect)
        for row in range(row0, row1 + 1):
            for col in range(col0, col1 + 1):
                if int(self._labels[row, col]) >= 0:
                    continue
                x = rect.left() + col * cell_w
                y = rect.top() + row * cell_h
                painter.fillRect(QRectF(x, y, cell_w, cell_h), QColor(238, 238, 238))
                painter.fillRect(QRectF(x, y, half_w, half_h), QColor(214, 214, 214))
                painter.fillRect(QRectF(x + half_w, y + half_h, half_w, half_h), QColor(214, 214, 214))
        painter.restore()

    def _draw_mono_cells(self, painter: QPainter, rect: QRectF):
        """ 黑白打印视图：白底 + 唯一种类符号，空白格无符号 """
        visible = self._visible_range(rect)
        if visible is None:
            return
        cell_w = rect.width() / self._grid[0]
        cell_h = rect.height() / self._grid[1]
        col0, row0, col1, row1 = visible
        painter.save()
        painter.setClipRect(rect)
        for row in range(row0, row1 + 1):
            for col in range(col0, col1 + 1):
                value = int(self._labels[row, col])
                x = rect.left() + col * cell_w
                y = rect.top() + row * cell_h
                painter.fillRect(QRectF(x, y, cell_w, cell_h), QColor("#ffffff"))
                if value < 0 or value >= len(self._entries):
                    continue
                if cell_w < 6:
                    continue
                entry = self._entries[value]
                symbol = self._symbols.get(entry.id, "")
                if not symbol:
                    continue
                painter.setPen(QColor("#111111"))
                painter.setFont(QFont("Arial", max(5, min(11, int(cell_w * 0.42))), QFont.Bold))
                painter.drawText(QRectF(x, y, cell_w, cell_h), Qt.AlignCenter, symbol)
        painter.restore()

    def _draw_guides(self, painter: QPainter, rect: QRectF):
        if self._view_mode == "preview":
            return
        cell = rect.width() / max(1, self._grid[0])
        painter.save()
        painter.setClipRect(rect)
        if self._show_grid and cell >= 4:
            painter.setPen(QPen(QColor(120, 120, 120, 80), 0))
            for col in range(1, self._grid[0]):
                x = rect.left() + col * cell
                painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            for row in range(1, self._grid[1]):
                y = rect.top() + row * cell
                painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
        if self._guide5:
            painter.setPen(QPen(QColor(70, 140, 220, 160), 1))
            for x in self.guide_line_positions("x", 5):
                if self._guide10 and int((x - rect.left()) / cell) % 10 == 0:
                    continue
                painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            for y in self.guide_line_positions("y", 5):
                if self._guide10 and int((y - rect.top()) / cell) % 10 == 0:
                    continue
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        if self._guide10:
            painter.setPen(QPen(QColor(240, 160, 50, 220), 2))
            for x in self.guide_line_positions("x", 10):
                painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            for y in self.guide_line_positions("y", 10):
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.restore()

        if self._board_partitions:
            self._draw_board_partitions(painter, rect, cell)

    def _draw_board_partitions(self, painter: QPainter, rect: QRectF, cell: float):
        painter.save()
        painter.setClipRect(rect)
        pen = QPen(QColor(255, 110, 90, 220), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for region in board_regions(self._grid[0], self._grid[1], self._board_width, self._board_height):
            region_rect = QRectF(
                rect.left() + region["x0"] * cell,
                rect.top() + region["y0"] * cell,
                region["width"] * cell,
                region["height"] * cell,
            )
            painter.drawRect(region_rect)
            if cell >= 8:
                tag = QRectF(region_rect.left() + 2, region_rect.top() + 2, 30, 16)
                painter.fillRect(tag, QColor(255, 110, 90, 230))
                painter.setPen(QColor("#ffffff"))
                painter.setFont(QFont("Arial", 8, QFont.Bold))
                painter.drawText(tag, Qt.AlignCenter, region["label"])
                painter.setPen(pen)
        painter.restore()

    def _draw_cell_markers(self, painter: QPainter, rect: QRectF):
        if self._view_mode in ("preview", "mono") or not self._entries or self._labels is None:
            return
        cell = rect.width() / max(1, self._grid[0])
        mode = self._cell_mode
        if mode == "color":
            return
        visible = self._visible_range(rect)
        if visible is None:
            return
        col0, row0, col1, row1 = visible
        cell_h = rect.height() / max(1, self._grid[1])
        painter.save()
        painter.setClipRect(rect)
        for row in range(row0, row1 + 1):
            for col in range(col0, col1 + 1):
                value = int(self._labels[row, col])
                if value < 0 or value >= len(self._entries):
                    continue
                entry = self._entries[value]
                meta = entry.meta or {}
                symbol = self._symbols.get(entry.id, "") or str(meta.get("symbol") or "")
                cell_code = str(meta.get("cell_code") or meta.get("code") or "")
                text = ""
                if mode == "mixed":
                    if cell >= 18 and self._marker_code:
                        text = cell_code
                    elif cell >= 8:
                        text = str(meta.get("abbrev") or cell_code or "")
                elif mode == "code" and self._marker_code:
                    text = cell_code if cell >= 9 else ""
                elif mode == "abbrev" and self._marker_code:
                    text = str(meta.get("abbrev") or cell_code or "") if cell >= 7 else ""
                elif mode == "symbol" and self._marker_symbol:
                    text = symbol if cell >= 6 else ""
                if not text:
                    continue
                x = rect.left() + col * cell
                y = rect.top() + row * cell
                font_size = max(5, min(11, int(cell * 0.34)))
                painter.setFont(QFont("Segoe UI", font_size))
                rgb = entry.rgb
                luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
                painter.setPen(QColor("#111111") if luminance > 150 else QColor("#ffffff"))
                painter.drawText(QRectF(x, y, cell, cell_h), Qt.AlignCenter, text)
        painter.restore()

    def _draw_highlight(self, painter: QPainter, rect: QRectF):
        """ 高亮当前图例条目对应的所有格子，便于定位材料使用位置 """
        if self._highlight_label is None or self._labels is None:
            return
        visible = self._visible_range(rect)
        if visible is None:
            return
        if self._labels.shape != (self._grid[1], self._grid[0]):
            return
        col0, row0, col1, row1 = visible
        cell_w = rect.width() / self._grid[0]
        cell_h = rect.height() / self._grid[1]
        painter.save()
        painter.setClipRect(rect)
        painter.setPen(QPen(QColor(255, 196, 45, 230), 1))
        painter.setBrush(QColor(255, 196, 45, 52))
        for row in range(row0, row1 + 1):
            for col in range(col0, col1 + 1):
                if int(self._labels[row, col]) != self._highlight_label:
                    continue
                painter.drawRect(
                    QRectF(rect.left() + col * cell_w, rect.top() + row * cell_h, cell_w, cell_h)
                )
        painter.restore()

    def _draw_axes(self, painter: QPainter, rect: QRectF):
        if self._view_mode == "preview" or not (self._axis_x or self._axis_y):
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        strip_color = QColor(42, 46, 55, 235)
        border_color = QColor(90, 98, 115)
        text_color = QColor("#dfe6f3")
        if self._axis_x:
            top_rect = QRectF(rect.left(), rect.top() - RULER_SIZE, rect.width(), RULER_SIZE)
            painter.fillRect(top_rect, strip_color)
            painter.setPen(QPen(border_color, 1))
            painter.drawLine(top_rect.bottomLeft(), top_rect.bottomRight())
        if self._axis_y:
            left_rect = QRectF(rect.left() - RULER_SIZE, rect.top(), RULER_SIZE, rect.height())
            painter.fillRect(left_rect, strip_color)
            painter.setPen(QPen(border_color, 1))
            painter.drawLine(left_rect.topRight(), left_rect.bottomRight())
        if self._axis_x and self._axis_y:
            corner = QRectF(rect.left() - RULER_SIZE, rect.top() - RULER_SIZE, RULER_SIZE, RULER_SIZE)
            painter.fillRect(corner, strip_color)
            painter.setPen(QPen(border_color, 1))
            painter.drawRect(corner)

        painter.setPen(QPen(text_color, 1))
        painter.setFont(QFont("Segoe UI", 7))
        for index, position in self.axis_tick_positions("x"):
            painter.setPen(QPen(text_color, 1))
            painter.drawLine(QPointF(position, rect.top() - 4), QPointF(position, rect.top()))
            if self._coordinate_numbers:
                painter.drawText(
                    QRectF(position - 18, rect.top() - RULER_SIZE + 2, 36, RULER_SIZE - 6),
                    Qt.AlignCenter,
                    str(index + 1),
                )
        for index, position in self.axis_tick_positions("y"):
            painter.setPen(QPen(text_color, 1))
            painter.drawLine(QPointF(rect.left() - 4, position), QPointF(rect.left(), position))
            if self._coordinate_numbers:
                painter.drawText(
                    QRectF(rect.left() - RULER_SIZE + 1, position - 8, RULER_SIZE - 5, 16),
                    Qt.AlignRight | Qt.AlignVCenter,
                    str(index + 1),
                )
        painter.restore()

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

    def _draw_hover_cell(self, painter: QPainter, rect: QRectF):
        col, row = self._hover_cell
        if col < 0 or row < 0 or self._grid[0] <= 0:
            return
        cell_rect = self.cell_rect(col, row)
        if cell_rect.isEmpty():
            return
        pen = QPen(QColor(255, 255, 255, 190), 1)
        pen.setStyle(Qt.DotLine)
        painter.save()
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(cell_rect)
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
        delta = event.angleDelta().y()
        if not delta:
            return
        # 按滚轮增量缩放：高分辨率触控板的小增量不再被放大成 25% 跳变
        steps = delta / 120.0
        old_scale = self._display_scale()
        new_zoom = max(0.2, min(64.0, old_scale * (1.25 ** steps)))
        if abs(new_zoom - old_scale) < 1e-6:
            self._set_zoom_badge(new_zoom)
            event.accept()
            return

        position = event.pos()
        old_rect = self._image_rect()
        old_cell_scale = old_rect.width() / self._grid[0]
        image_x = (position.x() - old_rect.left()) / old_cell_scale
        image_y = (position.y() - old_rect.top()) / old_cell_scale

        self._fit = False
        self._zoom = new_zoom
        left, top = self._ruler_margins()
        center_x = (self.width() + left) / 2.0 + self._pan.x()
        center_y = (self.height() + top) / 2.0 + self._pan.y()
        target_x = center_x - self._grid[0] * new_zoom / 2.0
        target_y = center_y - self._grid[1] * new_zoom / 2.0
        desired_x = position.x() - image_x * new_zoom
        desired_y = position.y() - image_y * new_zoom
        self._pan += QPoint(round(desired_x - target_x), round(desired_y - target_y))
        self._set_zoom_badge(new_zoom)
        self.update()
        self.zoomChanged.emit(new_zoom)
        event.accept()

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
            self._hover_cell = hover
            self.update()
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
            self.zoomChanged.emit(self._display_scale())
