##############################
# ui/main_window.py - Moge 2.0 三模式工作台
##############################

import colorsys
from collections import deque
from pathlib import Path

import numpy as np
from PyQt5.QtCore import QSettings, QSize, Qt, QThread, QTimer
from PyQt5.QtGui import QColor, QIcon, QImage, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
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
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
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
from Moge.core.clustering import ALGORITHM_INFO, EXPERIMENTAL_ALGORITHMS
from Moge.core.document import GridDocument
from Moge.core.grid import isolated_cells, render_grid
from Moge.core.materials import (
    BEAD_CATALOG,
    MC_CATEGORIES,
    MC_VERSIONS,
    BeadColor,
    board_partitions,
    filter_beads,
    load_bead_catalog_csv,
    load_bead_inventory_csv,
    load_resource_pack_zip,
)
from Moge.core.models import GridSpec, RenderResult
from Moge.core.modes import beads as beads_mode
from Moge.core.modes import minecraft as minecraft_mode
from Moge.core.modes import pixel as pixel_mode
from Moge.core.modes import registry
from Moge.exporters.blueprint_pdf import export_blueprint_pdf
from Moge.exporters.csv import export_materials_csv
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


class MainWindow(QMainWindow):
    """ 三模式像素艺术创作工作台 """

    def __init__(self):
        super().__init__()
        self.settings = QSettings("Moge", "Moge2")
        self.original_img = None
        self.source_path = None
        self.mode = "pixel"
        self.mode_settings = {mode: registry.default_settings(mode) for mode, _ in registry.mode_options()}
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

        # 中央：欢迎页 / 画布
        self.center_stack = QStackedWidget()
        self.welcome = self._build_welcome()
        self.canvas = GridCanvas()
        self.canvas.setMinimumWidth(280)
        self.center_stack.addWidget(self.welcome)
        self.center_stack.addWidget(self.canvas)
        self.center_stack.setCurrentWidget(self.welcome)
        self.splitter.addWidget(self.center_stack)

        # 右侧：调色板 + 统计
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self._build_palette_tab(), "调色板")
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
        outer.addWidget(self.splitter)

        # 状态栏
        status = self.statusBar()
        self.lbl_status = QLabel("就绪")
        self.lbl_source = QLabel("源图 -")
        self.lbl_grid = QLabel("网格 -")
        self.lbl_colors = QLabel("颜色 -")
        self.lbl_zoom = QLabel("缩放 -")
        self.lbl_preview = QLabel("预览：纯色")
        self.lbl_hover = QLabel("")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedWidth(150)
        self.progress.setVisible(False)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setVisible(False)

        status.addWidget(self.lbl_status, 1)
        for widget in (self.lbl_hover, self.lbl_preview, self.lbl_source, self.lbl_grid, self.lbl_colors, self.lbl_zoom):
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
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.palette_search = QLineEdit()
        self.palette_search.setPlaceholderText("搜索颜色 / 方块 / 色号")
        self.palette_search.setClearButtonEnabled(True)
        layout.addWidget(self.palette_search)

        filter_row = QHBoxLayout()
        self.palette_sort = QComboBox()
        self.palette_sort.addItem("用量降序", "count")
        self.palette_sort.addItem("名称", "name")
        self.palette_sort.addItem("色相", "hue")
        self.palette_scope = QComboBox()
        self.palette_scope.addItem("已用颜色", "used")
        self.palette_scope.addItem("全部颜色", "all")
        self.palette_used_only = QCheckBox("仅已用")
        self.palette_used_only.setChecked(True)
        self.palette_used_only.setVisible(False)
        filter_row.addWidget(self.palette_sort, 1)
        filter_row.addWidget(self.palette_scope)
        layout.addLayout(filter_row)

        self.palette_list = QListWidget()
        self.palette_list.setIconSize(QSize(18, 18))
        self.palette_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.palette_list.setTextElideMode(Qt.ElideRight)
        self.palette_list.setUniformItemSizes(True)
        self.palette_list.setWordWrap(False)
        self.palette_list.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        layout.addWidget(self.palette_list, 1)
        return tab

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
        self.bead_board_width = QSpinBox()
        self.bead_board_width.setRange(1, 128)
        self.bead_board_width.setValue(29)
        self.bead_board_height = QSpinBox()
        self.bead_board_height.setRange(1, 128)
        self.bead_board_height.setValue(29)
        self.bead_pack_size = QSpinBox()
        self.bead_pack_size.setRange(1, 100000)
        self.bead_pack_size.setValue(1000)
        self.btn_import_inventory = QPushButton("导入库存 CSV...")
        self.bead_inventory_note = QLabel("未导入库存")
        self.bead_inventory_note.setWordWrap(True)
        advanced_form.addRow("底板宽:", self.bead_board_width)
        advanced_form.addRow("底板高:", self.bead_board_height)
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

    def _build_actions(self):
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.mode_combo = QComboBox()
        for key, label in registry.mode_options():
            self.mode_combo.addItem(label, key)
        toolbar.addWidget(QLabel(" 模式 "))
        toolbar.addWidget(self.mode_combo)
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
        file_menu.addSeparator()
        file_menu.addActions([self.act_export_png, self.act_export_csv, self.act_export_pdf])
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
            self.btn_apply,
            self.mode_combo,
        ]

        self._connect_action(self.act_open, lambda: self.open_image())
        self._connect_action(self.act_samples, self.open_sample_library)
        self._connect_action(self.act_open_project, self.open_project)
        self._connect_action(self.act_save_project, self.save_project)
        self._connect_action(self.act_export_png, self.export_png_file)
        self._connect_action(self.act_export_csv, self.export_csv_file)
        self._connect_action(self.act_export_pdf, self.export_pdf_file)
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
        self.btn_mc_diagnose.clicked.connect(self.show_mc_diagnostics)
        self.btn_manage_resources.clicked.connect(self.open_resource_manager)
        self.mc_edition.currentIndexChanged.connect(lambda _index: self._refresh_mc_versions())
        self.btn_cancel.clicked.connect(self.cancel_task)

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
        self.palette_search.textChanged.connect(lambda _text: self._palette_timer.start())
        self.palette_sort.currentIndexChanged.connect(lambda _index: self._refresh_palette())
        self.palette_scope.currentIndexChanged.connect(self._on_palette_scope_changed)
        self.palette_used_only.toggled.connect(self._on_palette_used_only_toggled)
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
        self.palette_used_only.setChecked(self.mode == "beads")
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
        self._refresh_palette()
        self._refresh_stats()
        self._update_status()
        self._update_action_states()
        self.lbl_status.setText(f"已切换到 {registry.mode_label(self.mode)}")

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
            self.bead_board_width.setValue(int(settings.get("board_width", 29)))
            self.bead_board_height.setValue(int(settings.get("board_height", 29)))
            self.bead_pack_size.setValue(int(settings.get("pack_size", 1000)))

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
            save_project(path, result, self.source_path)
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
        path, _ = QFileDialog.getSaveFileName(self, "导出 PNG", "moge.png", "PNG 图片 (*.png);;JPEG 图片 (*.jpg)")
        if not path:
            return
        try:
            export_png(result, path, cell_size=8)
            self.lbl_status.setText(f"已导出：{Path(path).name}")
        except Exception as exc:
            logger.error("导出 PNG 失败", exc_info=True)
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
            self.stats_view.setHtml(f"<h3>单元格 ({col}, {row})</h3><p>空单元（无材料）</p>")
            self.right_tabs.setCurrentIndex(1)
            return
        entry = document.entries[value]
        meta = entry.meta
        lines = [
            f"<h3>材料详情 ({col}, {row})</h3>",
            f"<p><b>{entry.name}</b><br>ID：{entry.id}<br>颜色：{entry.rgb}<br>来源：{entry.source}</p>",
        ]
        if meta.get("geometry"):
            lines.append(f"<p>几何：{meta.get('geometry')}<br>方块状态：{meta.get('block_state') or '-'}</p>")
        if meta.get("texture_sha256"):
            lines.append(
                f"<p><b>真实贴图</b><br>SHA-256：{meta.get('texture_sha256')}<br>"
                f"路径：{meta.get('texture_path')}<br>校验：{'通过' if meta.get('verified') else '未通过'}</p>"
            )
        if document.mode == "beads":
            lines.append(
                f"<p><b>品牌/系列</b>：{meta.get('brand')} / {meta.get('series')}<br>"
                f"<b>色号</b>：{meta.get('code')}<br>"
                f"<b>尺寸</b>：{meta.get('size') or '-'}<br>"
                f"<b>色系/材质</b>：{meta.get('color_family') or '-'} / "
                f"{material_label(str(meta.get('material') or 'solid'))}<br>"
                f"<b>可信度</b>：{trust_label(str(meta.get('trust') or 'unknown'))}<br>"
                f"<b>许可/来源</b>：{meta.get('license') or '-'} · {entry.source}</p>"
            )
            match = nearest_cross_brand(entry.rgb, self.bead_catalog, brand=str(meta.get("brand") or ""))
            if match is not None:
                other, distance = match
                lines.append(
                    f"<p><b>跨品牌近似参考</b>：{other.brand} {other.series} {other.code} "
                    f"ΔE00={distance:.2f}（仅近似，不是同一色号）</p>"
                )
        self.stats_view.setHtml("".join(lines))
        self.right_tabs.setCurrentIndex(1)
        self.lbl_status.setText(f"({col}, {row}) {entry.name}")

    def _bead_catalog_entries(self) -> list:
        """ 无作品时用于调色板预览的品牌色卡条目 """
        from Moge.core.models import PaletteEntry

        brand = self.bead_brand.currentData() or ""
        series = self.bead_series.currentData() or ""
        items = filter_beads(
            self.bead_catalog,
            brand=brand,
            series=series,
            size=self.bead_size.currentData() or None,
            color_family=self.bead_family.currentData() or None,
            material=self.bead_material.currentData() or None,
        )
        return [
            PaletteEntry(
                id=item.id,
                name=item.display_name,
                rgb=item.rgb,
                source=item.source,
                meta={
                    "brand": item.brand,
                    "series": item.series,
                    "code": item.code,
                    "size": item.size,
                    "color_family": item.color_family,
                    "material": item.material,
                    "trust": item.trust,
                    "source_url": item.source_url,
                    "license": item.license,
                },
            )
            for item in items
        ]

    def _refresh_palette(self):
        if self._palette_building:
            return
        self._palette_timer.stop()
        self._palette_building = True
        self.palette_list.blockSignals(True)
        self.palette_list.clear()
        result = self._current_result()
        show_counts = result is not None
        if result is not None:
            entries = result.grid.entries
            counts = result.stats.get("counts", {})
            used_only = self.palette_used_only.isChecked()
            mode = result.mode
        elif self.mode == "beads":
            entries = self._bead_catalog_entries()
            counts = {}
            used_only = False
            mode = "beads"
            if self.palette_used_only.isChecked():
                self.palette_used_only.blockSignals(True)
                self.palette_used_only.setChecked(False)
                self.palette_used_only.blockSignals(False)
                self._sync_palette_scope()
        else:
            self.palette_list.blockSignals(False)
            self._palette_building = False
            return

        query = self.palette_search.text().strip().lower()
        sort_key = self.palette_sort.currentData()

        rows = []
        for index, entry in enumerate(entries):
            count = int(counts.get(entry.id, 0))
            if used_only and count <= 0:
                continue
            searchable = f"{entry.name} {entry.id} {entry.meta.get('code', '')}".lower()
            if query and query not in searchable:
                continue
            red, green, blue = (channel / 255.0 for channel in entry.rgb)
            hue = colorsys.rgb_to_hsv(red, green, blue)[0]
            rows.append((index, entry, count, hue))

        if sort_key == "name":
            rows.sort(key=lambda row: row[1].name)
        elif sort_key == "hue":
            rows.sort(key=lambda row: (row[3], row[1].name))
        else:
            rows.sort(key=lambda row: (-row[2], row[1].name))

        for index, entry, count, _hue in rows:
            key = tuple(entry.rgb)
            icon = self._icon_cache.get(key)
            if icon is None:
                pixmap = QPixmap(16, 16)
                pixmap.fill(QColor(*key))
                icon = QIcon(pixmap)
                if len(self._icon_cache) >= 512:
                    self._icon_cache.clear()
                self._icon_cache[key] = icon
            label = entry.name
            if mode == "minecraft":
                texture = entry.meta.get("texture")
                if texture == "real":
                    label += " [真实]"
                elif texture == "user-average":
                    label += " [贴图]"
                else:
                    label += " [近似]"
            elif mode == "beads":
                meta = entry.meta
                badges = []
                if meta.get("material") and meta.get("material") != "solid":
                    badges.append(material_label(str(meta.get("material"))))
                if meta.get("trust"):
                    badges.append(trust_label(str(meta.get("trust"))))
                label = f"{meta.get('code', '')} {entry.name}"
                if badges:
                    label += " [" + "/".join(badges) + "]"
            suffix = f"  ×{count}" if show_counts else ""
            item = QListWidgetItem(icon, f"{label}{suffix}")
            item.setData(Qt.UserRole, index)
            item.setToolTip(
                f"{entry.name}\n{entry.id}" + (f"\n用量 {count}" if show_counts else "\n示例色卡（未处理）")
            )
            self.palette_list.addItem(item)

        visible_indices = [row[0] for row in rows]
        if visible_indices:
            if self.selected_entry not in visible_indices:
                self.selected_entry = visible_indices[0]
            target_row = visible_indices.index(self.selected_entry)
            self.palette_list.setCurrentRow(target_row)
        self.palette_list.blockSignals(False)
        self._palette_building = False

    def _on_palette_selected(self, row):
        if row >= 0 and not self._palette_building:
            item = self.palette_list.item(row)
            if item is not None:
                self.selected_entry = int(item.data(Qt.UserRole))

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
            trust_counts = stats.get("catalog_trust_counts") or {}
            material_counts = stats.get("catalog_material_counts") or {}
            trust_text = " · ".join(f"{trust_label(key)} {value}" for key, value in trust_counts.items()) or "-"
            material_text = " · ".join(
                f"{material_label(key)} {value}" for key, value in material_counts.items()
            ) or "-"
            lines.append(
                f"<p><b>品牌/系列</b>：{stats.get('brand')} / {stats.get('series')}<br>"
                f"<b>尺寸</b>：{stats.get('size') or '-'}<br>"
                f"<b>色卡来源</b>：{stats.get('catalog_source') or '-'}（{stats.get('catalog_license') or '未知许可'}）<br>"
                f"<b>可信度</b>：{trust_text}<br>"
                f"<b>材质</b>：{material_text}<br>"
                f"<b>总珠子</b>：{stats.get('total_beads')}<br>"
                f"<b>使用颜色</b>：{stats.get('used_colors')}<br>"
                f"<b>底板</b>：{stats.get('boards')} 块（{stats.get('board_size')}）<br>"
                f"<b>采购包数</b>：{stats.get('packs_required', 0)} 包"
                f"（每包 {stats.get('pack_size', 0)}）<br>"
                f"<b>色卡已验证</b>：{'是' if stats.get('verified_catalog') else '否（社区/采样参考）'}</p>"
            )
        if stats.get("note"):
            lines.append(f"<p><i>{stats['note']}</i></p>")

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
            self.lbl_colors.setText(f"色号 {result.stats.get('used_colors', 0)}")
        else:
            self.lbl_colors.setText(f"颜色 {result.stats.get('used_entries', 0)}")
        self.lbl_zoom.setText("缩放 -" if self.original_img is None else self.lbl_zoom.text())

    def _on_hover(self, col, row):
        self.lbl_hover.setText("" if col < 0 else f"({col}, {row})")

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

        if self.tool == "pick":
            value = int(labels[row, col])
            if value >= 0:
                self.selected_entry = value
                self.palette_list.setCurrentRow(value)
            return

        if self.tool == "lock":
            locked = document.toggle_lock(col, row)
            self.canvas.set_locked_mask(document.locked)
            self.lbl_status.setText(f"已{'锁定' if locked else '解锁'} ({col}, {row})")
            return

        if self.tool == "select":
            if self.selection_anchor is None:
                self.selection_anchor = (col, row)
            document.set_selection(self.selection_anchor, (col, row))
            self.canvas.set_selection(document.selection)
            x0, y0, x1, y1 = document.selection
            self.lbl_status.setText(f"选区 ({x0}, {y0}) - ({x1}, {y1})")
            return

        if document.is_locked(col, row):
            self.lbl_status.setText(f"({col}, {row}) 已锁定，无法编辑")
            return

        if self.tool == "erase" and result.mode != "pixel":
            QMessageBox.information(self, "提示", "该模式不支持擦除为空白；请用“替换同类”或重新选择材料。")
            return

        new_value = -1 if self.tool == "erase" else int(self.selected_entry)
        if self.tool == "fill":
            target = int(labels[row, col])
            if target == new_value:
                return
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
        elif self.tool == "replace":
            target = int(labels[row, col])
            if target < 0 or target == new_value:
                return
            self._ensure_undo()
            labels[(labels == target) & ~document.locked] = new_value
        else:
            if int(labels[row, col]) == new_value:
                return
            self._ensure_undo()
            labels[row, col] = new_value

        self._refresh_after_edit()

    def _refresh_after_edit(self, immediate: bool = False):
        result = self._current_result()
        document = self._current_document()
        if result is None or document is None:
            return
        result.grid.labels = document.labels
        labels = document.labels
        result.image = render_grid(labels, document.entries, transparent=(result.mode == "pixel"))
        flat = labels.reshape(-1)
        valid = flat[flat >= 0]
        values, counts = np.unique(valid, return_counts=True) if valid.size else (np.array([]), np.array([]))
        result.stats["counts"] = {
            document.entries[int(value)].id: int(count) for value, count in zip(values, counts)
        }
        result.stats["filled_cells"] = int(valid.size)
        result.stats["empty_cells"] = int(flat.size - valid.size)
        result.stats["used_entries"] = int(len(values))
        result.stats["isolated_cells"] = isolated_cells(labels)
        if result.mode == "minecraft":
            result.stats["block_types"] = int(len(values))
        if result.mode == "beads":
            settings = self.mode_settings.get("beads", {})
            boards = board_partitions(
                labels.shape[1],
                labels.shape[0],
                int(settings.get("board_width", 29)),
                int(settings.get("board_height", 29)),
            )
            board_stats = []
            for board in boards:
                section = labels[board["y0"]:board["y1"], board["x0"]:board["x1"]].reshape(-1)
                section = section[section >= 0]
                board_stats.append(
                    {
                        "index": board["index"],
                        "row": board["row"],
                        "col": board["col"],
                        "beads": int(section.size),
                        "colors": int(len(np.unique(section))),
                    }
                )
            result.stats["board_stats"] = board_stats
            result.stats["total_beads"] = int(valid.size)
            result.stats["used_colors"] = int(len(values))
            pack_size = max(1, int(settings.get("pack_size", 1000)))
            result.stats["pack_size"] = pack_size
            result.stats["packs_required"] = sum(
                (int(count) + pack_size - 1) // pack_size for count in counts
            )
        self.canvas.set_image(
            document.render(self.preview_style),
            (document.spec.width, document.spec.height),
        )
        self._update_status()
        self._update_action_states()
        # 拖动绘制时侧栏重建代价高，合并到空闲时统一刷新
        if immediate:
            self._side_timer.stop()
            self._refresh_palette()
            self._refresh_stats()
        else:
            self._side_timer.start()

    def _flush_side_panels(self):
        """ 笔画结束或空闲后统一刷新调色板与统计，避免逐格重建列表 """
        self._side_timer.stop()
        self._refresh_palette()
        self._refresh_stats()

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
        self.lbl_status.setText(f"已锁定选区 ({x0}, {y0}) - ({x1}, {y1})")

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

    def locate_cell(self):
        text, accepted = QInputDialog.getText(self, "定位坐标", "输入 x,y（从 0 开始）：", text="0,0")
        if not accepted:
            return
        try:
            col_text, row_text = text.replace("，", ",").split(",", 1)
            col, row = int(col_text.strip()), int(row_text.strip())
            if col < 0 or row < 0:
                raise ValueError
        except Exception:
            QMessageBox.warning(self, "参数错误", "坐标格式应为 x,y，例如 12,8")
            return
        self.canvas.center_on_cell(col, row)
        self.lbl_hover.setText(f"({col}, {row})")
        self.lbl_status.setText(f"已定位到 ({col}, {row})")

    def toggle_theme(self):
        self._theme = "light" if self._theme == "dark" else "dark"
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self._theme)
        self.settings.setValue("theme", self._theme)

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
        for action in (self.act_save_project, self.act_export_png, self.act_export_csv, self.act_export_pdf):
            action.setEnabled(has_result and not busy)
        self.act_undo.setEnabled(bool(document and document.can_undo) and not busy)
        self.act_redo.setEnabled(bool(document and document.can_redo) and not busy)
        editing = self.interaction_mode == "edit" and not busy
        for action in self.tool_actions.values():
            action.setEnabled(editing)
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
        self._apply_settings_to_panels("pixel", self.mode_settings["pixel"])
        self._apply_settings_to_panels("minecraft", self.mode_settings["minecraft"])
        self._apply_settings_to_panels("beads", self.mode_settings["beads"])

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
        image = render_grid(grid.labels, grid.entries, transparent=(grid.mode == "pixel"))
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
        if grid.mode == "beads":
            stats["used_colors"] = stats["used_entries"]
            stats["total_beads"] = stats["filled_cells"]
            pack_size = max(1, int(settings.get("pack_size", 1000)))
            stats["pack_size"] = pack_size
            stats["packs_required"] = sum(
                (count + pack_size - 1) // pack_size for count in stats["counts"].values()
            )
        return RenderResult(
            image=image,
            grid=grid,
            stats=stats,
            algorithm=str(settings.get("quantizer", "project")),
            mode=grid.mode,
            elapsed_ms=0.0,
            settings={"params": settings},
        )

    # ---------- 拖放 ---------- #
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_image(url.toLocalFile())
                break

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
