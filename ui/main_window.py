##############################
# ui/main_window.py - Moge 2.0 三模式工作台
##############################

import colorsys
import re
from collections import deque
from pathlib import Path

import numpy as np
from PyQt5.QtCore import QRect, QSettings, QSize, Qt, QThread, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QIcon, QImage, QKeySequence, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAction,
    QActionGroup,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from Moge.core.beads.catalog import (
    available_families,
    available_materials,
    available_sizes,
    load_catalog_with_meta,
    material_label,
    nearest_cross_brand,
    preferred_selection,
    trust_label,
)
from Moge.core.beads.pattern import (
    bead_summary,
    board_stats,
    build_symbols,
    legend_rows,
    parse_bead_mm,
    pattern_size_mm,
)
from Moge.core.clustering import ALGORITHM_INFO, EXPERIMENTAL_ALGORITHMS
from Moge.core.document import GridDocument
from Moge.core.grid import isolated_cells, render_grid
from Moge.core.materials import (
    BEAD_CATALOG,
    MC_CATEGORIES,
    MC_VERSIONS,
    BeadColor,
    load_bead_catalog_csv,
    load_bead_inventory_csv,
    load_resource_pack_zip,
)
from Moge.core.models import GridSpec, RenderResult
from Moge.core.modes import beads as beads_mode
from Moge.core.modes import minecraft as minecraft_mode
from Moge.core.modes import pixel as pixel_mode
from Moge.core.modes import registry
from Moge.core.palette_exchange import export_palette_csv, load_palette_csv, remap_to_palette
from Moge.core.workbench import get_adapter, prepare_result
from Moge.exporters.bead_sheet import BeadSheetOptions, export_bead_png, export_partition_pngs
from Moge.exporters.blueprint_pdf import export_blueprint_pdf
from Moge.exporters.csv import export_materials_csv
from Moge.exporters.legend_sheet import LegendSheetOptions, export_legend_png
from Moge.exporters.png import export_png
from Moge.exporters.project import load_project, save_project
from Moge.ui.canvas import GridCanvas
from Moge.ui.theme import apply_theme
from Moge.ui.worker import PipelineWorker
from Moge.utils.logger_config import get_module_logger

logger = get_module_logger(__name__)

IMAGE_FILTER = "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)"
PROJECT_FILTER = "Moge 工程 (*.moge)"

RESULT_CURRENT = "CURRENT"
RESULT_STALE = "STALE"
RESULT_INVALID = "INVALID"

LEGEND_DATA_ROLE = Qt.UserRole + 1
LEGEND_PRIMARY_PT = 9.5
LEGEND_SECONDARY_PT = 8.0
LEGEND_COUNT_PT = 8.5
LEGEND_PADDING_X = 10
LEGEND_PADDING_Y = 6
LEGEND_SWATCH_SIZE = 26


class LegendItemDelegate(QStyledItemDelegate):
    """ 图例条目自绘：统一字体层级、固定内边距、省略超长文本、主题自适应 """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dark = True
        self._texture_cache: dict = {}
        self.set_theme("dark")

    def set_theme(self, theme: str):
        self.dark = theme != "light"
        if self.dark:
            self.bg = QColor("#262a33")
            self.bg_hover = QColor("#303644")
            self.bg_selected = QColor("#2f6feb")
            self.text = QColor("#e8edf5")
            self.text_secondary = QColor("#9fb2c8")
            self.text_muted = QColor("#7d8798")
            self.border = QColor("#3a3f4b")
            self.text_selected = QColor("#ffffff")
        else:
            self.bg = QColor("#ffffff")
            self.bg_hover = QColor("#eef3fb")
            self.bg_selected = QColor("#2f6feb")
            self.text = QColor("#20232a")
            self.text_secondary = QColor("#5b6b80")
            self.text_muted = QColor("#8a94a3")
            self.border = QColor("#d5dbe5")
            self.text_selected = QColor("#ffffff")

    def _fonts(self, base: QFont) -> tuple[QFont, QFont, QFont]:
        primary = QFont(base)
        primary.setPointSizeF(LEGEND_PRIMARY_PT)
        secondary = QFont(base)
        secondary.setPointSizeF(LEGEND_SECONDARY_PT)
        count = QFont(base)
        count.setPointSizeF(LEGEND_COUNT_PT)
        count.setBold(True)
        return primary, secondary, count

    def row_height(self, base: QFont) -> int:
        primary, secondary, _count = self._fonts(base)
        return max(
            48,
            QFontMetrics(primary).height() + QFontMetrics(secondary).height() + LEGEND_PADDING_Y * 2 + 4,
        )

    def compact_height(self, base: QFont) -> int:
        return max(32, QFontMetrics(base).height() + 12)

    def _item_height(self, base: QFont, payload: dict) -> int:
        return self.row_height(base) if payload.get("secondary") else self.compact_height(base)

    def sizeHint(self, option, index):
        payload = index.data(LEGEND_DATA_ROLE) or {}
        view = self.parent()
        if isinstance(view, QListView) and view.viewMode() == QListView.IconMode:
            grid = view.gridSize()
            if grid.isValid() and grid.height() > 0:
                return grid
            return QSize(260, self._item_height(option.font, payload))
        return QSize(max(180, option.rect.width()), self._item_height(option.font, payload))

    def paint(self, painter: QPainter, option, index):
        payload = index.data(LEGEND_DATA_ROLE)
        if not isinstance(payload, dict):
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        view = self.parent()
        icon_mode = isinstance(view, QListView) and view.viewMode() == QListView.IconMode
        margin = 3 if icon_mode else 1
        rect = QRect(option.rect).adjusted(margin, margin, -margin, -margin)
        if rect.width() <= 8 or rect.height() <= 8:
            painter.restore()
            return

        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        background = self.bg_selected if selected else (self.bg_hover if hovered else self.bg)
        painter.setPen(Qt.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 5, 5)

        primary_font, secondary_font, count_font = self._fonts(option.font)
        fm_primary = QFontMetrics(primary_font)
        fm_secondary = QFontMetrics(secondary_font)
        fm_count = QFontMetrics(count_font)

        swatch_size = max(18, min(LEGEND_SWATCH_SIZE, rect.height() - LEGEND_PADDING_Y * 2))
        swatch = QRect(
            rect.left() + LEGEND_PADDING_X,
            rect.top() + (rect.height() - swatch_size) // 2,
            swatch_size,
            swatch_size,
        )
        self._draw_swatch(painter, swatch, payload)

        used = bool(payload.get("used", True))
        text_left = swatch.right() + 10
        count_text = str(payload.get("count_text") or "")
        count_width = fm_count.horizontalAdvance(count_text) if count_text else 0
        count_left = rect.right() - LEGEND_PADDING_X - count_width
        text_right = count_left - 8 if count_width else rect.right() - LEGEND_PADDING_X
        if text_right - text_left < 36:
            count_width = 0
            text_right = rect.right() - LEGEND_PADDING_X
        text_width = max(12, text_right - text_left)

        primary_text = fm_primary.elidedText(str(payload.get("primary") or ""), Qt.ElideRight, text_width)
        secondary_text = ""
        secondary = str(payload.get("secondary") or "")
        if secondary:
            secondary_text = fm_secondary.elidedText(secondary, Qt.ElideRight, text_width)

        if secondary_text:
            content_height = fm_primary.height() + 3 + fm_secondary.height()
            top = rect.top() + (rect.height() - content_height) // 2
            primary_baseline = top + fm_primary.ascent()
            secondary_baseline = top + fm_primary.height() + 3 + fm_secondary.ascent()
        else:
            top = rect.top() + (rect.height() - fm_primary.height()) // 2
            primary_baseline = top + fm_primary.ascent()
            secondary_baseline = 0

        primary_color = self.text_selected if selected else (self.text if used else self.text_secondary)
        secondary_color = self.text_selected if selected else self.text_secondary
        if not used and not selected:
            secondary_color = self.text_muted

        painter.setFont(primary_font)
        painter.setPen(primary_color)
        painter.drawText(text_left, primary_baseline, primary_text)

        if secondary_text:
            painter.setFont(secondary_font)
            painter.setPen(secondary_color)
            painter.drawText(text_left, secondary_baseline, secondary_text)

        if count_text and count_width:
            count_color = self.text_selected if selected else (self.text if used else self.text_muted)
            painter.setFont(count_font)
            painter.setPen(count_color)
            painter.drawText(
                QRect(count_left, top, count_width, fm_primary.height()),
                Qt.AlignRight | Qt.AlignVCenter,
                count_text,
            )

        painter.restore()

    def _draw_swatch(self, painter: QPainter, rect: QRect, payload: dict):
        texture_path = str(payload.get("thumbnail_path") or "")
        texture = self._texture(texture_path, rect.size())
        if texture is not None:
            painter.save()
            painter.setClipRect(rect)
            painter.drawPixmap(rect, texture)
            painter.restore()
            painter.setBrush(Qt.NoBrush)
            painter.setPen(self.border)
            painter.drawRoundedRect(rect, 3, 3)
            if payload.get("special"):
                dot = QRect(rect.right() - 7, rect.top() + 2, 6, 6)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor("#ef6c00"))
                painter.drawEllipse(dot)
            return
        transparent = bool(payload.get("transparent"))
        if transparent:
            half_w = rect.width() // 2
            half_h = rect.height() // 2
            painter.fillRect(rect, QColor("#cfcfcf"))
            painter.fillRect(QRect(rect.left(), rect.top(), half_w, half_h), QColor("#f2f2f2"))
            painter.fillRect(
                QRect(rect.left() + half_w, rect.top() + half_h, half_w, half_h),
                QColor("#f2f2f2"),
            )
        rgb = payload.get("rgb")
        if rgb:
            painter.setOpacity(0.55 if transparent else 1.0)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(*rgb))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)
            painter.setOpacity(1.0)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(self.border)
        painter.drawRoundedRect(rect, 3, 3)
        if payload.get("special"):
            dot = QRect(rect.right() - 7, rect.top() + 2, 6, 6)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#ef6c00"))
            painter.drawEllipse(dot)

    def _texture(self, path: str, size: QSize):
        if not path or not Path(path).is_file():
            return None
        key = (path, size.width(), size.height())
        cached = self._texture_cache.get(key)
        if cached is not None:
            return cached
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return None
        scaled = pixmap.scaled(
            size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        if len(self._texture_cache) >= 128:
            self._texture_cache.clear()
        self._texture_cache[key] = scaled
        return scaled


class MainWindow(QMainWindow):
    """ 三模式像素艺术创作工作台 """

    def __init__(self):
        super().__init__()
        self.settings = QSettings("Moge", "Moge2")
        self.original_img = None
        self.source_path = None
        self.mode = "pixel"
        self.mode_settings = {mode: registry.default_settings(mode) for mode, _ in registry.mode_options()}
        for mode_key, settings in self.mode_settings.items():
            default_board = 29 if mode_key == "beads" else 16
            settings.setdefault("board_width", default_board)
            settings.setdefault("board_height", default_board)
            settings.setdefault("view", {"view_mode": "preview"})
        self.results = {}
        self.documents = {}
        self.interaction_mode = "view"
        self.preview_style = "solid"
        self.selection_anchor = None
        self.bead_catalog, self.bead_palette_meta = self._load_bead_palette()
        self.bead_inventory_map = {}
        self.mc_texture_overrides = {}
        self.mc_texture_pack_name = ""
        self._palette_building = False
        self._bead_display_syncing = False
        self.bead_view_mode = "preview"
        self.selected_entry = 0
        self.tool = "paint"
        self._stroke_pending = False
        self._task_counter = 0
        self._active_task = None
        self._thread = None
        self._worker = None
        self._busy_actions = []
        self._theme = str(self.settings.value("theme", "dark"))
        self._icon_cache = {}
        self._side_timer = QTimer(self)
        self._side_timer.setSingleShot(True)
        self._side_timer.setInterval(120)
        self._side_timer.timeout.connect(self._flush_side_panels)
        self._palette_timer = QTimer(self)
        self._palette_timer.setSingleShot(True)
        self._palette_timer.setInterval(150)
        self._palette_timer.timeout.connect(self._refresh_palette)
        self._legend_layout_timer = QTimer(self)
        self._legend_layout_timer.setSingleShot(True)
        self._legend_layout_timer.setInterval(80)
        self._legend_layout_timer.timeout.connect(self._apply_legend_layout)

        self._build_ui()
        self._build_actions()
        self._connect_signals()
        self._refresh_mc_versions()
        self._restore_window_state()
        self._set_busy(False)
        self._refresh_palette()
        self._refresh_stats()
        self._update_status()
        self._show_welcome()

    @staticmethod
    def _load_bead_palette():
        """ 优先读取 SQLite 色卡库，缺失时回退内置近似色卡 """
        try:
            catalog, meta = load_catalog_with_meta()
        except Exception:
            logger.warning("读取拼豆色卡数据库失败，回退内置色卡", exc_info=True)
            return list(BEAD_CATALOG), {}
        return (catalog or list(BEAD_CATALOG)), meta

    # ---------- UI ---------- #
    def _build_ui(self):
        self.setWindowTitle("墨格 Moge 2.0 - 像素艺术工作台")
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(1200, max(920, int(available.width() * 0.9)))
            height = min(800, max(560, int(available.height() * 0.9)))
        else:
            width, height = 1200, 800
        self.setGeometry(100, 100, width, height)
        self.setMinimumSize(820, 560)
        self.setAcceptDrops(True)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(6, 6, 6, 6)

        self.splitter = QSplitter(Qt.Horizontal)

        # 左侧：共享网格 + 模式参数
        left_content = QWidget()
        left_layout = QVBoxLayout(left_content)

        grid_group = QGroupBox("基础设置")
        grid_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        grid_form = QFormLayout(grid_group)
        grid_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.grid_width = QSpinBox()
        self.grid_width.setRange(4, 256)
        self.grid_width.setValue(64)
        self.grid_height = QSpinBox()
        self.grid_height.setRange(4, 256)
        self.grid_height.setValue(48)
        grid_form.addRow("网格宽:", self.grid_width)
        grid_form.addRow("网格高:", self.grid_height)
        left_layout.addWidget(grid_group)

        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self._build_pixel_panel())
        self.mode_stack.addWidget(self._build_minecraft_panel())
        self.mode_stack.addWidget(self._build_beads_panel())
        self._configure_form_controls()
        left_layout.addWidget(self.mode_stack, 1)

        self.view_panel = self._build_view_panel()
        left_layout.addWidget(self.view_panel)

        self.btn_apply = QPushButton("执行处理")
        self.btn_apply.setShortcut(QKeySequence("Ctrl+Return"))
        left_layout.addWidget(self.btn_apply)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setWidget(left_content)
        left_scroll.setMinimumWidth(300)
        left_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.left_scroll = left_scroll
        self.left_content = left_content
        self.splitter.addWidget(left_scroll)

        # 中央：欢迎页 / 画布 / 图例统计页
        self.center_stack = QStackedWidget()
        self.welcome = self._build_welcome()
        self.canvas = GridCanvas()
        self.canvas.setMinimumWidth(280)
        self.legend_page = QTextBrowser()
        self.legend_page.setLineWrapMode(QTextBrowser.WidgetWidth)
        self.center_stack.addWidget(self.welcome)
        self.center_stack.addWidget(self.canvas)
        self.center_stack.addWidget(self.legend_page)
        self.center_stack.setCurrentWidget(self.welcome)
        self.splitter.addWidget(self.center_stack)

        # 右侧：图例 + 统计
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self._build_palette_tab(), "图例")
        self.stats_view = QTextBrowser()
        self.stats_view.setLineWrapMode(QTextBrowser.WidgetWidth)
        self.stats_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.right_tabs.addTab(self.stats_view, "统计")
        self.right_tabs.setMinimumWidth(220)
        self.splitter.addWidget(self.right_tabs)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(2, False)
        self.splitter.setSizes([300, 760, 260])
        self.splitter.splitterMoved.connect(lambda *_args: self._legend_layout_timer.start())
        outer.addWidget(self.splitter)

        # 状态栏
        status = self.statusBar()
        self.lbl_status = QLabel("就绪")
        self.lbl_source = QLabel("源图 -")
        self.lbl_grid = QLabel("网格 -")
        self.lbl_colors = QLabel("颜色 -")
        self.lbl_zoom = QLabel("缩放 -")
        self.lbl_preview = QLabel("预览：纯色")
        self.lbl_view = QLabel("视图：成品预览")
        self.lbl_hover = QLabel("")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedWidth(150)
        self.progress.setVisible(False)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setVisible(False)

        status.addWidget(self.lbl_status, 1)
        for widget in (self.lbl_hover, self.lbl_view, self.lbl_preview, self.lbl_source, self.lbl_grid, self.lbl_colors, self.lbl_zoom):
            status.addPermanentWidget(widget)
        status.addPermanentWidget(self.progress)
        status.addPermanentWidget(self.btn_cancel)

    def _build_welcome(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        title = QLabel("墨格 Moge 2.0")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 30px; font-weight: bold; color: #6d9bff;")
        subtitle = QLabel("像素艺术 / Minecraft 方块画 / 拼豆图纸")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 14px; color: #9fb2c8;")
        hint = QLabel("尚未打开图片。可以打开本地图片、恢复工程，或使用内置示例图库。")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(18)
        layout.addWidget(hint)
        layout.addSpacing(18)
        self.btn_welcome_open = QPushButton("打开图片")
        self.btn_welcome_project = QPushButton("打开工程")
        self.btn_welcome_samples = QPushButton("使用示例图片")
        for button in (self.btn_welcome_open, self.btn_welcome_project, self.btn_welcome_samples):
            button.setFixedWidth(240)
            button.setMinimumHeight(38)
            layout.addWidget(button, 0, Qt.AlignHCenter)
            layout.addSpacing(8)
        layout.addStretch(1)
        self.btn_welcome_open.clicked.connect(lambda: self.open_image())
        self.btn_welcome_project.clicked.connect(self.open_project)
        self.btn_welcome_samples.clicked.connect(self.open_sample_library)
        return page

    def _show_welcome(self):
        if hasattr(self, "center_stack"):
            self.center_stack.setCurrentWidget(self.welcome)


    def _build_palette_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        base_font = QFont(self.font())
        search_font = QFont(base_font)
        search_font.setPointSizeF(LEGEND_PRIMARY_PT)
        combo_font = QFont(base_font)
        combo_font.setPointSizeF(LEGEND_SECONDARY_PT + 0.5)
        note_font = QFont(base_font)
        note_font.setPointSizeF(LEGEND_SECONDARY_PT)

        self.palette_search = QLineEdit()
        self.palette_search.setPlaceholderText("搜索颜色 / 方块 / 色号")
        self.palette_search.setClearButtonEnabled(True)
        self.palette_search.setFont(search_font)
        layout.addWidget(self.palette_search)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        self.palette_sort = QComboBox()
        self.palette_sort.setFont(combo_font)
        self.palette_sort.addItem("用量（多→少）", "count")
        self.palette_sort.addItem("色号（A→Z / 1→9）", "code")
        self.palette_sort.addItem("色相（红→紫）", "hue")
        self.palette_sort.addItem("明度（深→浅）", "luminance")
        self.palette_sort.addItem("名称（A→Z）", "name")
        self.palette_sort.setToolTip(
            "用量：数量降序，未用颜色按色号；色号：自然排序（A2 在 A10 前）；"
            "色相：红→紫，同色相按饱和度；明度：深→浅；名称：不区分大小写"
        )
        self.palette_scope = QComboBox()
        self.palette_scope.setFont(combo_font)
        self.palette_scope.addItem("已用颜色", "used")
        self.palette_scope.addItem("全部颜色", "all")
        self.palette_used_only = QCheckBox("仅已用")
        self.palette_used_only.setChecked(True)
        self.palette_used_only.setVisible(False)
        filter_row.addWidget(self.palette_sort, 1)
        filter_row.addWidget(self.palette_scope)
        layout.addLayout(filter_row)

        self.palette_note = QLabel("")
        self.palette_note.setWordWrap(True)
        self.palette_note.setFont(note_font)
        layout.addWidget(self.palette_note)

        self.palette_list = QListWidget()
        list_font = QFont(base_font)
        list_font.setPointSizeF(LEGEND_PRIMARY_PT)
        self.palette_list.setFont(list_font)
        self.palette_list.setIconSize(QSize(LEGEND_SWATCH_SIZE, LEGEND_SWATCH_SIZE))
        self.palette_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.palette_list.setTextElideMode(Qt.ElideRight)
        self.palette_list.setUniformItemSizes(False)
        self.palette_list.setWordWrap(False)
        self.palette_list.setSpacing(2)
        self.palette_list.setMouseTracking(True)
        self.palette_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.palette_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.palette_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.palette_list.setResizeMode(QListView.Adjust)
        self.palette_list.setMovement(QListView.Static)
        self.palette_list.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.palette_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._legend_delegate = LegendItemDelegate(self.palette_list)
        self.palette_list.setItemDelegate(self._legend_delegate)
        layout.addWidget(self.palette_list, 1)

        self.btn_export_legend = QPushButton("导出图例 PNG...")
        self.btn_export_legend.setToolTip("导出当前搜索、范围与排序下的图例为高分辨率 PNG")
        self.btn_export_legend.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.btn_export_legend)
        self._apply_legend_theme()
        return tab

    def _apply_legend_theme(self):
        """ 图例面板跟随深/浅主题，保持文本层级与对比度 """
        delegate = getattr(self, "_legend_delegate", None)
        if delegate is not None:
            delegate.set_theme(self._theme)
        note = getattr(self, "palette_note", None)
        if note is not None:
            color = "#9fb2c8" if self._theme != "light" else "#5b6b80"
            note.setStyleSheet(f"color: {color};")
        palette_list = getattr(self, "palette_list", None)
        if palette_list is not None:
            palette_list.viewport().update()

    def _configure_form_controls(self):
        """ 统一收缩输入控件的最小宽度，避免窄侧栏被长选项文本撑破 """
        for child in self.mode_stack.findChildren(QWidget):
            if isinstance(child, (QComboBox, QSpinBox, QDoubleSpinBox)):
                child.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                child.setMinimumWidth(60)
            if isinstance(child, QComboBox):
                child.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                child.setMinimumContentsLength(6)

    def _build_pixel_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        mode_group = QGroupBox("模式设置")
        mode_form = QFormLayout(mode_group)
        mode_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.px_sampling = QComboBox()
        for key, label in pixel_mode.SAMPLING_OPTIONS:
            self.px_sampling.addItem(label, key)
        self.px_colors = QSpinBox()
        self.px_colors.setRange(2, 256)
        self.px_colors.setValue(16)
        self.px_preset = QComboBox()
        for key, label in pixel_mode.PRESET_OPTIONS:
            self.px_preset.addItem(label, key)
        mode_form.addRow("采样方式:", self.px_sampling)
        mode_form.addRow("目标颜色数:", self.px_colors)
        mode_form.addRow("效果预设:", self.px_preset)
        layout.addWidget(mode_group)

        advanced_group = QGroupBox("高级参数")
        advanced_form = QFormLayout(advanced_group)
        advanced_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.px_algorithm = QComboBox()
        for key, info in ALGORITHM_INFO.items():
            if key in EXPERIMENTAL_ALGORITHMS:
                continue
            self.px_algorithm.addItem(info.label, key)
        self.px_seed = QSpinBox()
        self.px_seed.setRange(0, 99999)
        self.px_seed.setValue(42)
        self.px_optimize = QCheckBox("清理孤立色块")
        self.px_max_delta = QDoubleSpinBox()
        self.px_max_delta.setRange(0.0, 30.0)
        self.px_max_delta.setSingleStep(0.5)
        self.px_max_delta.setValue(6.0)
        advanced_form.addRow("量化算法:", self.px_algorithm)
        advanced_form.addRow("随机种子:", self.px_seed)
        advanced_form.addRow("", self.px_optimize)
        advanced_form.addRow("合并色差上限:", self.px_max_delta)
        layout.addWidget(advanced_group)

        palette_group = QGroupBox("调色板")
        palette_layout = QVBoxLayout(palette_group)
        self.btn_import_palette = QPushButton("导入调色板 CSV...")
        self.btn_export_palette = QPushButton("导出调色板 CSV...")
        palette_layout.addWidget(self.btn_import_palette)
        palette_layout.addWidget(self.btn_export_palette)
        layout.addWidget(palette_group)

        self.px_algorithm_note = QLabel("算法与预设会被展开为可检查参数；自动选择基于透明规则。")
        self.px_algorithm_note.setWordWrap(True)
        layout.addWidget(self.px_algorithm_note)
        layout.addStretch(1)
        return panel

    def _build_minecraft_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        mode_group = QGroupBox("模式设置")
        mode_layout = QVBoxLayout(mode_group)
        mode_form = QFormLayout()
        mode_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.mc_edition = QComboBox()
        self.mc_edition.addItem("Java 版", "java")
        self.mc_edition.addItem("基岩版", "bedrock")
        self.mc_version = QComboBox()
        for version in MC_VERSIONS:
            self.mc_version.addItem(version, version)
        self.mc_version.setCurrentText("1.20.1")
        self.mc_obtain = QComboBox()
        for key, label in minecraft_mode.OBTAINABILITY_OPTIONS:
            self.mc_obtain.addItem(label, key)
        mode_form.addRow("版本:", self.mc_edition)
        mode_form.addRow("精确版本:", self.mc_version)
        mode_form.addRow("获取条件:", self.mc_obtain)
        mode_layout.addLayout(mode_form)

        mode_layout.addWidget(QLabel("材质类别（不选=全部）"))
        self.mc_categories = QListWidget()
        self.mc_categories.setMaximumHeight(150)
        self.mc_categories.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.mc_categories.setTextElideMode(Qt.ElideRight)
        self.mc_categories.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        for key, label in MC_CATEGORIES.items():
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.mc_categories.addItem(item)
        mode_layout.addWidget(self.mc_categories)
        layout.addWidget(mode_group)

        advanced_group = QGroupBox("高级参数")
        advanced_layout = QVBoxLayout(advanced_group)
        advanced_form = QFormLayout()
        advanced_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.mc_buildable = QCheckBox("仅完整可建造方块")
        self.mc_buildable.setChecked(True)
        self.mc_cost = QComboBox()
        for key, label in minecraft_mode.COST_OPTIONS:
            self.mc_cost.addItem(label, key)
        self.mc_orientation = QComboBox()
        self.mc_orientation.addItem("不限制朝向", "any")
        self.mc_orientation.addItem("无朝向依赖", "none")
        self.mc_orientation.addItem("轴向依赖", "axis")
        self.mc_orientation.addItem("朝向依赖", "facing")
        self.mc_exclude_transparent = QCheckBox("排除透明方块")
        self.mc_exclude_gravity = QCheckBox("排除重力方块")
        self.mc_resource_mode = QComboBox()
        self.mc_resource_mode.addItem("自动（优先真实贴图）", "auto")
        self.mc_resource_mode.addItem("仅真实贴图", "real")
        self.mc_resource_mode.addItem("内置近似色", "approx")
        self.mc_strategy = QComboBox()
        for key, label in minecraft_mode.MATCHING_OPTIONS:
            self.mc_strategy.addItem(label, key)
        advanced_form.addRow("成本偏好:", self.mc_cost)
        advanced_form.addRow("匹配策略:", self.mc_strategy)
        advanced_form.addRow("", self.mc_buildable)
        advanced_form.addRow("朝向:", self.mc_orientation)
        advanced_form.addRow("", self.mc_exclude_transparent)
        advanced_form.addRow("", self.mc_exclude_gravity)
        advanced_form.addRow("资源来源:", self.mc_resource_mode)
        advanced_layout.addLayout(advanced_form)

        self.btn_import_pack = QPushButton("导入资源包 ZIP...")
        self.mc_pack_note = QLabel("未加载用户资源包")
        self.mc_pack_note.setWordWrap(True)
        self.btn_mc_diagnose = QPushButton("筛选诊断")
        self.btn_manage_resources = QPushButton("版本资源管理...")
        advanced_layout.addWidget(self.btn_import_pack)
        advanced_layout.addWidget(self.mc_pack_note)
        advanced_layout.addWidget(self.btn_mc_diagnose)
        advanced_layout.addWidget(self.btn_manage_resources)
        layout.addWidget(advanced_group)

        note = QLabel(minecraft_mode.DISPLAY_NOTE)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return panel

    def _build_beads_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        mode_group = QGroupBox("模式设置")
        form = QFormLayout(mode_group)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.bead_brand = QComboBox()
        self.bead_series = QComboBox()
        self.bead_size = QComboBox()
        self.bead_family = QComboBox()
        self.bead_material = QComboBox()
        self.btn_import_beads = QPushButton("导入色卡 CSV...")
        self.btn_bead_info = QPushButton("色卡详情...")
        self.bead_catalog_note = QLabel("内置近似色卡，未验证")
        self.bead_catalog_note.setWordWrap(True)
        self.bead_source_note = QLabel("")
        self.bead_source_note.setWordWrap(True)
        self.bead_source_note.setVisible(False)
        self.bead_inventory = QLineEdit()
        self.bead_inventory.setPlaceholderText("库存色号，逗号分隔；留空=全部")
        self.bead_disabled = QLineEdit()
        self.bead_disabled.setPlaceholderText("禁用色号，逗号分隔")
        form.addRow("品牌:", self.bead_brand)
        form.addRow("系列:", self.bead_series)
        form.addRow("尺寸:", self.bead_size)
        form.addRow("色系:", self.bead_family)
        form.addRow("材质:", self.bead_material)
        form.addRow("", self.btn_import_beads)
        form.addRow("", self.btn_bead_info)
        form.addRow("", self.bead_catalog_note)
        form.addRow("", self.bead_source_note)
        form.addRow("库存:", self.bead_inventory)
        form.addRow("禁用:", self.bead_disabled)
        layout.addWidget(mode_group)

        advanced_group = QGroupBox("高级参数")
        advanced_form = QFormLayout(advanced_group)
        advanced_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.bead_pack_size = QSpinBox()
        self.bead_pack_size.setRange(1, 100000)
        self.bead_pack_size.setValue(1000)
        self.btn_import_inventory = QPushButton("导入库存 CSV...")
        self.bead_inventory_note = QLabel("未导入库存")
        self.bead_inventory_note.setWordWrap(True)
        advanced_form.addRow("每包数量:", self.bead_pack_size)
        advanced_form.addRow("", self.btn_import_inventory)
        advanced_form.addRow("", self.bead_inventory_note)
        layout.addWidget(advanced_group)

        note = QLabel(beads_mode.DISPLAY_NOTE)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

        self._refresh_bead_catalog_combos()
        return panel

    def _build_view_panel(self) -> QWidget:
        """ 三模式共享的图纸显示设置：坐标、辅助线、标记与分区 """
        display_group = QGroupBox("图纸显示")
        display_layout = QVBoxLayout(display_group)
        display_form = QFormLayout()
        display_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.bead_view_combo = QComboBox()
        self.bead_view_combo.addItem("成品预览", "preview")
        self.bead_view_combo.addItem("施工图", "blueprint")
        self.bead_view_combo.addItem("图例统计", "legend")
        self.bead_view_combo.addItem("黑白打印", "mono")
        self.bead_cell_mode = QComboBox()
        self.bead_cell_mode.addItem("纯颜色", "color")
        self.bead_cell_mode.addItem("色号", "code")
        self.bead_cell_mode.addItem("缩写", "abbrev")
        self.bead_cell_mode.addItem("黑白符号", "symbol")
        self.bead_cell_mode.addItem("混合", "mixed")
        self.bead_coord_step = QComboBox()
        self.bead_coord_step.addItem("每格编号", 1)
        self.bead_coord_step.addItem("每 5 格编号", 5)
        self.bead_coord_step.addItem("每 10 格编号", 10)
        self.bead_board_width = QSpinBox()
        self.bead_board_width.setRange(1, 128)
        self.bead_board_width.setValue(29)
        self.bead_board_width.setToolTip("分区宽度；Minecraft 常用 16 或 32")
        self.bead_board_height = QSpinBox()
        self.bead_board_height.setRange(1, 128)
        self.bead_board_height.setValue(29)
        self.bead_board_height.setToolTip("分区高度；Minecraft 常用 16 或 32")
        display_form.addRow("视图:", self.bead_view_combo)
        display_form.addRow("格内显示:", self.bead_cell_mode)
        display_form.addRow("坐标数字:", self.bead_coord_step)
        display_form.addRow("分区宽:", self.bead_board_width)
        display_form.addRow("分区高:", self.bead_board_height)
        display_layout.addLayout(display_form)

        self.bead_show_grid = QCheckBox("显示网格")
        self.bead_show_grid.setChecked(True)
        self.bead_show_x = QCheckBox("显示 X 轴")
        self.bead_show_y = QCheckBox("显示 Y 轴")
        self.bead_show_numbers = QCheckBox("显示坐标数字")
        self.bead_guide5 = QCheckBox("5 格辅助线")
        self.bead_guide10 = QCheckBox("10 格辅助线")
        self.bead_show_boards = QCheckBox("显示分区")
        self.bead_keep_blank = QCheckBox("保留透明空白格")
        self.bead_keep_blank.setChecked(True)
        for row in (
            (self.bead_show_grid, self.bead_show_numbers),
            (self.bead_show_x, self.bead_show_y),
            (self.bead_guide5, self.bead_guide10),
            (self.bead_show_boards, self.bead_keep_blank),
        ):
            row_layout = QHBoxLayout()
            for widget in row:
                row_layout.addWidget(widget)
            display_layout.addLayout(row_layout)

        self.bead_marker_color = QCheckBox("颜色标记")
        self.bead_marker_color.setChecked(True)
        self.bead_marker_code = QCheckBox("编号标记")
        self.bead_marker_symbol = QCheckBox("符号标记")
        marker_row = QHBoxLayout()
        for widget in (self.bead_marker_color, self.bead_marker_code, self.bead_marker_symbol):
            marker_row.addWidget(widget)
        display_layout.addLayout(marker_row)

        preset_row = QHBoxLayout()
        self.btn_bead_preset_preview = QPushButton("成品预览")
        self.btn_bead_preset_blueprint = QPushButton("施工图")
        self.btn_bead_preset_mono = QPushButton("黑白打印")
        for button in (self.btn_bead_preset_preview, self.btn_bead_preset_blueprint, self.btn_bead_preset_mono):
            preset_row.addWidget(button)
        display_layout.addLayout(preset_row)
        for child in display_group.findChildren(QWidget):
            if isinstance(child, (QCheckBox, QPushButton)):
                child.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        for combo in (self.bead_view_combo, self.bead_cell_mode, self.bead_coord_step):
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            combo.setMinimumWidth(60)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
        for spin in (self.bead_board_width, self.bead_board_height):
            spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            spin.setMinimumWidth(60)
        return display_group

    def _build_actions(self):
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.mode_combo = QComboBox()
        for key, label in registry.mode_options():
            self.mode_combo.addItem(label, key)
        toolbar.addWidget(QLabel(" 模式 "))
        toolbar.addWidget(self.mode_combo)
        self.view_combo = QComboBox()
        self.view_combo.addItem("成品预览", "preview")
        self.view_combo.addItem("施工图", "blueprint")
        self.view_combo.addItem("图例统计", "legend")
        self.view_combo.addItem("黑白打印", "mono")
        toolbar.addWidget(QLabel(" 视图 "))
        toolbar.addWidget(self.view_combo)
        toolbar.addSeparator()

        self.act_open = QAction("打开图片", self)
        self.act_open.setShortcut(QKeySequence.Open)
        self.act_open_project = QAction("打开工程", self)
        self.act_save_project = QAction("保存工程", self)
        self.act_save_project.setShortcut(QKeySequence.Save)
        toolbar.addActions([self.act_open, self.act_open_project, self.act_save_project])
        self.act_samples = QAction("示例图库", self)
        toolbar.addAction(self.act_samples)
        toolbar.addSeparator()

        self.act_undo = QAction("撤销", self)
        self.act_undo.setShortcut(QKeySequence.Undo)
        self.act_redo = QAction("重做", self)
        self.act_redo.setShortcut(QKeySequence.Redo)
        toolbar.addActions([self.act_undo, self.act_redo])
        toolbar.addSeparator()

        # 查看/编辑模式切换：查看模式不允许修改网格
        self.mode_group = QActionGroup(self)
        self.mode_group.setExclusive(True)
        self.act_view_mode = QAction("查看模式", self)
        self.act_view_mode.setCheckable(True)
        self.act_view_mode.setChecked(True)
        self.act_edit_mode = QAction("编辑模式", self)
        self.act_edit_mode.setCheckable(True)
        self.act_edit_mode.setShortcut(QKeySequence("Ctrl+E"))
        for action, key in ((self.act_view_mode, "view"), (self.act_edit_mode, "edit")):
            action.setData(key)
            self.mode_group.addAction(action)
            toolbar.addAction(action)
        toolbar.addSeparator()

        self.preview_group = QActionGroup(self)
        self.preview_group.setExclusive(True)
        self.act_preview_solid = QAction("纯色预览", self)
        self.act_preview_solid.setCheckable(True)
        self.act_preview_solid.setChecked(True)
        self.act_preview_texture = QAction("真实纹理预览", self)
        self.act_preview_texture.setCheckable(True)
        for action, key in ((self.act_preview_solid, "solid"), (self.act_preview_texture, "texture")):
            action.setData(key)
            self.preview_group.addAction(action)
            toolbar.addAction(action)
        toolbar.addSeparator()

        self.act_fit = QAction("适应窗口", self)
        self.act_fit.setShortcut(QKeySequence("F"))
        self.act_grid = QAction("显示网格", self)
        self.act_grid.setCheckable(True)
        self.act_grid.setChecked(True)
        self.act_grid.setShortcut(QKeySequence("Ctrl+G"))
        self.act_theme = QAction("切换主题", self)
        self.act_compare = QAction("对比原图", self)
        self.act_compare.setCheckable(True)
        self.act_compare.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self.act_compare.setEnabled(False)
        self.act_reset_view = QAction("重置视图", self)
        self.act_reset_view.setShortcut(QKeySequence("Ctrl+0"))
        self.act_locate = QAction("定位坐标...", self)
        self.act_locate.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self.act_sidebar = QAction("显示侧栏", self)
        self.act_sidebar.setCheckable(True)
        self.act_sidebar.setChecked(True)
        self.act_sidebar.setShortcut(QKeySequence("Ctrl+B"))
        toolbar.addActions([
            self.act_fit, self.act_reset_view, self.act_compare, self.act_grid, self.act_theme, self.act_sidebar,
        ])

        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(self.act_open)
        file_menu.addAction(self.act_open_project)
        file_menu.addAction(self.act_save_project)
        file_menu.addAction(self.act_samples)
        self.act_export_png = QAction("导出 PNG...", self)
        self.act_export_csv = QAction("导出材料 CSV...", self)
        self.act_export_pdf = QAction("导出图纸 PDF...", self)
        self.act_export_preview_png = QAction("导出成品预览 PNG...", self)
        self.act_export_blueprint_png = QAction("导出施工图 PNG...", self)
        self.act_export_mono_png = QAction("导出黑白符号 PNG...", self)
        self.act_export_partitions = QAction("导出分区 PNG...", self)
        file_menu.addSeparator()
        file_menu.addActions([self.act_export_png, self.act_export_csv, self.act_export_pdf])
        file_menu.addSeparator()
        file_menu.addActions([
            self.act_export_preview_png, self.act_export_blueprint_png,
            self.act_export_mono_png, self.act_export_partitions,
        ])
        file_menu.addSeparator()
        act_quit = QAction("退出", self)
        act_quit.setShortcut(QKeySequence.Quit)
        file_menu.addAction(act_quit)

        edit_menu = self.menuBar().addMenu("编辑")
        edit_menu.addActions([self.act_undo, self.act_redo])
        edit_menu.addSeparator()
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_actions = {}
        for key, label, shortcut in (
            ("paint", "画笔", "B"),
            ("fill", "填充", "G"),
            ("pick", "吸管", "I"),
            ("erase", "橡皮擦", "E"),
            ("replace", "替换同类", "R"),
            ("select", "矩形框选", "S"),
            ("lock", "区域锁定", "L"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setShortcut(QKeySequence(shortcut))
            action.setData(key)
            self.tool_group.addAction(action)
            edit_menu.addAction(action)
            self.tool_actions[key] = action
        self.tool_actions["paint"].setChecked(True)

        edit_menu.addSeparator()
        self.act_lock_selection = QAction("锁定/解锁选区", self)
        self.act_lock_selection.setShortcut(QKeySequence("Ctrl+L"))
        self.act_clear_selection = QAction("清除选区", self)
        self.act_clear_selection.setShortcut(QKeySequence("Esc"))
        edit_menu.addActions([self.act_lock_selection, self.act_clear_selection])

        view_menu = self.menuBar().addMenu("视图")
        view_menu.addActions([
            self.act_fit, self.act_reset_view, self.act_compare, self.act_grid, self.act_sidebar, self.act_theme,
        ])
        view_menu.addSeparator()
        self.act_preset_preview = QAction("拼豆：成品预览", self)
        self.act_preset_blueprint = QAction("拼豆：施工图", self)
        self.act_preset_mono = QAction("拼豆：黑白打印", self)
        self.act_preset_legend = QAction("拼豆：图例统计", self)
        view_menu.addActions([
            self.act_preset_preview, self.act_preset_blueprint, self.act_preset_mono, self.act_preset_legend,
        ])

        help_menu = self.menuBar().addMenu("帮助")
        act_about = QAction("关于 Moge", self)
        help_menu.addAction(act_about)

        self._busy_actions = [
            self.act_open,
            self.act_open_project,
            self.act_save_project,
            self.act_export_png,
            self.act_export_csv,
            self.act_export_pdf,
            self.act_export_preview_png,
            self.act_export_blueprint_png,
            self.act_export_mono_png,
            self.act_export_partitions,
            self.btn_apply,
            self.mode_combo,
            self.view_combo,
        ]

        self._connect_action(self.act_open, lambda: self.open_image())
        self._connect_action(self.act_samples, self.open_sample_library)
        self._connect_action(self.act_open_project, self.open_project)
        self._connect_action(self.act_save_project, self.save_project)
        self._connect_action(self.act_export_png, self.export_png_file)
        self._connect_action(self.act_export_csv, self.export_csv_file)
        self._connect_action(self.act_export_pdf, self.export_pdf_file)
        self._connect_action(self.act_export_preview_png, lambda: self.export_bead_png_file("preview"))
        self._connect_action(self.act_export_blueprint_png, lambda: self.export_bead_png_file("blueprint"))
        self._connect_action(self.act_export_mono_png, lambda: self.export_bead_png_file("mono"))
        self._connect_action(self.act_export_partitions, self.export_partition_pngs_file)
        self._connect_action(self.act_preset_preview, lambda: self._apply_bead_preset("preview"))
        self._connect_action(self.act_preset_blueprint, lambda: self._apply_bead_preset("blueprint"))
        self._connect_action(self.act_preset_mono, lambda: self._apply_bead_preset("mono"))
        self._connect_action(self.act_preset_legend, lambda: self._apply_bead_preset("legend"))
        self._connect_action(self.act_undo, self.undo)
        self._connect_action(self.act_redo, self.redo)
        self.mode_group.triggered.connect(self._on_interaction_mode_changed)
        self.preview_group.triggered.connect(self._on_preview_style_changed)
        self._connect_action(self.act_lock_selection, self.toggle_selection_lock)
        self._connect_action(self.act_clear_selection, self.clear_selection)
        self._connect_action(self.act_fit, self.canvas_fit)
        self._connect_action(self.act_reset_view, self.canvas.reset_view)
        self._connect_action(self.act_locate, self.locate_cell)
        self._connect_action(self.act_theme, self.toggle_theme)
        self._connect_action(act_quit, self.close)
        self._connect_action(act_about, self.show_about)
        self.act_grid.toggled.connect(self.canvas.set_grid_visible)
        self.act_compare.toggled.connect(self.canvas.set_compare_enabled)
        self.act_sidebar.toggled.connect(self._set_sidebar_visible)
        self.tool_group.triggered.connect(self._on_tool_changed)
        self.btn_import_beads.clicked.connect(self.import_bead_catalog)
        self.btn_bead_info.clicked.connect(self.show_bead_info)
        self.btn_import_pack.clicked.connect(self.import_minecraft_pack)
        self.btn_import_inventory.clicked.connect(self.import_bead_inventory)
        self.btn_import_palette.clicked.connect(self.import_pixel_palette)
        self.btn_export_palette.clicked.connect(self.export_pixel_palette)
        self.btn_mc_diagnose.clicked.connect(self.show_mc_diagnostics)
        self.btn_manage_resources.clicked.connect(self.open_resource_manager)
        self.mc_edition.currentIndexChanged.connect(lambda _index: self._refresh_mc_versions())
        self.btn_cancel.clicked.connect(self.cancel_task)
        self.btn_export_legend.clicked.connect(self.export_legend_png_file)
        self.btn_bead_preset_preview.clicked.connect(lambda: self._apply_bead_preset("preview"))
        self.btn_bead_preset_blueprint.clicked.connect(lambda: self._apply_bead_preset("blueprint"))
        self.btn_bead_preset_mono.clicked.connect(lambda: self._apply_bead_preset("mono"))
        self.view_combo.currentIndexChanged.connect(self._on_view_combo_changed)

    def _connect_action(self, action, function):
        action.triggered.connect(lambda checked=False: function())

    def _connect_signals(self):
        self.mode_combo.currentIndexChanged.connect(self._on_mode_combo)
        self.canvas.strokeStarted.connect(self._on_stroke_started)
        self.canvas.strokeFinished.connect(self._flush_side_panels)
        self.canvas.cellPressed.connect(self._on_cell_pressed)
        self.canvas.cellDragged.connect(self._on_cell_dragged)
        self.canvas.hoverCellChanged.connect(self._on_hover)
        self.canvas.zoomChanged.connect(self._on_zoom)
        self.canvas.cellInspected.connect(self._on_cell_inspected)
        self.palette_list.currentRowChanged.connect(self._on_palette_selected)
        self.palette_list.customContextMenuRequested.connect(self._show_palette_context_menu)
        self.palette_search.textChanged.connect(lambda _text: self._palette_timer.start())
        self.palette_sort.currentIndexChanged.connect(lambda _index: self._refresh_palette())
        self.palette_scope.currentIndexChanged.connect(self._on_palette_scope_changed)
        self.palette_used_only.toggled.connect(self._on_palette_used_only_toggled)
        self.right_tabs.currentChanged.connect(lambda _index: self._legend_layout_timer.start())
        self.mc_edition.currentIndexChanged.connect(self._on_mc_context_changed)
        self.mc_version.currentIndexChanged.connect(self._on_mc_context_changed)
        self.mc_obtain.currentIndexChanged.connect(self._on_mc_context_changed)
        self.mc_buildable.toggled.connect(self._on_mc_context_changed)
        self.mc_orientation.currentIndexChanged.connect(self._on_mc_context_changed)
        self.mc_exclude_transparent.toggled.connect(self._on_mc_context_changed)
        self.mc_exclude_gravity.toggled.connect(self._on_mc_context_changed)
        self.mc_resource_mode.currentIndexChanged.connect(self._on_mc_context_changed)
        self.mc_strategy.currentIndexChanged.connect(self._on_mc_context_changed)
        self.mc_categories.itemChanged.connect(self._on_mc_context_changed)
        self.bead_brand.currentIndexChanged.connect(self._on_bead_brand_changed)
        self.bead_series.currentIndexChanged.connect(self._on_bead_series_changed)
        self.bead_inventory.textEdited.connect(lambda _text: self.bead_inventory_map.clear())
        for widget in (
            self.bead_show_grid,
            self.bead_show_x,
            self.bead_show_y,
            self.bead_show_numbers,
            self.bead_guide5,
            self.bead_guide10,
            self.bead_show_boards,
            self.bead_keep_blank,
            self.bead_marker_color,
            self.bead_marker_code,
            self.bead_marker_symbol,
        ):
            widget.toggled.connect(self._on_bead_display_changed)
        for combo in (self.bead_view_combo, self.bead_cell_mode, self.bead_coord_step):
            combo.currentIndexChanged.connect(self._on_bead_display_changed)
        self.bead_board_width.valueChanged.connect(self._on_board_size_changed)
        self.bead_board_height.valueChanged.connect(self._on_board_size_changed)
        self.grid_width.valueChanged.connect(lambda _value: self._update_status())
        self.grid_height.valueChanged.connect(lambda _value: self._update_status())
        self.btn_apply.clicked.connect(self.apply_processing)

    # ---------- 状态与模式 ---------- #
    def _current_result(self):
        return self.results.get(self.mode)

    def _on_mode_combo(self, index):
        if index < 0 or self._thread is not None:
            return
        self.mode_settings[self.mode] = self._collect_settings(self.mode)
        self.mode = self.mode_combo.itemData(index)
        self.mode_stack.setCurrentIndex(index)
        self.palette_used_only.blockSignals(True)
        self.palette_used_only.setChecked(True)
        self.palette_used_only.blockSignals(False)
        self._sync_palette_scope()
        self._apply_settings_to_panels(self.mode, self.mode_settings[self.mode])
        self.selection_anchor = None
        self._stroke_pending = False
        result = self.results.get(self.mode)
        if result is not None:
            self._display_result(result)
        elif self.original_img is not None:
            self._display_source()
        else:
            self.canvas.set_image(None)
        self.canvas.set_interaction_mode(self.interaction_mode)
        self._sync_view_controls(self.bead_view_combo.currentData() or "preview")
        self._on_bead_display_changed()
        self._refresh_palette()
        self._refresh_stats()
        self._update_status()
        self._update_action_states()
        self.lbl_status.setText(f"已切换到 {registry.mode_label(self.mode)}")

    # ---------- 拼豆视图与施工图显示 ---------- #
    VIEW_LABELS = {
        "preview": "成品预览",
        "blueprint": "施工图",
        "legend": "图例统计",
        "mono": "黑白打印",
    }

    def _bead_display_options(self) -> dict:
        view = self.bead_view_combo.currentData() or "preview"
        self.bead_view_mode = view
        return {
            "view_mode": "blueprint" if view == "legend" else view,
            "axis_x": self.bead_show_x.isChecked(),
            "axis_y": self.bead_show_y.isChecked(),
            "coordinate_numbers": self.bead_show_numbers.isChecked(),
            "coordinate_step": int(self.bead_coord_step.currentData() or 1),
            "grid": self.bead_show_grid.isChecked(),
            "guide5": self.bead_guide5.isChecked(),
            "guide10": self.bead_guide10.isChecked(),
            "board_partitions": self.bead_show_boards.isChecked(),
            "board_width": self.bead_board_width.value(),
            "board_height": self.bead_board_height.value(),
            "cell_mode": self.bead_cell_mode.currentData() or "color",
            "marker_color": self.bead_marker_color.isChecked(),
            "marker_code": self.bead_marker_code.isChecked(),
            "marker_symbol": self.bead_marker_symbol.isChecked(),
        }

    def _sync_view_controls(self, view: str):
        view = view if view in self.VIEW_LABELS else "preview"
        self._bead_display_syncing = True
        try:
            index = self.bead_view_combo.findData(view)
            if index >= 0:
                self.bead_view_combo.setCurrentIndex(index)
            index = self.view_combo.findData(view)
            if index >= 0:
                self.view_combo.setCurrentIndex(index)
            self.bead_view_mode = view
        finally:
            self._bead_display_syncing = False
        self._update_view_label()

    def _update_view_label(self):
        self.lbl_view.setText(f"视图：{self.VIEW_LABELS.get(self.bead_view_mode, '成品预览')}")

    def _on_view_combo_changed(self, _index=None):
        view = self.view_combo.currentData() or "preview"
        if self._bead_display_syncing:
            return
        self._sync_view_controls(view)
        self._on_bead_display_changed()

    def _on_bead_display_changed(self, *_args):
        if self._bead_display_syncing or not hasattr(self, "canvas"):
            return
        self._bead_display_syncing = True
        try:
            view = self.bead_view_combo.currentData() or "preview"
            self.bead_view_mode = view
            index = self.view_combo.findData(view)
            if index >= 0:
                self.view_combo.blockSignals(True)
                self.view_combo.setCurrentIndex(index)
                self.view_combo.blockSignals(False)
            self.act_grid.blockSignals(True)
            self.act_grid.setChecked(self.bead_show_grid.isChecked())
            self.act_grid.blockSignals(False)
            self.canvas.configure_beads(self._bead_display_options())
            self._update_view_label()
            result = self._current_result()
            if result is not None and view == "legend":
                self._refresh_legend_page(result)
                self.center_stack.setCurrentWidget(self.legend_page)
            elif result is not None or self.original_img is not None:
                self.center_stack.setCurrentWidget(self.canvas)
            else:
                self._show_welcome()
        finally:
            self._bead_display_syncing = False

    def _apply_bead_preset(self, preset: str):
        preset = preset if preset in self.VIEW_LABELS else "preview"
        values = {
            "preview": {
                "grid": False, "axis_x": False, "axis_y": False, "numbers": False,
                "guide5": False, "guide10": False, "boards": False, "cell": "color",
                "marker_color": True, "marker_code": False, "marker_symbol": False, "step": 1,
            },
            "blueprint": {
                "grid": True, "axis_x": True, "axis_y": True, "numbers": True,
                "guide5": True, "guide10": True, "boards": True, "cell": "code",
                "marker_color": True, "marker_code": True, "marker_symbol": False, "step": 1,
            },
            "mono": {
                "grid": True, "axis_x": True, "axis_y": True, "numbers": True,
                "guide5": True, "guide10": True, "boards": True, "cell": "symbol",
                "marker_color": False, "marker_code": False, "marker_symbol": True, "step": 1,
            },
            "legend": {
                "grid": True, "axis_x": True, "axis_y": True, "numbers": True,
                "guide5": True, "guide10": True, "boards": True, "cell": "code",
                "marker_color": True, "marker_code": True, "marker_symbol": False, "step": 1,
            },
        }[preset]
        self._bead_display_syncing = True
        try:
            combo_index = self.bead_view_combo.findData(preset)
            if combo_index >= 0:
                self.bead_view_combo.setCurrentIndex(combo_index)
            self.bead_show_grid.setChecked(values["grid"])
            self.bead_show_x.setChecked(values["axis_x"])
            self.bead_show_y.setChecked(values["axis_y"])
            self.bead_show_numbers.setChecked(values["numbers"])
            self.bead_guide5.setChecked(values["guide5"])
            self.bead_guide10.setChecked(values["guide10"])
            self.bead_show_boards.setChecked(values["boards"])
            self.bead_marker_color.setChecked(values["marker_color"])
            self.bead_marker_code.setChecked(values["marker_code"])
            self.bead_marker_symbol.setChecked(values["marker_symbol"])
            cell_index = self.bead_cell_mode.findData(values["cell"])
            if cell_index >= 0:
                self.bead_cell_mode.setCurrentIndex(cell_index)
            step_index = self.bead_coord_step.findData(values["step"])
            if step_index >= 0:
                self.bead_coord_step.setCurrentIndex(step_index)
            self.bead_view_mode = preset
        finally:
            self._bead_display_syncing = False
        self._sync_view_controls(preset)
        self._on_bead_display_changed()

    def _on_board_size_changed(self, _value=None):
        """ 分区尺寸变化只更新分区显示与统计，不重新量化 """
        settings = self.mode_settings.setdefault(self.mode, {})
        settings["board_width"] = self.bead_board_width.value()
        settings["board_height"] = self.bead_board_height.value()
        self.canvas.configure_beads(
            {"board_width": self.bead_board_width.value(), "board_height": self.bead_board_height.value()}
        )
        result = self._current_result()
        if result is not None and result.mode == "beads":
            result.stats["board_stats"] = board_stats(
                result.grid.labels,
                self.bead_board_width.value(),
                self.bead_board_height.value(),
            )
            result.stats["board_size"] = f"{self.bead_board_width.value()}x{self.bead_board_height.value()}"
            result.stats["boards"] = len(result.stats["board_stats"])
            self._refresh_stats()
            if self.bead_view_mode == "legend":
                self._refresh_legend_page(result)

    # ---------- 模式与参数 ---------- #
    def _collect_settings(self, mode: str) -> dict:
        if mode == "pixel":
            return {
                "sampling": self.px_sampling.currentData(),
                "algorithm": self.px_algorithm.currentData(),
                "colors": self.px_colors.value(),
                "seed": self.px_seed.value(),
                "preset": self.px_preset.currentData(),
                "optimize": self.px_optimize.isChecked(),
                "max_delta": self.px_max_delta.value(),
                "board_width": self.bead_board_width.value(),
                "board_height": self.bead_board_height.value(),
                "keep_blank_cells": self.bead_keep_blank.isChecked(),
                "view": self._bead_display_options(),
            }
        if mode == "minecraft":
            categories = [
                self.mc_categories.item(index).data(Qt.UserRole)
                for index in range(self.mc_categories.count())
                if self.mc_categories.item(index).checkState() == Qt.Checked
            ]
            return {
                "edition": self.mc_edition.currentData(),
                "version": self.mc_version.currentData(),
                "categories": categories,
                "obtainability": self.mc_obtain.currentData(),
                "buildable_only": self.mc_buildable.isChecked(),
                "max_cost_tier": self.mc_cost.currentData(),
                "included_ids": [],
                "excluded_ids": [],
                "orientation": self.mc_orientation.currentData(),
                "exclude_transparent": self.mc_exclude_transparent.isChecked(),
                "exclude_gravity": self.mc_exclude_gravity.isChecked(),
                "resource_mode": self.mc_resource_mode.currentData(),
                "matching_strategy": self.mc_strategy.currentData(),
                "texture_overrides": dict(self.mc_texture_overrides),
                "texture_pack_name": self.mc_texture_pack_name,
                "board_width": self.bead_board_width.value(),
                "board_height": self.bead_board_height.value(),
                "keep_blank_cells": self.bead_keep_blank.isChecked(),
                "view": self._bead_display_options(),
            }
        if self.bead_inventory_map:
            inventory_ids = [item_id for item_id, quantity in self.bead_inventory_map.items() if quantity > 0]
        else:
            inventory_ids = [item.strip() for item in self.bead_inventory.text().split(",") if item.strip()] or None
        return {
            "brand": self.bead_brand.currentData(),
            "series": self.bead_series.currentData(),
            "size_filter": self.bead_size.currentData() or "",
            "family_filter": self.bead_family.currentData() or "",
            "material_filter": self.bead_material.currentData() or "",
            "catalog": list(self.bead_catalog),
            "inventory_ids": inventory_ids,
            "disabled_ids": [item.strip() for item in self.bead_disabled.text().split(",") if item.strip()],
            "board_width": self.bead_board_width.value(),
            "board_height": self.bead_board_height.value(),
            "pack_size": self.bead_pack_size.value(),
            "keep_blank_cells": self.bead_keep_blank.isChecked(),
            "empty_alpha_threshold": 0.5,
            "view": self._bead_display_options(),
        }

    def _apply_settings_to_panels(self, mode: str, settings: dict):
        if mode == "pixel":
            self._set_combo_data(self.px_sampling, settings.get("sampling", "mean"))
            self._set_combo_data(self.px_algorithm, settings.get("algorithm", "kmeans_lab"))
            self.px_colors.setValue(int(settings.get("colors", 16)))
            self._set_combo_data(self.px_preset, settings.get("preset", "custom"))
            self.px_seed.setValue(int(settings.get("seed", 42)))
            self.px_optimize.setChecked(bool(settings.get("optimize", False)))
            self.px_max_delta.setValue(float(settings.get("max_delta", 6.0)))
        elif mode == "minecraft":
            self._set_combo_data(self.mc_edition, settings.get("edition", "java"))
            self._set_combo_data(self.mc_version, settings.get("version", "1.20.1"))
            self._set_combo_data(self.mc_obtain, settings.get("obtainability", "any"))
            self._set_combo_data(self.mc_cost, settings.get("max_cost_tier"))
            self.mc_buildable.setChecked(bool(settings.get("buildable_only", True)))
            selected = set(settings.get("categories") or [])
            for index in range(self.mc_categories.count()):
                item = self.mc_categories.item(index)
                item.setCheckState(Qt.Checked if item.data(Qt.UserRole) in selected else Qt.Unchecked)
            overrides = settings.get("texture_overrides") or {}
            self.mc_texture_overrides = {
                str(block_id): tuple(int(channel) for channel in rgb)
                for block_id, rgb in overrides.items()
            }
            self.mc_texture_pack_name = str(settings.get("texture_pack_name") or "")
            if self.mc_texture_overrides:
                name = self.mc_texture_pack_name or "用户资源包"
                self.mc_pack_note.setText(f"已加载 {name} 的 {len(self.mc_texture_overrides)} 个方块贴图（平均色）")
            else:
                self.mc_pack_note.setText("未加载用户资源包（仅为内置近似色）")
            self._set_combo_data(self.mc_orientation, settings.get("orientation", "any"))
            self.mc_exclude_transparent.setChecked(bool(settings.get("exclude_transparent", False)))
            self.mc_exclude_gravity.setChecked(bool(settings.get("exclude_gravity", False)))
            self._set_combo_data(self.mc_resource_mode, settings.get("resource_mode", "auto"))
            self._set_combo_data(self.mc_strategy, settings.get("matching_strategy", "perceptual"))
        else:
            catalog = settings.get("catalog")
            if catalog:
                converted = []
                for item in catalog:
                    if isinstance(item, BeadColor):
                        converted.append(item)
                    elif isinstance(item, dict):
                        converted.append(
                            BeadColor(
                                brand=str(item["brand"]),
                                series=str(item["series"]),
                                code=str(item["code"]),
                                name=str(item["name"]),
                                rgb=tuple(int(channel) for channel in item["rgb"]),
                                availability=str(item.get("availability", "unknown")),
                                source=str(item.get("source", "project")),
                                revision=str(item.get("revision", "1")),
                                product_line=str(item.get("product_line", "")),
                                verified=bool(item.get("verified", False)),
                                size=str(item.get("size", "")),
                                color_family=str(item.get("color_family", "")),
                                material=str(item.get("material", "solid")),
                                trust=str(item.get("trust", "unknown")),
                                source_url=str(item.get("source_url", "")),
                                license=str(item.get("license", "")),
                            )
                        )
                self.bead_catalog = converted or self.bead_catalog
                self._refresh_bead_catalog_combos()
            self._set_combo_data(self.bead_brand, settings.get("brand"))
            self._on_bead_brand_changed()
            self._set_combo_data(self.bead_series, settings.get("series"))
            self._on_bead_series_changed()
            self._set_combo_data(self.bead_size, settings.get("size_filter", ""))
            self._set_combo_data(self.bead_family, settings.get("family_filter", ""))
            self._set_combo_data(self.bead_material, settings.get("material_filter", ""))
            inventory = settings.get("inventory_ids") or []
            self.bead_inventory.setText(", ".join(item_id.split(":")[-1] for item_id in inventory))
            disabled = settings.get("disabled_ids") or []
            self.bead_disabled.setText(", ".join(disabled))
            self.bead_pack_size.setValue(int(settings.get("pack_size", 1000)))
        self.bead_board_width.blockSignals(True)
        self.bead_board_width.setValue(int(settings.get("board_width", self.bead_board_width.value())))
        self.bead_board_width.blockSignals(False)
        self.bead_board_height.blockSignals(True)
        self.bead_board_height.setValue(int(settings.get("board_height", self.bead_board_height.value())))
        self.bead_board_height.blockSignals(False)
        self.bead_keep_blank.blockSignals(True)
        self.bead_keep_blank.setChecked(bool(settings.get("keep_blank_cells", True)))
        self.bead_keep_blank.blockSignals(False)
        view = settings.get("view")
        if isinstance(view, dict):
            self._apply_saved_bead_view(view)

    def _apply_saved_bead_view(self, view: dict):
        """ 从工程恢复施工图显示状态，仅改变显示开关 """
        if not hasattr(self, "bead_view_combo"):
            return
        self._bead_display_syncing = True
        try:
            view_mode = str(view.get("view_mode") or "preview")
            if view_mode == "blueprint" and view.get("marker_symbol") and not view.get("marker_code"):
                view_mode = "mono"
            index = self.bead_view_combo.findData(view_mode)
            if index >= 0:
                self.bead_view_combo.setCurrentIndex(index)
            self.bead_show_grid.setChecked(bool(view.get("grid", True)))
            self.bead_show_x.setChecked(bool(view.get("axis_x", False)))
            self.bead_show_y.setChecked(bool(view.get("axis_y", False)))
            self.bead_show_numbers.setChecked(bool(view.get("coordinate_numbers", False)))
            self.bead_guide5.setChecked(bool(view.get("guide5", False)))
            self.bead_guide10.setChecked(bool(view.get("guide10", False)))
            self.bead_show_boards.setChecked(bool(view.get("board_partitions", False)))
            self.bead_marker_color.setChecked(bool(view.get("marker_color", True)))
            self.bead_marker_code.setChecked(bool(view.get("marker_code", False)))
            self.bead_marker_symbol.setChecked(bool(view.get("marker_symbol", False)))
            cell_index = self.bead_cell_mode.findData(view.get("cell_mode", "color"))
            if cell_index >= 0:
                self.bead_cell_mode.setCurrentIndex(cell_index)
            step_index = self.bead_coord_step.findData(int(view.get("coordinate_step", 1)))
            if step_index >= 0:
                self.bead_coord_step.setCurrentIndex(step_index)
            self.bead_view_mode = str(self.bead_view_combo.currentData() or "preview")
            index = self.view_combo.findData(self.bead_view_mode)
            if index >= 0:
                self.view_combo.setCurrentIndex(index)
        finally:
            self._bead_display_syncing = False

    @staticmethod
    def _set_combo_data(combo: QComboBox, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _version_sort_key(value: str):
        from Moge.core.resources.java import parse_version_tuple

        return parse_version_tuple(value) or (0,)

    def _refresh_mc_versions(self):
        """ 合并静态版本与本地已下载真实资源版本 """
        if not hasattr(self, "mc_version"):
            return
        edition = self.mc_edition.currentData() or "java"
        if edition == "java":
            versions = list(MC_VERSIONS)
        else:
            from Moge.core.resources.bedrock import TARGET_VERSIONS

            versions = list(TARGET_VERSIONS)
        downloaded = set()
        try:
            from Moge.core.resources.manager import ResourceManager

            with ResourceManager() as manager:
                for row in manager.versions(edition):
                    if row["version"] not in versions:
                        versions.append(row["version"])
                    if row["status"] == "ready":
                        downloaded.add(row["version"])
        except Exception:
            downloaded = set()

        current = self.mc_version.currentData()
        self.mc_version.blockSignals(True)
        self.mc_version.clear()
        for version in sorted(versions, key=self._version_sort_key):
            label = version + (" [真实]" if version in downloaded else "")
            self.mc_version.addItem(label, version)
        index = self.mc_version.findData(current)
        if index >= 0:
            self.mc_version.setCurrentIndex(index)
        self.mc_version.blockSignals(False)

    def open_resource_manager(self):
        from Moge.ui.resource_dialog import ResourceManagerDialog

        dialog = ResourceManagerDialog(self)
        dialog.resourcesChanged.connect(self._on_resources_changed)
        dialog.exec_()

    def _on_resources_changed(self):
        self._refresh_mc_versions()
        self.lbl_status.setText("Minecraft 版本资源已更新")

    # ---------- 文件 ---------- #
    def open_image(self, path: str = None, suggested_spec: GridSpec = None, keep_grid: bool = False):
        if self._thread is not None:
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "打开图片", "", IMAGE_FILTER)
        if not path:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(self, "警告", "无法加载该图片，请确认文件格式是否正确！")
            return

        qimage = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
        height, width = qimage.height(), qimage.width()
        pointer = qimage.bits()
        pointer.setsize(qimage.byteCount())
        self.original_img = np.array(pointer).reshape(height, width, 4).copy()
        self.source_path = path
        self.results.clear()
        self.documents.clear()
        self.selected_entry = 0

        if suggested_spec is not None:
            self.grid_width.setValue(max(4, min(256, suggested_spec.width)))
            self.grid_height.setValue(max(4, min(256, suggested_spec.height)))
        elif not keep_grid:
            target = 64
            if width >= height:
                grid_width = min(256, max(8, target))
                grid_height = min(256, max(8, round(target * height / width)))
            else:
                grid_height = min(256, max(8, target))
                grid_width = min(256, max(8, round(target * width / height)))
            self.grid_width.setValue(grid_width)
            self.grid_height.setValue(grid_height)

        self._display_source()
        self.canvas.set_reference_image(self.original_img)
        self.act_compare.blockSignals(True)
        self.act_compare.setChecked(False)
        self.act_compare.blockSignals(False)
        self.act_compare.setEnabled(True)
        self.canvas.set_compare_enabled(False)
        self._refresh_palette()
        self._refresh_stats()
        self._update_status()
        self._update_action_states()
        self.lbl_status.setText(f"已打开 {Path(path).name} ({width}x{height})")
        logger.info("打开图片：%s (%sx%s)", path, width, height)

    def open_sample_library(self):
        from Moge.core.samples import image_path, recommended_grid
        from Moge.ui.sample_dialog import SampleLibraryDialog

        dialog = SampleLibraryDialog(self)
        if dialog.exec_() != QDialog.Accepted or not dialog.selected_entry:
            return
        entry = dialog.selected_entry
        path = image_path(entry)
        if not path.is_file():
            QMessageBox.warning(self, "示例图片缺失", f"找不到内置图片：{path}")
            return
        if self.original_img is not None or self.results:
            answer = QMessageBox.question(
                self,
                "加载示例图片",
                "当前画布已有内容，加载示例图片会替换当前作品（未保存的更改将丢失）。是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        spec = recommended_grid(entry) if dialog.use_recommended else None
        self.open_image(str(path), suggested_spec=spec, keep_grid=not dialog.use_recommended)
        self.lbl_status.setText(
            f"已加载示例：{entry.get('title')}（{entry.get('author')} · {entry.get('license')}）"
        )

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开工程", "", PROJECT_FILTER)
        if not path:
            return
        try:
            document = load_project(path)
            if document.grid is None:
                raise ValueError("工程中没有网格数据")
            mode = document.mode
            settings = dict(self.mode_settings.get(mode, registry.default_settings(mode)))
            settings.update(document.settings.get("params", document.settings) or {})
            if mode == "beads":
                settings["catalog"] = list(self.bead_catalog)
            self.mode_settings[mode] = settings
            self.mode = mode
            self.mode_combo.blockSignals(True)
            self._set_combo_data(self.mode_combo, mode)
            self.mode_combo.blockSignals(False)
            self.mode_stack.setCurrentIndex(self.mode_combo.currentIndex())
            self._apply_settings_to_panels(mode, settings)
            self.grid_width.setValue(document.grid.spec.width)
            self.grid_height.setValue(document.grid.spec.height)

            result = self._result_from_grid(document.grid, settings)
            self.results[mode] = result
            self.selection_anchor = None
            self._stroke_pending = False
            self._display_result(result)
            if self.original_img is None:
                self.canvas.set_reference_image(None)
                self.act_compare.setChecked(False)
                self.act_compare.setEnabled(False)
            self.lbl_status.setText(f"已打开工程 {Path(path).name}")
        except Exception as exc:
            logger.error("打开工程失败", exc_info=True)
            QMessageBox.critical(self, "错误", f"无法打开工程：{exc}")

    def save_project(self):
        result = self._current_result()
        if result is None:
            QMessageBox.warning(self, "警告", "没有可保存的结果，请先执行处理。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存工程", "untitled.moge", PROJECT_FILTER)
        if not path:
            return
        try:
            prepare_result(result)
            params = result.settings.setdefault("params", {})
            params["view"] = self._bead_display_options()
            params["board_width"] = self.bead_board_width.value()
            params["board_height"] = self.bead_board_height.value()
            if result.mode == "beads":
                params["keep_blank_cells"] = self.bead_keep_blank.isChecked()
            document = self.documents.get(result.mode)
            locked = document.locked if document is not None else None
            save_project(path, result, self.source_path, locked=locked)
            self.lbl_status.setText(f"工程已保存：{Path(path).name}")
        except Exception as exc:
            logger.error("保存工程失败", exc_info=True)
            QMessageBox.critical(self, "错误", f"保存失败：{exc}")

    def save_image(self):
        self.export_png_file()

    def export_png_file(self):
        result = self._current_result()
        if result is None:
            QMessageBox.warning(self, "警告", "没有可导出的结果。")
            return
        if result.mode == "beads":
            mode = "blueprint" if self.bead_view_mode == "legend" else self.bead_view_mode
            self.export_bead_png_file(mode)
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 PNG", "moge.png", "PNG 图片 (*.png);;JPEG 图片 (*.jpg)")
        if not path:
            return
        try:
            export_png(result, path, cell_size=8)
            self.lbl_status.setText(f"已导出：{Path(path).name}")
        except Exception as exc:
            logger.error("导出 PNG 失败", exc_info=True)
            QMessageBox.critical(self, "错误", f"导出失败：{exc}")

    def _bead_sheet_options(self, mode: str) -> BeadSheetOptions:
        preview = mode == "preview"
        mono = mode == "mono"
        result = self._current_result()
        mode_label = registry.mode_label(result.mode) if result is not None else registry.mode_label(self.mode)
        detail = ""
        if result is not None and result.mode == "beads":
            detail = f"{result.stats.get('brand') or ''} {result.stats.get('series') or ''}".strip()
        elif result is not None and result.mode == "minecraft":
            detail = f"{result.stats.get('edition') or ''} {result.stats.get('version') or ''}".strip()
        return BeadSheetOptions(
            mode=mode,
            cell_size=24 if preview else (20 if mode == "blueprint" else 22),
            title=f"Moge {mode_label}图纸" + (f"  ·  {detail}" if detail else ""),
            show_axes=not preview and (self.bead_show_x.isChecked() or self.bead_show_y.isChecked()),
            show_coordinate_numbers=not preview and self.bead_show_numbers.isChecked(),
            coordinate_step=int(self.bead_coord_step.currentData() or 1),
            show_guides_5=not preview and self.bead_guide5.isChecked(),
            show_guides_10=not preview and self.bead_guide10.isChecked(),
            show_board_partitions=not preview and self.bead_show_boards.isChecked(),
            board_width=self.bead_board_width.value(),
            board_height=self.bead_board_height.value(),
            show_codes=(self.bead_marker_code.isChecked() and not mono) or mono,
            show_symbols=self.bead_marker_symbol.isChecked() or mono,
            show_legend=not preview,
            transparent_background=False,
        )

    def export_bead_png_file(self, mode: str):
        """ 三模式通用图纸 PNG 导出：成品 / 带标记施工图 / 黑白符号图 """
        result = self._current_result()
        if result is None:
            QMessageBox.warning(self, "警告", "请先生成作品。")
            return
        mode = mode if mode in ("preview", "blueprint", "mono") else "blueprint"
        labels = {"preview": "成品图", "blueprint": "施工图", "mono": "黑白符号图"}
        default_name = f"{result.mode}-{mode}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, f"导出{labels[mode]} PNG", default_name, "PNG 图片 (*.png)"
        )
        if not path:
            return
        try:
            export_bead_png(result, path, self._bead_sheet_options(mode))
            self.lbl_status.setText(f"已导出：{Path(path).name}")
        except Exception as exc:
            logger.error("导出图纸 PNG 失败", exc_info=True)
            QMessageBox.critical(self, "错误", f"导出失败：{exc}")

    def export_partition_pngs_file(self):
        """ 按当前分区规格逐区导出 PNG，供大型作品分块制作 """
        result = self._current_result()
        if result is None:
            QMessageBox.warning(self, "警告", "请先生成作品。")
            return
        directory = QFileDialog.getExistingDirectory(self, "选择分区导出目录")
        if not directory:
            return
        try:
            paths = export_partition_pngs(result, directory, self._bead_sheet_options("blueprint"))
            self.lbl_status.setText(f"已导出 {len(paths)} 个分区 PNG → {directory}")
        except Exception as exc:
            logger.error("导出分区 PNG 失败", exc_info=True)
            QMessageBox.critical(self, "错误", f"分区导出失败：{exc}")

    def export_legend_png_file(self):
        """ 导出当前搜索、范围与排序后的图例面板为高分辨率 PNG """
        rows = []
        for index in range(self.palette_list.count()):
            payload = self.palette_list.item(index).data(LEGEND_DATA_ROLE)
            if isinstance(payload, dict):
                rows.append(payload)
        if not rows:
            QMessageBox.warning(self, "警告", "当前没有可导出的图例。")
            return

        result = self._current_result()
        mode = result.mode if result is not None else self.mode
        mode_label = registry.mode_label(mode)
        sort_label = self.palette_sort.currentText()
        query = self.palette_search.text().strip()
        if mode == "beads":
            brand = str(result.stats.get("brand") or "") if result is not None else self.bead_brand.currentData()
            series = str(result.stats.get("series") or "") if result is not None else self.bead_series.currentData()
            scope = "已用颜色" if self.palette_used_only.isChecked() else "全部颜色"
            total = int(result.stats.get("total_beads") or result.stats.get("filled_cells") or 0) if result is not None else 0
            subtitle = f"{brand} {series} · {scope} · {len(rows)} 色"
            if total:
                subtitle += f" · 总珠子 {total} 颗"
            subtitle += f" · 排序：{sort_label}"
        else:
            subtitle = f"{mode_label} · {len(rows)} 项 · 排序：{sort_label}"
        if query:
            subtitle += f" · 搜索：{query}"

        columns = 1 if len(rows) <= 10 else (2 if len(rows) <= 60 else 3)
        width = {1: 560, 2: 900, 3: 1240}[columns]
        path, _ = QFileDialog.getSaveFileName(
            self, "导出图例 PNG", "legend.png", "PNG 图片 (*.png)"
        )
        if not path:
            return
        options = LegendSheetOptions(
            title=f"Moge {mode_label}图例",
            subtitle=subtitle,
            theme=self._theme,
            columns=columns,
            width=width,
        )
        try:
            export_legend_png(rows, path, options)
            self.lbl_status.setText(f"已导出图例：{Path(path).name}")
        except Exception as exc:
            logger.error("导出图例 PNG 失败", exc_info=True)
            QMessageBox.critical(self, "错误", f"导出失败：{exc}")

    def import_pixel_palette(self):
        """ 将作品颜色整体映射到导入调色板，不重新运行聚类 """
        result = self._current_result()
        document = self._current_document()
        if result is None or document is None or result.mode != "pixel":
            QMessageBox.warning(self, "警告", "请先在普通像素模式下生成作品。")
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入调色板", "", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            palette = load_palette_csv(path)
            new_labels, new_entries = remap_to_palette(document.labels, document.entries, palette)
            document.labels = new_labels
            document.entries = new_entries
            document.locked = np.zeros_like(new_labels, dtype=bool)
            document.clear_history()
            document.selection = None
            result.grid.labels = new_labels
            result.grid.entries = new_entries
            result.grid.cells = []
            prepare_result(result)
            self.selected_entry = 0
            self.canvas.set_locked_mask(document.locked)
            self.canvas.set_selection(None)
            self._refresh_after_edit(immediate=True)
            self.lbl_status.setText(f"已导入调色板 {len(palette)} 色：{Path(path).name}")
        except Exception as exc:
            logger.error("导入调色板失败", exc_info=True)
            QMessageBox.critical(self, "错误", f"导入失败：{exc}")

    def export_pixel_palette(self):
        result = self._current_result()
        if result is None or result.mode != "pixel":
            QMessageBox.warning(self, "警告", "请先在普通像素模式下生成作品。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出调色板", "palette.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            export_palette_csv(result, path)
            self.lbl_status.setText(f"已导出调色板：{Path(path).name}")
        except Exception as exc:
            logger.error("导出调色板失败", exc_info=True)
            QMessageBox.critical(self, "错误", f"导出失败：{exc}")

    def export_csv_file(self):
        result = self._current_result()
        if result is None:
            QMessageBox.warning(self, "警告", "没有可导出的结果。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出材料 CSV", "materials.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            export_materials_csv(result, path)
            self.lbl_status.setText(f"已导出：{Path(path).name}")
        except Exception as exc:
            logger.error("导出 CSV 失败", exc_info=True)
            QMessageBox.critical(self, "错误", f"导出失败：{exc}")

    def export_pdf_file(self):
        result = self._current_result()
        if result is None:
            QMessageBox.warning(self, "警告", "没有可导出的结果。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出图纸 PDF", "blueprint.pdf", "PDF 文件 (*.pdf)")
        if not path:
            return
        board_width = self.bead_board_width.value() if result.mode == "beads" else 29
        board_height = self.bead_board_height.value() if result.mode == "beads" else 29
        try:
            export_blueprint_pdf(result, path, "Moge 图纸", board_width, board_height)
            self.lbl_status.setText(f"已导出：{Path(path).name}")
        except Exception as exc:
            logger.error("导出 PDF 失败", exc_info=True)
            QMessageBox.critical(self, "错误", f"导出失败：{exc}")

    def import_minecraft_pack(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入 Minecraft 资源包", "", "资源包 ZIP (*.zip)")
        if not path:
            return
        try:
            pack = load_resource_pack_zip(path)
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"资源包读取失败：{exc}")
            return
        self.mc_texture_overrides = dict(pack.overrides)
        self.mc_texture_pack_name = pack.pack_name
        self.mc_pack_note.setText(
            f"已加载 {pack.pack_name} 的 {pack.loaded} 个方块贴图（平均色），跳过 {pack.skipped}"
        )
        self.lbl_status.setText(f"已导入资源包：{pack.pack_name}（{pack.loaded} 个方块）")
        logger.info("导入资源包：%s，覆盖 %s 个方块", path, pack.loaded)

    def import_bead_inventory(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入拼豆库存", "", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            inventory, errors = load_bead_inventory_csv(path)
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"库存读取失败：{exc}")
            return
        self.bead_inventory_map = inventory
        codes = [item_id.split(":")[-1] for item_id, quantity in inventory.items() if quantity > 0]
        self.bead_inventory.setText(", ".join(codes))
        total = sum(inventory.values())
        note = f"已导入 {len(inventory)} 个色号，共 {total} 颗"
        if errors:
            note += f"，跳过 {len(errors)} 行"
        self.bead_inventory_note.setText(note)
        self.lbl_status.setText(note)

    def show_bead_info(self):
        from Moge.ui.bead_info_dialog import BeadPaletteInfoDialog

        BeadPaletteInfoDialog(self).exec_()

    def show_mc_diagnostics(self):
        settings = self._collect_settings("minecraft")
        try:
            candidates = minecraft_mode.candidate_blocks(settings)
        except Exception as exc:
            QMessageBox.warning(self, "参数错误", str(exc))
            return
        reasons = minecraft_mode.rejection_diagnostics(settings)
        excluded = {block_id: reason for block_id, reason in reasons.items() if reason}
        category_counts = {}
        for block in candidates:
            label = MC_CATEGORIES.get(block.category, block.category)
            category_counts[label] = category_counts.get(label, 0) + 1

        lines = [
            "<h3>筛选诊断</h3>",
            f"<p>版本 {settings.get('edition')} {settings.get('version')} · "
            f"候选 <b>{len(candidates)}</b> / {len(reasons)} 个方块</p>",
            "<h4>候选类别</h4><ul>",
        ]
        for label, count in sorted(category_counts.items()):
            lines.append(f"<li>{label}：{count}</li>")
        lines.append("</ul><h4>排除原因（前 30 条）</h4><ul>")
        for block_id, reason in list(excluded.items())[:30]:
            lines.append(f"<li>{block_id}：{reason}</li>")
        lines.append("</ul>")
        self.stats_view.setHtml("".join(lines))
        self.right_tabs.setCurrentIndex(1)

    def import_bead_catalog(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入拼豆色卡", "", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            catalog, errors = load_bead_catalog_csv(path)
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"色卡读取失败：{exc}")
            return
        if not catalog:
            QMessageBox.warning(self, "警告", "没有有效色号；\n" + "\n".join(errors[:8]))
            return
        self.bead_catalog = catalog
        self._refresh_bead_catalog_combos()
        note = f"已导入 {len(catalog)} 个色号"
        if errors:
            note += f"，跳过 {len(errors)} 行"
        self.bead_catalog_note.setText(note)
        self.lbl_status.setText(note)

    # ---------- 处理 ---------- #
    def apply_processing(self):
        if self._thread is not None:
            return
        if self.original_img is None:
            QMessageBox.warning(self, "警告", "请先打开图片！")
            return

        self.mode_settings[self.mode] = self._collect_settings(self.mode)
        spec = GridSpec(self.grid_width.value(), self.grid_height.value())
        try:
            config = registry.build_config(self.mode, spec, self.mode_settings[self.mode], self.original_img)
        except Exception as exc:
            QMessageBox.warning(self, "参数错误", str(exc))
            return

        self._task_counter += 1
        self._active_task = self._task_counter
        self._worker = PipelineWorker(self.original_img, config, self._active_task)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_processed)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.cancelled.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)

        self._set_busy(True)
        self.progress.setValue(0)
        self.lbl_status.setText("开始处理...")
        self._thread.start()

    def _on_progress(self, task_id, value, message):
        if task_id != self._active_task:
            return
        self.progress.setValue(int(value))
        self.lbl_status.setText(message)

    def _on_processed(self, task_id, result):
        if task_id != self._active_task:
            return
        self.results[result.mode] = result
        prepare_result(result)
        if result.mode == "beads":
            result.grid.cells = []
        self.palette_used_only.blockSignals(True)
        self.palette_used_only.setChecked(True)
        self.palette_used_only.blockSignals(False)
        self._sync_palette_scope()
        if result.mode == "minecraft":
            edition = str(result.stats.get("edition") or "")
            version = str(result.stats.get("version") or "")
            target_ids = self._mc_candidate_ids(edition, version)
            unexpected = [
                entry.id for entry in result.grid.entries if target_ids and entry.id not in target_ids
            ]
            result.stats["version_isolated"] = not unexpected
            if unexpected:
                logger.error("处理结果包含目标版本之外的方块：%s", unexpected[:10])
                result.stats["isolation_violations"] = unexpected
        if result.mode == self.mode:
            self._display_result(result)
            state, _message = (
                self._mc_state_text(result) if result.mode == "minecraft" else (RESULT_CURRENT, "")
            )
            version_label = (
                f"{result.stats.get('edition')} {result.stats.get('version')}"
                if result.mode == "minecraft" else ""
            )
            warning = (
                " · 画质警告：当前材料集色差较大"
                if result.mode == "minecraft" and result.stats.get("quality_warning")
                else ""
            )
            self.lbl_status.setText(
                f"处理完成：{result.algorithm} · {result.elapsed_ms:.0f} ms"
                + (f" · {state} {version_label}" if version_label else "")
                + warning
            )
        else:
            self.lbl_status.setText(f"{registry.mode_label(result.mode)} 处理完成")
        self._refresh_palette()
        self._refresh_stats()
        self._update_action_states()

    def _on_failed(self, task_id, message):
        if task_id != self._active_task:
            return
        logger.error("处理失败：%s", message)
        self.lbl_status.setText("处理失败")
        if "真实资源尚未下载" in message:
            answer = QMessageBox.question(
                self, "缺少真实资源", message + "\n\n是否打开版本资源管理？"
            )
            if answer == QMessageBox.Yes:
                self.open_resource_manager()
            return
        QMessageBox.critical(self, "错误", f"处理失败：{message}")

    def _on_cancelled(self, task_id):
        if task_id != self._active_task:
            return
        self.lbl_status.setText("已取消处理")

    def _on_thread_finished(self):
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self._worker = None
        self._thread = None
        self._set_busy(False)

    def cancel_task(self):
        if self._worker is not None:
            self._worker.cancel()
            self.lbl_status.setText("正在取消...")

    def _set_busy(self, busy: bool):
        for widget in self._busy_actions:
            widget.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.btn_cancel.setVisible(busy)
        self._update_action_states()

    # ---------- 显示 ---------- #
    def _current_document(self):
        result = self._current_result()
        if result is None:
            return None
        return self._sync_document(result)

    # ---------- 版本一致性状态 ---------- #
    def _mc_target(self) -> tuple[str, str]:
        return (
            str(self.mc_edition.currentData() or "java"),
            str(self.mc_version.currentData() or ""),
        )

    def _mc_candidate_ids(self, edition: str, version: str) -> set[str]:
        """ 目标版本的全部方块 ID；用于识别旧结果中的跨版本材料 """
        key = (edition, version)
        cache = getattr(self, "_mc_target_ids_cache", None)
        if cache is None:
            cache = {}
            self._mc_target_ids_cache = cache
        if key in cache:
            return cache[key]
        ids: set[str] = set()
        try:
            from Moge.core.modes import minecraft as minecraft_mode

            blocks = minecraft_mode.candidate_blocks(
                {
                    "edition": edition,
                    "version": version,
                    "resource_mode": "auto",
                    "buildable_only": False,
                }
            )
            ids = {block.block_id for block in blocks}
        except Exception:
            logger.warning("读取目标版本候选集合失败", exc_info=True)
        if len(cache) >= 8:
            cache.clear()
        cache[key] = ids
        return ids

    @staticmethod
    def _mc_signature(settings: dict) -> tuple:
        return (
            str(settings.get("edition") or ""),
            str(settings.get("version") or ""),
            tuple(sorted(settings.get("categories") or [])),
            str(settings.get("obtainability") or ""),
            bool(settings.get("buildable_only", True)),
            settings.get("max_cost_tier"),
            str(settings.get("orientation") or ""),
            bool(settings.get("exclude_transparent", False)),
            bool(settings.get("exclude_gravity", False)),
            str(settings.get("resource_mode") or ""),
            str(settings.get("matching_strategy") or ""),
        )

    def _mc_state_text(self, result) -> tuple[str, str]:
        generated_edition = str(result.stats.get("edition") or "")
        generated_version = str(result.stats.get("version") or "")
        target_edition, target_version = self._mc_target()
        generated = f"{generated_edition} {generated_version}".strip() or "未知版本"
        target = f"{target_edition} {target_version}".strip() or "未知版本"

        target_ids = self._mc_candidate_ids(target_edition, target_version)
        unexpected = [entry.id for entry in result.grid.entries if target_ids and entry.id not in target_ids]
        if unexpected:
            preview = "、".join(unexpected[:6])
            return RESULT_INVALID, (
                f"旧结果（{generated}）包含 {len(unexpected)} 个 {target} 不支持的材料"
                f"（如 {preview}），请重新处理"
            )

        saved = (result.settings or {}).get("params") or {}
        if (generated_edition, generated_version) != (target_edition, target_version) or (
            self._mc_signature(saved) != self._mc_signature(self._collect_settings("minecraft"))
        ):
            return RESULT_STALE, f"旧结果生成于 {generated}，当前选择 {target}，请重新处理"
        return RESULT_CURRENT, f"当前结果与 {generated} 一致"

    def _on_mc_context_changed(self, *_args):
        """ 版本/筛选变化后刷新状态，不自动重新处理 """
        if self.mode != "minecraft":
            self._update_action_states()
            return
        result = self._current_result()
        self._refresh_stats()
        self._update_status()
        self._update_action_states()
        if result is None:
            return
        state, message = self._mc_state_text(result)
        self.lbl_status.setText(f"{state} · {message}")

    def _missing_texture_entries(self, document, result) -> list:
        counts = result.stats.get("counts", {})
        missing = []
        for entry in document.entries:
            if int(counts.get(entry.id, 0)) <= 0:
                continue
            path = str(entry.meta.get("texture_path") or "")
            if not path or not Path(path).is_file():
                missing.append(entry)
        return missing

    def _sync_document(self, result: RenderResult) -> GridDocument:
        """ 结果与文档共用同一份 labels，保证编辑、渲染、导出读取同一数据 """
        document = self.documents.get(result.mode)
        if document is None or getattr(document, "result_token", None) is not result:
            document = GridDocument.from_result(result)
            document.result_token = result
            self.documents[result.mode] = document
        result.grid.labels = document.labels
        if self.mode == result.mode:
            self.canvas.set_locked_mask(document.locked)
            self.canvas.set_selection(document.selection)
        return document

    def _display_result(self, result: RenderResult):
        document = self._sync_document(result)
        self.center_stack.setCurrentWidget(self.canvas)
        self.canvas.set_image(
            document.render(self.preview_style),
            (result.grid.spec.width, result.grid.spec.height),
        )
        prepare_result(result)
        self.canvas.set_bead_entries(result.grid.entries, result.grid.symbols, document.labels)
        self.canvas.configure_beads(self._bead_display_options())
        self.canvas.set_highlight_label(self.selected_entry)
        self._refresh_legend_page(result)
        if self.bead_view_mode == "legend":
            self.center_stack.setCurrentWidget(self.legend_page)
        self.canvas.set_editable(self.interaction_mode == "edit")
        self._update_preview_label()
        self._on_zoom(self.canvas.zoom())
        self._refresh_preview_actions()
        self._refresh_palette()
        self._refresh_stats()
        self._update_status()
        self._update_action_states()

    def _display_source(self):
        if self.original_img is None:
            self.canvas.set_image(None)
            self._show_welcome()
            return
        self.center_stack.setCurrentWidget(self.canvas)
        height, width = self.original_img.shape[:2]
        self.canvas.set_image(self.original_img, (width, height))
        self.canvas.set_bead_entries([], {}, None)
        self.canvas.configure_beads(self._bead_display_options())
        self.canvas.set_highlight_label(None)
        self.canvas.set_editable(False)
        self.canvas.set_locked_mask(None)
        self.canvas.set_selection(None)
        self.lbl_preview.setText("预览：源图")
        self._on_zoom(self.canvas.zoom())
        self._refresh_palette()
        self._refresh_stats()
        self._update_status()

    # ---------- 查看/编辑与预览 ---------- #
    def _on_interaction_mode_changed(self, action):
        self.interaction_mode = "edit" if action.data() == "edit" else "view"
        self.canvas.set_interaction_mode(self.interaction_mode)
        editable = self.interaction_mode == "edit" and self._current_result() is not None
        self.canvas.set_editable(editable)
        for tool_action in self.tool_actions.values():
            tool_action.setEnabled(self.interaction_mode == "edit")
        self.selection_anchor = None
        self._stroke_pending = False
        self.clear_selection()
        self._update_action_states()
        self.lbl_status.setText(
            "编辑模式：可修改网格数据" if self.interaction_mode == "edit"
            else "查看模式：左键拖动平移，单击检查材料"
        )

    def _on_preview_style_changed(self, action):
        style = "texture" if action.data() == "texture" else "solid"
        if style == self.preview_style:
            return
        document = self._current_document()
        result = self._current_result()
        if document is None or result is None:
            return
        if style == "texture":
            missing = self._missing_texture_entries(document, result)
            if missing:
                self.preview_style = "solid"
                self.act_preview_solid.setChecked(True)
                names = "、".join(
                    str(entry.meta.get("code") or entry.name) for entry in missing[:6]
                )
                message = f"{len(missing)} 个已用材料缺少真实贴图（{names}），已保持纯色预览"
                self.lbl_status.setText(message)
                QMessageBox.warning(self, "缺少真实贴图", message)
                return
        self.preview_style = style
        self._rerender_preview()
        self._update_preview_label()
        self.lbl_status.setText(
            "真实纹理预览：仅改变渲染方式，材料统计不变" if style == "texture" else "已切换为纯色预览"
        )

    def _update_preview_label(self):
        self.lbl_preview.setText(
            "预览：真实纹理" if self.preview_style == "texture" else "预览：纯色"
        )

    def _rerender_preview(self):
        document = self._current_document()
        if document is None:
            return
        self.canvas.set_image(
            document.render(self.preview_style),
            (document.spec.width, document.spec.height),
        )

    def _refresh_preview_actions(self):
        document = self._current_document()
        result = self._current_result()
        has_texture = False
        if document is not None and result is not None:
            counts = result.stats.get("counts", {})
            used = sum(1 for entry in document.entries if int(counts.get(entry.id, 0)) > 0)
            has_texture = used > 0 and not self._missing_texture_entries(document, result)
        self.act_preview_texture.setEnabled(has_texture)
        self.act_preview_texture.setToolTip(
            "读取当前版本真实 PNG 渲染" if has_texture else "存在缺少真实贴图的已用材料"
        )

    def _on_cell_inspected(self, col, row):
        document = self._current_document()
        if document is None:
            return
        value = int(document.labels[row, col])
        if value < 0:
            label = "空白格（不放珠子，不计入总颗数）" if document.mode == "beads" else "空单元（无材料）"
            self.stats_view.setHtml(
                f"<h3>单元格 (X {col + 1}, Y {row + 1})</h3><p>{label}</p>"
            )
            self.right_tabs.setCurrentIndex(1)
            return
        entry = document.entries[value]
        result = self._current_result()
        counts = result.stats.get("counts", {}) if result is not None else {}
        count = int(counts.get(entry.id, 0))
        total = int(result.stats.get("total_beads") or result.stats.get("filled_cells") or 0) if result else 0
        context = self._adapter_context(result)
        context["index"] = value
        adapter = get_adapter(document.mode)
        lines = [
            f"<h3>材料详情 (X {col + 1}, Y {row + 1})</h3>",
            adapter.details(entry, count, total, context),
        ]
        if document.mode == "beads":
            meta = entry.meta
            match = nearest_cross_brand(entry.rgb, self.bead_catalog, brand=str(meta.get("brand") or ""))
            if match is not None:
                other, distance = match
                lines.append(
                    f"<p><b>跨品牌近似参考</b>：{other.brand} {other.series} {other.code} "
                    f"ΔE00={distance:.2f}（仅近似，不是同一色号）</p>"
                )
        self.stats_view.setHtml("".join(lines))
        self.right_tabs.setCurrentIndex(1)
        self.lbl_status.setText(f"(X {col + 1}, Y {row + 1}) {entry.name}")

    def _bead_catalog_entries(self) -> list:
        """ 无作品时用于图例面板预览的当前品牌/系列全部色卡 """
        return get_adapter("beads").browse_entries(self._adapter_context())

    def _refresh_palette(self):
        if self._palette_building:
            return
        self._palette_timer.stop()
        self._palette_building = True
        self.palette_list.blockSignals(True)
        self.palette_list.clear()
        source = self._palette_source()
        if source is None:
            self.palette_note.setText("")
            self.palette_list.blockSignals(False)
            self._palette_building = False
            if hasattr(self, "btn_export_legend"):
                self.btn_export_legend.setEnabled(False)
            self._apply_legend_layout()
            return
        entries, counts, used_only, mode = source
        result = self._current_result()
        total = int(result.stats.get("total_beads") or result.stats.get("filled_cells") or 0) if result is not None else 0
        symbols = dict(result.grid.symbols) if result is not None else {}
        if not symbols:
            symbols = build_symbols(entries)
        adapter = get_adapter(mode)
        context = self._adapter_context(result)
        rows = self._palette_rows(entries, counts, used_only)
        row_height = self._legend_delegate.row_height(self.palette_list.font())
        compact_height = self._legend_delegate.compact_height(self.palette_list.font())
        for row in rows:
            index, entry, count = row[0], row[1], row[2]
            context["index"] = index
            payload = adapter.legend_payload(entry, index, count, total, symbols, context)
            item = QListWidgetItem()
            item.setIcon(self._palette_icon(entry))
            item.setData(Qt.UserRole, index)
            item.setData(LEGEND_DATA_ROLE, payload)
            item.setText(
                payload["primary"]
                + (f"\n{payload['secondary']}" if payload.get("secondary") else "")
            )
            item.setSizeHint(QSize(0, row_height if payload.get("secondary") else compact_height))
            item.setToolTip(adapter.tooltip(entry, payload, count, total))
            self.palette_list.addItem(item)

        visible_indices = [row[0] for row in rows]
        if visible_indices:
            if self.selected_entry not in visible_indices:
                self.selected_entry = visible_indices[0]
            target_row = visible_indices.index(self.selected_entry)
            self.palette_list.setCurrentRow(target_row)
            self.canvas.set_highlight_label(self.selected_entry)
        if not rows:
            query = self.palette_search.text().strip()
            self.palette_note.setText(
                "没有匹配的颜色，请调整搜索或颜色范围。" if query else "当前没有可显示的颜色。"
            )
        else:
            self.palette_note.setText(self._palette_note_text(entries, rows, mode, used_only))
        self.palette_list.blockSignals(False)
        self._palette_building = False
        if hasattr(self, "btn_export_legend"):
            self.btn_export_legend.setEnabled(bool(rows))
        self._apply_legend_layout()

    def _apply_legend_layout(self):
        """ 侧栏宽度变化时在单列与 2/3 列之间自动切换，避免文字重叠 """
        if not hasattr(self, "palette_list") or not hasattr(self, "_legend_delegate"):
            return
        base_font = self.palette_list.font()
        row_height = self._legend_delegate.row_height(base_font)
        compact_height = self._legend_delegate.compact_height(base_font)
        count = self.palette_list.count()
        width = self.palette_list.viewport().width()
        has_secondary = any(
            (self.palette_list.item(index).data(LEGEND_DATA_ROLE) or {}).get("secondary")
            for index in range(count)
        )
        icon_mode = count > 0 and width >= 560 and self.palette_list.isVisible()
        current = self.palette_list.currentRow()
        self.palette_list.blockSignals(True)
        try:
            for index in range(count):
                item = self.palette_list.item(index)
                payload = item.data(LEGEND_DATA_ROLE) or {}
                item.setSizeHint(
                    QSize(0, row_height if payload.get("secondary") else compact_height)
                )
            if icon_mode:
                columns = 3 if width >= 980 else 2
                gap = 6
                column_width = max(250, (width - gap * (columns + 1)) // columns)
                grid_height = (row_height if has_secondary else compact_height) + 6
                self.palette_list.setViewMode(QListView.IconMode)
                self.palette_list.setFlow(QListView.LeftToRight)
                self.palette_list.setWrapping(True)
                self.palette_list.setGridSize(QSize(column_width, grid_height))
                self.palette_list.setSpacing(0)
            else:
                self.palette_list.setViewMode(QListView.ListMode)
                self.palette_list.setFlow(QListView.TopToBottom)
                self.palette_list.setWrapping(False)
                self.palette_list.setGridSize(QSize())
                self.palette_list.setSpacing(2)
            if 0 <= current < count:
                self.palette_list.setCurrentRow(current)
        finally:
            self.palette_list.blockSignals(False)

    def _palette_note_text(self, entries, rows, mode: str, used_only: bool) -> str:
        sort_label = self.palette_sort.currentText()
        result = self._current_result()
        if result is None:
            if mode == "pixel":
                label = "参考调色板"
            elif mode == "beads":
                label = "全部色卡"
            else:
                label = "候选方块"
            detail = ""
            if mode == "beads" and entries:
                brand = str(entries[0].meta.get("brand") or "")
                series = str(entries[0].meta.get("series") or "")
                detail_name = series if brand and brand in series else f"{brand} {series}".strip()
                detail = f"{detail_name} · "
            return f"{detail}{label} {len(entries)} 项 · 排序：{sort_label}"
        used = sum(1 for row in rows if row[2] > 0)
        if mode == "beads":
            brand = str(entries[0].meta.get("brand") or "") if entries else ""
            series = str(entries[0].meta.get("series") or "") if entries else ""
            detail_name = series if brand and brand in series else f"{brand} {series}".strip()
            total_beads = int(result.stats.get("total_beads", 0))
            if used_only:
                return (
                    f"{detail_name} · 已用 {len(rows)} 色"
                    f" · 总珠子 {total_beads} 颗 · 排序：{sort_label}"
                )
            return (
                f"{detail_name} · 全部 {len(rows)} 色"
                f"（已用 {used}）· 总珠子 {total_beads} 颗 · 排序：{sort_label}"
            )
        return (
            f"{registry.mode_label(mode)} · {'已用' if used_only else '全部'} {len(rows)} 项"
            f"（已用 {used}）· 排序：{sort_label}"
        )

    def _adapter_context(self, result=None) -> dict:
        settings = self._collect_settings(self.mode)
        context = {
            "settings": settings,
            "catalog": self.bead_catalog,
            "brand": self.bead_brand.currentData() or "",
            "series": self.bead_series.currentData() or "",
            "size_filter": self.bead_size.currentData() or "",
            "family_filter": self.bead_family.currentData() or "",
            "material_filter": self.bead_material.currentData() or "",
            "disabled_ids": [item.strip() for item in self.bead_disabled.text().split(",") if item.strip()],
            "version": self.mc_version.currentData() or settings.get("version"),
            "edition": self.mc_edition.currentData() or settings.get("edition"),
            "show_counts": result is not None,
            "locked_counts": {},
        }
        if result is not None:
            context["version"] = result.stats.get("version") or context["version"]
            context["edition"] = result.stats.get("edition") or context["edition"]
            document = self.documents.get(result.mode)
            if document is not None and document.locked is not None:
                labels = result.grid.labels
                locked = np.asarray(document.locked, dtype=bool) & (labels >= 0)
                if locked.any():
                    values, counts = np.unique(labels[locked], return_counts=True)
                    context["locked_counts"] = {
                        int(value): int(count) for value, count in zip(values, counts)
                    }
        return context

    def _palette_source(self):
        """ 返回 (entries, counts, used_only, mode)；没有可展示数据时返回 None """
        result = self._current_result()
        if result is not None:
            return (
                result.grid.entries,
                result.stats.get("counts", {}),
                self.palette_used_only.isChecked(),
                result.mode,
            )
        if self.palette_used_only.isChecked():
            self.palette_used_only.blockSignals(True)
            self.palette_used_only.setChecked(False)
            self.palette_used_only.blockSignals(False)
            self._sync_palette_scope()
        adapter = get_adapter(self.mode)
        entries = adapter.browse_entries(self._adapter_context())
        if not entries:
            return None
        return entries, {}, False, self.mode

    @staticmethod
    def _natural_key(value) -> tuple:
        """ 色号自然排序：A2 排在 A10 前，纯数字按数值比较 """
        parts = re.split(r"(\d+)", str(value or ""))
        return tuple(
            (1, int(part)) if part.isdigit() else (0, part.casefold())
            for part in parts
            if part
        )

    def _palette_rows(self, entries, counts, used_only):
        """ 过滤并排序图例行：(下标, 条目, 用量, 色相, 饱和度, 明度值, 亮度) """
        query = self.palette_search.text().strip().lower()
        sort_key = self.palette_sort.currentData()
        rows = []
        for index, entry in enumerate(entries):
            count = int(counts.get(entry.id, 0))
            if used_only and count <= 0:
                continue
            meta = entry.meta or {}
            searchable = " ".join(
                str(value) for value in (
                    entry.name,
                    entry.id,
                    meta.get("code", ""),
                    meta.get("brand", ""),
                    meta.get("series", ""),
                    meta.get("symbol", ""),
                    material_label(str(meta.get("material") or "")),
                )
            ).lower()
            if query and query not in searchable:
                continue
            red, green, blue = (channel / 255.0 for channel in entry.rgb)
            hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
            luminance = 0.299 * entry.rgb[0] + 0.587 * entry.rgb[1] + 0.114 * entry.rgb[2]
            rows.append((index, entry, count, hue, saturation, value, luminance))

        def code_key(row):
            meta = row[1].meta or {}
            return (
                self._natural_key(meta.get("code")),
                str(meta.get("series") or "").casefold(),
                row[1].name.casefold(),
            )

        if sort_key == "name":
            rows.sort(key=lambda row: (row[1].name.casefold(), self._natural_key((row[1].meta or {}).get("code"))))
        elif sort_key == "code":
            rows.sort(key=code_key)
        elif sort_key == "hue":
            rows.sort(key=lambda row: (round(row[3], 4), -row[4], -row[5], row[1].name.casefold()))
        elif sort_key == "luminance":
            rows.sort(key=lambda row: (row[6], row[1].name.casefold(), self._natural_key((row[1].meta or {}).get("code"))))
        else:
            rows.sort(key=lambda row: (-row[2],) + code_key(row))
        return rows

    def _palette_icon(self, entry) -> QIcon:
        """ 复用颜色图标，避免滚动/刷新时重复创建 QPixmap """
        key = tuple(entry.rgb)
        icon = self._icon_cache.get(key)
        if icon is None:
            pixmap = QPixmap(16, 16)
            pixmap.fill(QColor(*key))
            icon = QIcon(pixmap)
            if len(self._icon_cache) >= 512:
                self._icon_cache.clear()
            self._icon_cache[key] = icon
        return icon

    def _on_palette_selected(self, row):
        if row >= 0 and not self._palette_building:
            item = self.palette_list.item(row)
            if item is not None:
                self.selected_entry = int(item.data(Qt.UserRole))
                self.canvas.set_highlight_label(self.selected_entry)

    def _show_palette_context_menu(self, position):
        item = self.palette_list.itemAt(position)
        if item is None:
            return
        index = int(item.data(Qt.UserRole))
        self.selected_entry = index
        self.canvas.set_highlight_label(index)
        menu = QMenu(self)
        act_details = menu.addAction("查看材料详情")
        menu.addSeparator()
        act_lock = menu.addAction("锁定该颜色")
        act_unlock = menu.addAction("解锁该颜色")
        chosen = menu.exec_(self.palette_list.viewport().mapToGlobal(position))
        if chosen is act_details:
            self._show_entry_details(index)
        elif chosen is act_lock:
            self._set_color_lock(index, True)
        elif chosen is act_unlock:
            self._set_color_lock(index, False)

    def _show_entry_details(self, index: int):
        result = self._current_result()
        document = self._current_document()
        if result is None or document is None or not (0 <= index < len(document.entries)):
            return
        entry = document.entries[index]
        count = int(result.stats.get("counts", {}).get(entry.id, 0))
        total = int(result.stats.get("total_beads") or result.stats.get("filled_cells") or 0)
        context = self._adapter_context(result)
        context["index"] = index
        self.stats_view.setHtml(get_adapter(result.mode).details(entry, count, total, context))
        self.right_tabs.setCurrentIndex(1)

    def _set_color_lock(self, index: int, locked: bool):
        document = self._current_document()
        result = self._current_result()
        if document is None or result is None:
            return
        labels = document.labels
        document.locked[labels == index] = bool(locked)
        self.canvas.set_locked_mask(document.locked)
        self._refresh_palette()
        self.lbl_status.setText(f"已{'锁定' if locked else '解锁'}调色板 #{index + 1} 的所有格子")

    def _on_palette_scope_changed(self, _index=None):
        scope = self.palette_scope.currentData() or "used"
        self.palette_used_only.blockSignals(True)
        self.palette_used_only.setChecked(scope == "used")
        self.palette_used_only.blockSignals(False)
        self._refresh_palette()

    def _on_palette_used_only_toggled(self, checked):
        self.palette_scope.blockSignals(True)
        index = self.palette_scope.findData("used" if checked else "all")
        if index >= 0:
            self.palette_scope.setCurrentIndex(index)
        self.palette_scope.blockSignals(False)
        self._refresh_palette()

    def _sync_palette_scope(self):
        scope = "used" if self.palette_used_only.isChecked() else "all"
        self.palette_scope.blockSignals(True)
        index = self.palette_scope.findData(scope)
        if index >= 0:
            self.palette_scope.setCurrentIndex(index)
        self.palette_scope.blockSignals(False)

    def _refresh_stats(self):
        result = self._current_result()
        if result is None:
            if self.original_img is None:
                self.stats_view.setHtml("<p>尚未打开图片。</p>")
            else:
                self.stats_view.setHtml("<p>尚未处理。设置参数后点击“执行处理”。</p>")
            return

        stats = result.stats
        entries = result.grid.entries
        counts = stats.get("counts", {})
        lines = [
            f"<h3>{registry.mode_label(result.mode)}</h3>",
            f"<p><b>算法</b>：{result.algorithm}<br>"
            f"<b>耗时</b>：{result.elapsed_ms:.0f} ms<br>"
            f"<b>网格</b>：{result.grid.spec.width}×{result.grid.spec.height}<br>"
            f"<b>填充单元</b>：{stats.get('filled_cells', 0)} / {stats.get('total_cells', 0)}<br>"
            f"<b>使用颜色/材料</b>：{stats.get('used_entries', 0)}<br>"
            f"<b>孤立单元</b>：{stats.get('isolated_cells', 0)}</p>",
        ]
        if result.mode == "minecraft":
            state, message = self._mc_state_text(result)
            color = {RESULT_CURRENT: "#6cc070", RESULT_STALE: "#e0a030", RESULT_INVALID: "#d05050"}.get(
                state, "#9aa4b8"
            )
            lines.insert(
                1,
                f"<p><b>结果状态</b>：<span style='color:{color}'><b>{state}</b></span><br>{message}</p>",
            )
            target_edition, target_version = self._mc_target()
            vanilla = stats.get("vanilla_coverage") or {}
            renderable = stats.get("renderable_coverage") or {}
            pack = stats.get("pack_coverage") or {}
            strategy_label = dict(minecraft_mode.MATCHING_OPTIONS).get(
                str(stats.get("matching_strategy") or "perceptual"), "感知色差优先"
            )
            lines.append(
                f"<p><b>结果版本</b>：{stats.get('edition')} {stats.get('version')}<br>"
                f"<b>当前选择</b>：{target_edition} {target_version}<br>"
                f"<b>候选方块</b>：{stats.get('candidate_blocks')}<br>"
                f"<b>方块种类</b>：{stats.get('block_types')}<br>"
                f"<b>合成来源</b>：{'Mojang 真实贴图' if stats.get('resource_source') == 'mojang-resource' else '内置近似色'}<br>"
                f"<b>合法率</b>：{stats.get('legal_rate', 0) * 100:.1f}%<br>"
                f"<b>原版资源覆盖率</b>：{vanilla.get('numerator', 0)}/{vanilla.get('denominator', 0)}"
                f"（{vanilla.get('ratio', 0) * 100:.1f}%）<br>"
                f"<b>可渲染候选覆盖率</b>：{renderable.get('numerator', 0)}/{renderable.get('denominator', 0)}"
                f"（{renderable.get('ratio', 0) * 100:.1f}%）<br>"
                f"<b>附加资源包覆盖率</b>：{pack.get('numerator', 0)}/{pack.get('denominator', 0)}"
                f"（{pack.get('ratio', 0) * 100:.1f}%）<br>"
                f"<b>预览</b>：{'真实纹理预览' if self.preview_style == 'texture' else '纯色预览'}<br>"
                f"<b>匹配策略</b>：{strategy_label}<br>"
                f"<b>纹理特征误差</b>：{stats.get('texture_feature_error', 0):.3f}<br>"
                f"<b>ΔE00 均值 / P95</b>：{stats.get('mean_delta_e00', 0):.2f} / {stats.get('p95_delta_e00', 0):.2f}</p>"
            )
            quality = stats.get("quality_message") or ""
            if quality:
                quality_color = "#d05050" if stats.get("quality_warning") else "#6cc070"
                lines.append(
                    f"<p><b>画质评估</b>：<span style='color:{quality_color}'>{quality}</span></p>"
                )
            limitations = stats.get("render_limitations") or []
            if limitations:
                items = "".join(f"<li>{item}</li>" for item in limitations)
                lines.append(f"<p><b>渲染限制</b></p><ul>{items}</ul>")
        elif result.mode == "beads":
            lines.append(self._bead_detail_html(result, page=False))
        if stats.get("note") and result.mode != "beads":
            lines.append(f"<p><i>{stats['note']}</i></p>")

        if result.mode == "beads":
            self.stats_view.setHtml("".join(lines))
            return

        lines.append("<h4>用量</h4><table cellspacing='2'>")
        sorted_entries = sorted(
            entries,
            key=lambda entry: -int(counts.get(entry.id, 0)),
        )
        for entry in sorted_entries[:24]:
            count = int(counts.get(entry.id, 0))
            if count <= 0:
                continue
            color = "#{:02X}{:02X}{:02X}".format(*entry.rgb)
            lines.append(
                f"<tr><td style='background:{color};'>&nbsp;&nbsp;&nbsp;</td>"
                f"<td>{entry.name}</td><td align='right'>{count}</td></tr>"
            )
        lines.append("</table>")
        self.stats_view.setHtml("".join(lines))

    def _bead_detail_html(self, result, page: bool = False) -> str:
        """ 拼豆图例统计：色号清单、数量、占比、总颗数、尺寸与底板分区 """
        stats = result.stats
        entries = result.grid.entries
        labels = result.grid.labels
        summary = bead_summary(labels, entries)
        stats.update(summary)
        stats["used_colors"] = summary["used_colors"]
        symbols = dict(result.grid.symbols) or build_symbols(entries)
        board_width = self.bead_board_width.value()
        board_height = self.bead_board_height.value()
        board_list = board_stats(labels, board_width, board_height)
        stats["board_stats"] = board_list
        stats["boards"] = len(board_list)
        stats["board_size"] = f"{board_width}x{board_height}"
        bead_mm = float(stats.get("bead_mm") or parse_bead_mm(entries))
        width_mm, height_mm = pattern_size_mm(
            result.grid.spec.width, result.grid.spec.height, bead_mm
        )
        stats["bead_mm"] = bead_mm
        stats["pattern_width_mm"] = width_mm
        stats["pattern_height_mm"] = height_mm
        trust_counts = stats.get("catalog_trust_counts") or {}
        material_counts = stats.get("catalog_material_counts") or {}
        trust_text = " · ".join(f"{trust_label(key)} {value}" for key, value in trust_counts.items()) or "-"
        material_text = " · ".join(
            f"{material_label(key)} {value}" for key, value in material_counts.items()
        ) or "-"
        heading = "<h2>拼豆图例统计</h2>" if page else ""
        parts = [
            heading,
            "<p>"
            f"<b>品牌/系列</b>：{stats.get('brand')} / {stats.get('series')}<br>"
            f"<b>网格尺寸</b>：{result.grid.spec.width}×{result.grid.spec.height}<br>"
            f"<b>作品尺寸</b>：{width_mm:.1f} × {height_mm:.1f} mm"
            f"（单颗约 {bead_mm:g} mm）<br>"
            f"<b>总颗数</b>：{summary['total_beads']}<br>"
            f"<b>空白格</b>：{summary['empty_cells']}（不计入总颗数）<br>"
            f"<b>白色珠子</b>：{summary['white_beads']}<br>"
            f"<b>使用颜色</b>：{summary['used_colors']} / {stats.get('candidate_colors', len(entries))}<br>"
            f"<b>透明/特殊材质</b>：{summary['transparent_beads']} / {summary['special_beads']}<br>"
            f"<b>底板</b>：{len(board_list)} 块（{board_width}×{board_height}）<br>"
            f"<b>采购包数</b>：{stats.get('packs_required', 0)} 包（每包 {stats.get('pack_size', 0)}）<br>"
            f"<b>色卡可信度</b>：{trust_text}<br>"
            f"<b>色卡材质</b>：{material_text}<br>"
            f"<b>色卡来源</b>：{stats.get('catalog_source') or '-'}"
            f"（{stats.get('catalog_license') or '未知许可'}）<br>"
            f"<b>色卡已验证</b>：{'是' if stats.get('verified_catalog') else '否（社区/采样参考）'}"
            "</p>",
        ]

        parts.append("<h4>图例 / 用量</h4><table cellspacing='2' cellpadding='2'>")
        parts.append(
            "<tr><th>色块</th><th>色号</th><th>名称</th><th>符号</th>"
            "<th>数量</th><th>占比</th><th>材质</th></tr>"
        )
        rows = legend_rows(labels, entries, symbols, include_unused=False)
        rows.sort(key=lambda row: (-row["count"], row["code"], row["name"]))
        for row in rows:
            color = "#{:02X}{:02X}{:02X}".format(*row["rgb"])
            material = material_label(row["material"]) if row["material"] else "-"
            parts.append(
                f"<tr><td style='background:{color};'>&nbsp;&nbsp;&nbsp;</td>"
                f"<td>{row['code'] or '-'}</td><td>{row['name']}</td>"
                f"<td align='center'>{row['symbol'] or '-'}</td>"
                f"<td align='right'>{row['count']}</td>"
                f"<td align='right'>{row['ratio'] * 100:.1f}%</td>"
                f"<td>{material}</td></tr>"
            )
        parts.append("</table>")

        parts.append("<h4>底板分区</h4><table cellspacing='2' cellpadding='2'>")
        parts.append("<tr><th>编号</th><th>珠子</th><th>空白格</th><th>颜色数</th></tr>")
        for board in board_list:
            parts.append(
                f"<tr><td><b>{board['label']}</b></td><td align='right'>{board['beads']}</td>"
                f"<td align='right'>{board['empty']}</td><td align='right'>{board['colors']}</td></tr>"
            )
        parts.append("</table>")
        if stats.get("note"):
            parts.append(f"<p><i>{stats['note']}</i></p>")
        return "".join(parts)

    def _general_legend_page_html(self, result, page: bool = True) -> str:
        """ 通用图例统计页：三种模式共用色块/编号/名称/符号/数量/占比表 """
        stats = result.stats
        entries = result.grid.entries
        labels = result.grid.labels
        symbols = dict(result.grid.symbols) or build_symbols(entries)
        rows = legend_rows(labels, entries, symbols, include_unused=False)
        rows.sort(key=lambda row: (-row["count"], row["code"], row["name"]))
        total = int(stats.get("total_beads") or stats.get("filled_cells") or 0)
        if not total:
            total = int(np.count_nonzero(labels >= 0))
        heading = "<h2>图例统计</h2>" if page else ""
        parts = [
            heading,
            f"<h3>{registry.mode_label(result.mode)}</h3>",
            "<p>"
            f"<b>网格尺寸</b>：{result.grid.spec.width}×{result.grid.spec.height}<br>"
            f"<b>填充单元</b>：{int(np.count_nonzero(labels >= 0))} / {labels.size}<br>"
            f"<b>空白单元</b>：{int(np.count_nonzero(labels < 0))}<br>"
            f"<b>使用材料</b>：{len(rows)}<br>",
        ]
        if result.mode == "minecraft":
            parts.append(
                f"<b>版本</b>：{stats.get('edition')} {stats.get('version')}<br>"
                f"<b>候选方块</b>：{stats.get('candidate_blocks')}<br>"
                f"<b>合法率</b>：{stats.get('legal_rate', 0) * 100:.1f}%<br>"
            )
        elif result.mode == "pixel":
            parts.append(
                f"<b>算法</b>：{result.algorithm}<br>"
                f"<b>调色板</b>：{len(entries)} 色<br>"
            )
        parts.append("</p>")
        parts.append("<h4>材料用量</h4><table cellspacing='2' cellpadding='2'>")
        parts.append(
            "<tr><th>色块</th><th>编号/ID</th><th>名称</th><th>符号</th>"
            "<th>数量</th><th>占比</th></tr>"
        )
        for row in rows:
            color = "#{:02X}{:02X}{:02X}".format(*row["rgb"])
            code = row["code"] or "-"
            if result.mode == "pixel":
                code = f"#{row['index'] + 1:03d}"
            ratio_text = f"{row['count'] / total * 100:.1f}%" if total else "-"
            parts.append(
                f"<tr><td style='background:{color};'>&nbsp;&nbsp;&nbsp;</td>"
                f"<td>{code}</td><td>{row['name']}</td>"
                f"<td align='center'>{row['symbol'] or '-'}</td>"
                f"<td align='right'>{row['count']}</td>"
                f"<td align='right'>{ratio_text}</td></tr>"
            )
        parts.append("</table>")
        return "".join(parts)

    def _refresh_legend_page(self, result):
        if result is None:
            self.legend_page.setHtml("<p>尚未生成作品。</p>")
            return
        if result.mode == "beads":
            self.legend_page.setHtml(self._bead_detail_html(result, page=True))
        else:
            self.legend_page.setHtml(self._general_legend_page_html(result, page=True))

    def _update_status(self):
        if self.original_img is None:
            self.lbl_source.setText("源图 -")
        else:
            height, width = self.original_img.shape[:2]
            self.lbl_source.setText(f"源图 {width}×{height}")
        self.lbl_grid.setText(f"网格 {self.grid_width.value()}×{self.grid_height.value()}")
        result = self._current_result()
        if result is None:
            self.lbl_colors.setText("颜色 -")
        elif result.mode == "minecraft":
            self.lbl_colors.setText(f"方块 {result.stats.get('block_types', 0)}")
        elif result.mode == "beads":
            used_colors = result.stats.get("used_colors", 0)
            total_beads = result.stats.get("total_beads", 0)
            self.lbl_colors.setText(f"色号 {used_colors} · 珠子 {total_beads}")
        else:
            self.lbl_colors.setText(f"颜色 {result.stats.get('used_entries', 0)}")
        self.lbl_zoom.setText("缩放 -" if self.original_img is None else self.lbl_zoom.text())
        self._update_view_label()

    def _on_hover(self, col, row):
        if col < 0:
            self.lbl_hover.setText("")
            self.lbl_hover.setToolTip("")
            return
        result = self._current_result()
        document = self.documents.get(self.mode)
        if result is not None and document is not None:
            if not (0 <= row < document.labels.shape[0] and 0 <= col < document.labels.shape[1]):
                return
            value = int(document.labels[row, col])
            if value < 0:
                text = f"X {col + 1} · Y {row + 1} · 空白格"
            else:
                entry = document.entries[value]
                count = int(result.stats.get("counts", {}).get(entry.id, 0))
                context = {
                    "show_counts": True,
                    "version": result.stats.get("version"),
                    "edition": result.stats.get("edition"),
                    "locked_counts": {},
                }
                payload = get_adapter(document.mode).legend_payload(
                    entry, value, count,
                    int(result.stats.get("total_beads") or result.stats.get("filled_cells") or 0),
                    result.grid.symbols,
                    context,
                )
                text = f"X {col + 1} · Y {row + 1} · {payload['primary']} · 用量 {count}"
                if payload.get("secondary"):
                    text += f" · {payload['secondary']}"
            self.lbl_hover.setText(text)
            self.lbl_hover.setToolTip(text)
            return
        self.lbl_hover.setText(f"(X {col + 1}, Y {row + 1})")
        self.lbl_hover.setToolTip("")

    def _on_zoom(self, value):
        self.lbl_zoom.setText(f"缩放 {value:.2f}×")

    # ---------- 编辑 ---------- #
    def _on_tool_changed(self, action):
        previous = self.tool
        self.tool = action.data()
        self.selection_anchor = None
        if previous == "select" and self.tool != "select":
            self.clear_selection()
        self.lbl_status.setText(f"工具：{action.text()}")

    def _on_stroke_started(self):
        self._stroke_pending = True
        if self.tool in ("select", "lock"):
            self.selection_anchor = None

    def _on_cell_pressed(self, col, row):
        self._apply_tool(col, row)

    def _on_cell_dragged(self, col, row):
        if self.tool in ("paint", "erase", "select"):
            self._apply_tool(col, row)

    def _ensure_undo(self):
        if not self._stroke_pending:
            return
        document = self._current_document()
        if document is None:
            return
        document.push_history()
        self._stroke_pending = False

    def _apply_tool(self, col, row):
        document = self._current_document()
        result = self._current_result()
        if document is None or result is None or self._thread is not None:
            return
        if self.interaction_mode != "edit":
            return
        if result.mode == "minecraft" and self._mc_state_text(result)[0] != RESULT_CURRENT:
            self.lbl_status.setText("当前结果与所选版本/筛选不一致，请重新处理后再编辑")
            return
        labels = document.labels
        height, width = labels.shape
        if not (0 <= col < width and 0 <= row < height):
            return
        if self._handle_pointer_tool(document, labels, col, row):
            return

        if document.is_locked(col, row):
            self.lbl_status.setText(f"(X {col + 1}, Y {row + 1}) 已锁定，无法编辑")
            return

        if self.tool == "erase" and result.mode not in ("pixel", "beads"):
            QMessageBox.information(self, "提示", "该模式不支持擦除为空白；请用“替换同类”或重新选择材料。")
            return

        new_value = -1 if self.tool == "erase" else int(self.selected_entry)
        if self.tool == "fill":
            changed = self._bucket_fill(document, row, col, new_value)
        elif self.tool == "replace":
            changed = self._replace_same(document, row, col, new_value)
        elif int(labels[row, col]) == new_value:
            changed = False
        else:
            self._ensure_undo()
            labels[row, col] = new_value
            changed = True

        if changed:
            self._refresh_after_edit()

    def _handle_pointer_tool(self, document, labels, col: int, row: int) -> bool:
        """ 处理不修改像素的取色/锁定/选区工具，返回是否已消费本次操作 """
        if self.tool == "pick":
            value = int(labels[row, col])
            if value >= 0:
                self.selected_entry = value
                self.palette_list.setCurrentRow(value)
            return True
        if self.tool == "lock":
            locked = document.toggle_lock(col, row)
            self.canvas.set_locked_mask(document.locked)
            self.lbl_status.setText(
                f"已{'锁定' if locked else '解锁'} (X {col + 1}, Y {row + 1})"
            )
            return True
        if self.tool == "select":
            if self.selection_anchor is None:
                self.selection_anchor = (col, row)
            document.set_selection(self.selection_anchor, (col, row))
            self.canvas.set_selection(document.selection)
            x0, y0, x1, y1 = document.selection
            self.lbl_status.setText(
                f"选区 (X {x0 + 1}, Y {y0 + 1}) - (X {x1 + 1}, Y {y1 + 1})"
            )
            return True
        return False

    def _bucket_fill(self, document, row: int, col: int, new_value: int) -> bool:
        """ 用四邻域洪水填充替换同色区域，返回是否发生修改 """
        labels = document.labels
        height, width = labels.shape
        target = int(labels[row, col])
        if target == new_value:
            return False
        self._ensure_undo()
        queue = deque([(row, col)])
        visited = set()
        while queue:
            current_row, current_col = queue.popleft()
            if (current_row, current_col) in visited:
                continue
            visited.add((current_row, current_col))
            if document.locked[current_row, current_col]:
                continue
            if int(labels[current_row, current_col]) != target:
                continue
            labels[current_row, current_col] = new_value
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = current_row + dr, current_col + dc
                if 0 <= nr < height and 0 <= nc < width and (nr, nc) not in visited:
                    queue.append((nr, nc))
        return True

    def _replace_same(self, document, row: int, col: int, new_value: int) -> bool:
        """ 替换整张网格中的同类色，跳过锁定单元 """
        labels = document.labels
        target = int(labels[row, col])
        if target < 0 or target == new_value:
            return False
        self._ensure_undo()
        labels[(labels == target) & ~document.locked] = new_value
        return True

    def _refresh_after_edit(self, immediate: bool = False):
        result = self._current_result()
        document = self._current_document()
        if result is None or document is None:
            return
        result.grid.labels = document.labels
        labels = document.labels
        result.image = render_grid(labels, document.entries, transparent=result.mode in ("pixel", "beads"))
        flat = labels.reshape(-1)
        valid = flat[flat >= 0]
        counts = result.grid.counts()
        used_entries = len(counts)
        result.stats["counts"] = counts
        result.stats["filled_cells"] = int(valid.size)
        result.stats["empty_cells"] = int(flat.size - valid.size)
        result.stats["used_entries"] = used_entries
        result.stats["isolated_cells"] = isolated_cells(labels)
        if result.mode == "minecraft":
            result.stats["block_types"] = used_entries
        if result.mode == "beads":
            settings = self.mode_settings.get("beads", {})
            board_width = int(settings.get("board_width", self.bead_board_width.value()))
            board_height = int(settings.get("board_height", self.bead_board_height.value()))
            region_stats = board_stats(labels, board_width, board_height)
            summary = bead_summary(labels, document.entries)
            result.stats.update(summary)
            result.stats["board_width"] = board_width
            result.stats["board_height"] = board_height
            result.stats["board_size"] = f"{board_width}x{board_height}"
            result.stats["board_stats"] = region_stats
            result.stats["boards"] = len(region_stats)
            result.stats["total_beads"] = summary["total_beads"]
            result.stats["used_colors"] = summary["used_colors"]
            pack_size = max(1, int(settings.get("pack_size", 1000)))
            result.stats["pack_size"] = pack_size
            result.stats["packs_required"] = sum(
                (count + pack_size - 1) // pack_size for count in counts.values()
            )
        self.canvas.set_image(
            document.render(self.preview_style),
            (document.spec.width, document.spec.height),
        )
        prepare_result(result)
        self.canvas.set_bead_entries(document.entries, result.grid.symbols, labels)
        self.canvas.set_highlight_label(self.selected_entry)
        self._update_status()
        self._update_action_states()
        # 拖动绘制时侧栏重建代价高，合并到空闲时统一刷新
        if immediate:
            self._side_timer.stop()
            self._refresh_palette()
            self._refresh_stats()
            if self.bead_view_mode == "legend":
                self._refresh_legend_page(result)
        else:
            self._side_timer.start()

    def _flush_side_panels(self):
        """ 笔画结束或空闲后统一刷新调色板与统计，避免逐格重建列表 """
        self._side_timer.stop()
        self._refresh_palette()
        self._refresh_stats()
        result = self._current_result()
        if result is not None and self.bead_view_mode == "legend":
            self._refresh_legend_page(result)

    def undo(self):
        document = self._current_document()
        if document is None or not document.undo():
            return
        self._refresh_after_edit(immediate=True)

    def redo(self):
        document = self._current_document()
        if document is None or not document.redo():
            return
        self._refresh_after_edit(immediate=True)

    def toggle_selection_lock(self):
        document = self._current_document()
        if document is None:
            return
        if document.selection is None:
            self.lbl_status.setText("请先用“矩形框选”选择区域")
            return
        document.lock_selection(True)
        self.canvas.set_locked_mask(document.locked)
        x0, y0, x1, y1 = document.selection
        self.lbl_status.setText(
            f"已锁定选区 (X {x0 + 1}, Y {y0 + 1}) - (X {x1 + 1}, Y {y1 + 1})"
        )

    def clear_selection(self):
        document = self._current_document()
        if document is not None:
            document.clear_selection()
        self.selection_anchor = None
        self.canvas.set_selection(None)

    # ---------- 主题/视图 ---------- #
    def canvas_fit(self):
        self.canvas.fit_to_view()

    def _set_sidebar_visible(self, visible: bool):
        self.right_tabs.setVisible(bool(visible))
        if hasattr(self, "_legend_layout_timer"):
            self._legend_layout_timer.start()

    def locate_cell(self):
        text, accepted = QInputDialog.getText(self, "定位坐标", "输入 X,Y（从 1 开始）：", text="1,1")
        if not accepted:
            return
        try:
            col_text, row_text = text.replace("，", ",").split(",", 1)
            display_col, display_row = int(col_text.strip()), int(row_text.strip())
            if display_col < 1 or display_row < 1:
                raise ValueError
            col, row = display_col - 1, display_row - 1
        except Exception:
            QMessageBox.warning(self, "参数错误", "坐标格式应为 X,Y，且从 1 开始，例如 12,8")
            return
        self.canvas.center_on_cell(col, row)
        self.lbl_hover.setText(f"(X {display_col}, Y {display_row})")
        self.lbl_status.setText(f"已定位到 (X {display_col}, Y {display_row})")

    def toggle_theme(self):
        self._theme = "light" if self._theme == "dark" else "dark"
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self._theme)
        self.settings.setValue("theme", self._theme)
        self._apply_legend_theme()

    def show_about(self):
        QMessageBox.about(
            self,
            "关于 Moge",
            "墨格 Moge 2.0\n像素艺术 / Minecraft 方块画 / 拼豆图纸\n\n"
            "内置示例图片来自 Wikimedia Commons，仅使用 CC0 / Public Domain / CC BY 许可；"
            "作者、来源与许可见示例图库详情及 assets/samples/CREDITS.md。\n\n"
            "Minecraft 原版贴图需由用户从官方资源获取，不随安装包分发。",
        )

    def _update_action_states(self):
        result = self._current_result()
        document = self._current_document() if result is not None else None
        has_result = result is not None
        busy = self._thread is not None
        for action in (
            self.act_save_project,
            self.act_export_png,
            self.act_export_csv,
            self.act_export_pdf,
            self.act_export_preview_png,
            self.act_export_blueprint_png,
            self.act_export_mono_png,
            self.act_export_partitions,
        ):
            action.setEnabled(has_result and not busy)
        self.act_undo.setEnabled(bool(document and document.can_undo) and not busy)
        self.act_redo.setEnabled(bool(document and document.can_redo) and not busy)
        editing = self.interaction_mode == "edit" and not busy
        for action in self.tool_actions.values():
            action.setEnabled(editing)
        export_legend = getattr(self, "btn_export_legend", None)
        if export_legend is not None:
            export_legend.setEnabled(bool(self.palette_list.count()) and not busy)
        self._refresh_preview_actions()

    # ---------- 其它 ---------- #
    def _restore_window_state(self):
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("splitter_state")
        if state:
            self.splitter.restoreState(state)
        sizes = self.splitter.sizes()
        if len(sizes) == 3 and self.act_sidebar.isChecked():
            if sizes[0] < 300:
                sizes[0] = 300
            if sizes[2] < 220:
                sizes[2] = 220
            self.splitter.setSizes(sizes)
        if not self.settings.value("sidebar_visible", True, type=bool):
            self.act_sidebar.setChecked(False)
        mode = self.settings.value("mode", "pixel")
        index = self.mode_combo.findData(mode)
        if index >= 0:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(index)
            self.mode_combo.blockSignals(False)
            self.mode = mode
            self.mode_stack.setCurrentIndex(index)
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self._theme)
        for mode_key in self.mode_settings:
            self._apply_settings_to_panels(mode_key, self.mode_settings[mode_key])
        self._apply_settings_to_panels(self.mode, self.mode_settings[self.mode])

    def _refresh_bead_catalog_combos(self):
        brands = sorted({item.brand for item in self.bead_catalog})
        preferred_brand, preferred_series = preferred_selection(self.bead_catalog)
        current_brand = self.bead_brand.currentData()
        self.bead_brand.blockSignals(True)
        self.bead_brand.clear()
        for brand in brands:
            self.bead_brand.addItem(brand, brand)
        target = current_brand if current_brand in brands else preferred_brand
        index = self.bead_brand.findData(target)
        if index >= 0:
            self.bead_brand.setCurrentIndex(index)
        self.bead_brand.blockSignals(False)
        self._on_bead_brand_changed()
        if target == preferred_brand and preferred_series:
            self._set_combo_data(self.bead_series, preferred_series)
            self._on_bead_series_changed()

        meta = self.bead_palette_meta or {}
        verifies = sum(1 for item in self.bead_catalog if item.verified)
        imported = any(item.source.startswith("user") for item in self.bead_catalog)
        if meta and not imported:
            trust = meta.get("trust_counts") or {}
            source_names = "、".join(
                f"{source.get('name')} ({source.get('license')})" for source in meta.get("sources", [])
            )
            brand = self.bead_brand.currentData() or "-"
            series = self.bead_series.currentData() or "-"
            self.bead_catalog_note.setText(
                f"SQLite 色卡 · {brand} {series} · {len(self.bead_catalog)} 色 · MIT"
            )
            self.bead_source_note.setText(
                f"官方 {trust.get('official', 0)} · 社区 {trust.get('community', 0)} · "
                f"采样 {trust.get('sampled', 0)}；冲突 {meta.get('conflicts', 0)} 条；"
                f"数据源：{source_names}；更新：{meta.get('updated_at') or '-'}"
            )
        else:
            source_label = "用户导入" if imported else "内置近似"
            self.bead_catalog_note.setText(
                f"{source_label}色卡：{len(self.bead_catalog)} 色（{'已验证标记' if verifies == len(self.bead_catalog) else '未验证'}）"
            )
            self.bead_source_note.setText("来源：本地导入/内置，不代表品牌官方测量色值")

    def _on_bead_brand_changed(self, _index=None):
        brand = self.bead_brand.currentData()
        current = self.bead_series.currentData()
        series = sorted({item.series for item in self.bead_catalog if item.brand == brand})
        self.bead_series.blockSignals(True)
        self.bead_series.clear()
        for item in series:
            self.bead_series.addItem(item, item)
        if current in series:
            self.bead_series.setCurrentIndex(self.bead_series.findData(current))
        self.bead_series.blockSignals(False)
        self._update_bead_filter_combos()

    def _on_bead_series_changed(self, _index=None):
        self._update_bead_filter_combos()

    def _update_bead_filter_combos(self):
        brand = self.bead_brand.currentData() or ""
        series = self.bead_series.currentData() or ""
        self._fill_bead_filter(
            self.bead_size, available_sizes(self.bead_catalog, brand, series), "全部尺寸"
        )
        self._fill_bead_filter(
            self.bead_family, available_families(self.bead_catalog, brand, series), "全部色系"
        )
        self._fill_bead_filter(
            self.bead_material, available_materials(self.bead_catalog, brand, series), "全部材质"
        )

    def _fill_bead_filter(self, combo: QComboBox, values: list[str], all_label: str):
        current = combo.currentData() or ""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(all_label, "")
        for value in values:
            if value == "solid":
                combo.addItem(material_label(value), value)
            else:
                combo.addItem(value, value)
        index = combo.findData(current)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _result_from_grid(self, grid, settings: dict) -> RenderResult:
        image = render_grid(grid.labels, grid.entries, transparent=grid.mode in ("pixel", "beads"))
        stats = {
            "total_cells": int(grid.labels.size),
            "filled_cells": int(np.count_nonzero(grid.labels >= 0)),
            "empty_cells": int(np.count_nonzero(grid.labels < 0)),
            "used_entries": len(grid.counts()),
            "counts": grid.counts(),
            "isolated_cells": isolated_cells(grid.labels),
            "palette_size": len(grid.entries),
            "algorithm": settings.get("quantizer", "project"),
            "mode": grid.mode,
            "elapsed_ms": 0.0,
        }
        if grid.mode == "minecraft":
            stats["block_types"] = stats["used_entries"]
            stats["edition"] = settings.get("edition", "java")
            stats["version"] = settings.get("version", "")
        if grid.mode == "beads":
            summary = bead_summary(grid.labels, grid.entries)
            stats.update(summary)
            stats["used_colors"] = summary["used_colors"]
            stats["total_beads"] = summary["total_beads"]
            board_width = max(1, int(settings.get("board_width", 29)))
            board_height = max(1, int(settings.get("board_height", 29)))
            region_stats = board_stats(grid.labels, board_width, board_height)
            stats["board_width"] = board_width
            stats["board_height"] = board_height
            stats["board_size"] = f"{board_width}x{board_height}"
            stats["board_stats"] = region_stats
            stats["boards"] = len(region_stats)
            bead_mm = parse_bead_mm(grid.entries)
            width_mm, height_mm = pattern_size_mm(grid.spec.width, grid.spec.height, bead_mm)
            stats["bead_mm"] = bead_mm
            stats["pattern_width_mm"] = width_mm
            stats["pattern_height_mm"] = height_mm
            pack_size = max(1, int(settings.get("pack_size", 1000)))
            stats["pack_size"] = pack_size
            stats["packs_required"] = sum(
                (count + pack_size - 1) // pack_size for count in stats["counts"].values()
            )
        result = RenderResult(
            image=image,
            grid=grid,
            stats=stats,
            algorithm=str(settings.get("quantizer", "project")),
            mode=grid.mode,
            elapsed_ms=0.0,
            settings={"params": settings},
        )
        prepare_result(result)
        return result

    # ---------- 拖放 ---------- #
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_image(url.toLocalFile())
                break

    def resizeEvent(self, event):
        super().resizeEvent(event)
        timer = getattr(self, "_legend_layout_timer", None)
        if timer is not None:
            timer.start()

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self.cancel_task()
            if not self._thread.wait(5000):
                event.ignore()
                return
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("splitter_state", self.splitter.saveState())
        self.settings.setValue("sidebar_visible", self.act_sidebar.isChecked())
        self.settings.setValue("mode", self.mode)
        self.settings.setValue("theme", self._theme)
        # 释放图像与结果，避免关闭窗口后仍持有大数组
        self.original_img = None
        self.results.clear()
        self.documents.clear()
        self.canvas.set_image(None)
        super().closeEvent(event)
