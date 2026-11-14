##############################
# ui/main_window.py - Moge 2.0 三模式工作台
##############################

from collections import deque
from pathlib import Path

import numpy as np
from PyQt5.QtCore import QSettings, QSize, Qt, QThread
from PyQt5.QtGui import QColor, QIcon, QImage, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from Moge.core.clustering import ALGORITHM_INFO
from Moge.core.grid import isolated_cells, render_grid
from Moge.core.materials import (
    BEAD_CATALOG,
    MC_CATEGORIES,
    MC_VERSIONS,
    BeadColor,
    board_partitions,
    load_bead_catalog_csv,
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
        self.undo_stack = {mode: [] for mode, _ in registry.mode_options()}
        self.redo_stack = {mode: [] for mode, _ in registry.mode_options()}
        self.bead_catalog = list(BEAD_CATALOG)
        self.selected_entry = 0
        self.tool = "paint"
        self._stroke_pending = False
        self._task_counter = 0
        self._active_task = None
        self._thread = None
        self._worker = None
        self._busy_actions = []
        self._theme = str(self.settings.value("theme", "dark"))

        self._build_ui()
        self._build_actions()
        self._connect_signals()
        self._restore_window_state()
        self._set_busy(False)
        self._refresh_palette()
        self._refresh_stats()
        self._update_status()

    # ---------- UI ---------- #
    def _build_ui(self):
        self.setWindowTitle("墨格 Moge 2.0 - 像素艺术工作台")
        self.setGeometry(100, 100, 1200, 800)
        self.setAcceptDrops(True)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(6, 6, 6, 6)

        self.splitter = QSplitter(Qt.Horizontal)

        # 左侧：共享网格 + 模式参数
        left_content = QWidget()
        left_layout = QVBoxLayout(left_content)

        grid_group = QGroupBox("网格")
        grid_form = QFormLayout(grid_group)
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
        left_layout.addWidget(self.mode_stack, 1)

        self.btn_apply = QPushButton("执行处理")
        self.btn_apply.setShortcut(QKeySequence("Ctrl+Return"))
        left_layout.addWidget(self.btn_apply)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_content)
        left_scroll.setMinimumWidth(280)
        self.splitter.addWidget(left_scroll)

        # 中央画布
        self.canvas = GridCanvas()
        self.splitter.addWidget(self.canvas)

        # 右侧：调色板 + 统计
        right_tabs = QTabWidget()
        self.palette_list = QListWidget()
        self.palette_list.setIconSize(QSize(18, 18))
        right_tabs.addTab(self.palette_list, "调色板")
        self.stats_view = QTextBrowser()
        right_tabs.addTab(self.stats_view, "统计")
        right_tabs.setMinimumWidth(240)
        self.splitter.addWidget(right_tabs)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([300, 720, 260])
        outer.addWidget(self.splitter)

        # 状态栏
        status = self.statusBar()
        self.lbl_status = QLabel("就绪")
        self.lbl_source = QLabel("源图 -")
        self.lbl_grid = QLabel("网格 -")
        self.lbl_colors = QLabel("颜色 -")
        self.lbl_zoom = QLabel("缩放 -")
        self.lbl_hover = QLabel("")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedWidth(150)
        self.progress.setVisible(False)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setVisible(False)

        status.addWidget(self.lbl_status, 1)
        for widget in (self.lbl_hover, self.lbl_source, self.lbl_grid, self.lbl_colors, self.lbl_zoom):
            status.addPermanentWidget(widget)
        status.addPermanentWidget(self.progress)
        status.addPermanentWidget(self.btn_cancel)

    def _build_pixel_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        params = QGroupBox("像素化参数")
        form = QFormLayout(params)
        self.px_sampling = QComboBox()
        for key, label in pixel_mode.SAMPLING_OPTIONS:
            self.px_sampling.addItem(label, key)
        self.px_algorithm = QComboBox()
        for key, info in ALGORITHM_INFO.items():
            self.px_algorithm.addItem(info.label, key)
        self.px_colors = QSpinBox()
        self.px_colors.setRange(2, 256)
        self.px_colors.setValue(16)
        self.px_preset = QComboBox()
        for key, label in pixel_mode.PRESET_OPTIONS:
            self.px_preset.addItem(label, key)
        self.px_seed = QSpinBox()
        self.px_seed.setRange(0, 99999)
        self.px_seed.setValue(42)
        self.px_optimize = QCheckBox("清理孤立色块")
        self.px_max_delta = QDoubleSpinBox()
        self.px_max_delta.setRange(0.0, 30.0)
        self.px_max_delta.setSingleStep(0.5)
        self.px_max_delta.setValue(6.0)

        form.addRow("采样方式:", self.px_sampling)
        form.addRow("量化算法:", self.px_algorithm)
        form.addRow("目标颜色数:", self.px_colors)
        form.addRow("效果预设:", self.px_preset)
        form.addRow("随机种子:", self.px_seed)
        form.addRow("", self.px_optimize)
        form.addRow("合并色差上限:", self.px_max_delta)
        layout.addWidget(params)

        self.px_algorithm_note = QLabel("算法与预设会被展开为可检查参数；自动选择基于透明规则。")
        self.px_algorithm_note.setWordWrap(True)
        layout.addWidget(self.px_algorithm_note)
        layout.addStretch(1)
        return panel

    def _build_minecraft_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        params = QGroupBox("Minecraft 筛选")
        form = QFormLayout(params)
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
        self.mc_cost = QComboBox()
        for key, label in minecraft_mode.COST_OPTIONS:
            self.mc_cost.addItem(label, key)
        self.mc_buildable = QCheckBox("仅完整可建造方块")
        self.mc_buildable.setChecked(True)

        form.addRow("版本:", self.mc_edition)
        form.addRow("精确版本:", self.mc_version)
        form.addRow("获取条件:", self.mc_obtain)
        form.addRow("成本偏好:", self.mc_cost)
        form.addRow("", self.mc_buildable)
        layout.addWidget(params)

        category_group = QGroupBox("材质类别（不选=全部）")
        category_layout = QVBoxLayout(category_group)
        self.mc_categories = QListWidget()
        self.mc_categories.setMaximumHeight(150)
        for key, label in MC_CATEGORIES.items():
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.mc_categories.addItem(item)
        category_layout.addWidget(self.mc_categories)
        layout.addWidget(category_group)

        note = QLabel(minecraft_mode.DISPLAY_NOTE)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return panel

    def _build_beads_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        catalog_group = QGroupBox("色卡")
        form = QFormLayout(catalog_group)
        self.bead_brand = QComboBox()
        self.bead_series = QComboBox()
        self.btn_import_beads = QPushButton("导入色卡 CSV...")
        self.bead_catalog_note = QLabel("内置近似色卡，未验证")
        self.bead_catalog_note.setWordWrap(True)
        form.addRow("品牌:", self.bead_brand)
        form.addRow("系列:", self.bead_series)
        form.addRow("", self.btn_import_beads)
        form.addRow("", self.bead_catalog_note)
        layout.addWidget(catalog_group)

        filter_group = QGroupBox("库存与限制")
        filter_form = QFormLayout(filter_group)
        self.bead_inventory = QLineEdit()
        self.bead_inventory.setPlaceholderText("库存色号，逗号分隔；留空=全部")
        self.bead_disabled = QLineEdit()
        self.bead_disabled.setPlaceholderText("禁用色号，逗号分隔")
        self.bead_board_width = QSpinBox()
        self.bead_board_width.setRange(1, 128)
        self.bead_board_width.setValue(29)
        self.bead_board_height = QSpinBox()
        self.bead_board_height.setRange(1, 128)
        self.bead_board_height.setValue(29)
        filter_form.addRow("库存:", self.bead_inventory)
        filter_form.addRow("禁用:", self.bead_disabled)
        filter_form.addRow("底板宽:", self.bead_board_width)
        filter_form.addRow("底板高:", self.bead_board_height)
        layout.addWidget(filter_group)

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
        toolbar.addSeparator()

        self.act_undo = QAction("撤销", self)
        self.act_undo.setShortcut(QKeySequence.Undo)
        self.act_redo = QAction("重做", self)
        self.act_redo.setShortcut(QKeySequence.Redo)
        toolbar.addActions([self.act_undo, self.act_redo])
        toolbar.addSeparator()

        self.act_fit = QAction("适应窗口", self)
        self.act_fit.setShortcut(QKeySequence("F"))
        self.act_grid = QAction("显示网格", self)
        self.act_grid.setCheckable(True)
        self.act_grid.setChecked(True)
        self.act_grid.setShortcut(QKeySequence("Ctrl+G"))
        self.act_theme = QAction("切换主题", self)
        toolbar.addActions([self.act_fit, self.act_grid, self.act_theme])

        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(self.act_open)
        file_menu.addAction(self.act_open_project)
        file_menu.addAction(self.act_save_project)
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
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setShortcut(QKeySequence(shortcut))
            action.setData(key)
            self.tool_group.addAction(action)
            edit_menu.addAction(action)
            self.tool_actions[key] = action
        self.tool_actions["paint"].setChecked(True)

        view_menu = self.menuBar().addMenu("视图")
        view_menu.addActions([self.act_fit, self.act_grid, self.act_theme])

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
        self._connect_action(self.act_open_project, self.open_project)
        self._connect_action(self.act_save_project, self.save_project)
        self._connect_action(self.act_export_png, self.export_png_file)
        self._connect_action(self.act_export_csv, self.export_csv_file)
        self._connect_action(self.act_export_pdf, self.export_pdf_file)
        self._connect_action(self.act_undo, self.undo)
        self._connect_action(self.act_redo, self.redo)
        self._connect_action(self.act_fit, self.canvas_fit)
        self._connect_action(self.act_theme, self.toggle_theme)
        self._connect_action(act_quit, self.close)
        self._connect_action(act_about, self.show_about)
        self.act_grid.toggled.connect(self.canvas.set_grid_visible)
        self.tool_group.triggered.connect(self._on_tool_changed)
        self.btn_import_beads.clicked.connect(self.import_bead_catalog)
        self.btn_cancel.clicked.connect(self.cancel_task)

    def _connect_action(self, action, function):
        action.triggered.connect(lambda checked=False: function())

    def _connect_signals(self):
        self.mode_combo.currentIndexChanged.connect(self._on_mode_combo)
        self.canvas.strokeStarted.connect(self._on_stroke_started)
        self.canvas.cellPressed.connect(self._on_cell_pressed)
        self.canvas.cellDragged.connect(self._on_cell_dragged)
        self.canvas.hoverCellChanged.connect(self._on_hover)
        self.canvas.zoomChanged.connect(self._on_zoom)
        self.palette_list.currentRowChanged.connect(self._on_palette_selected)
        self.bead_brand.currentIndexChanged.connect(self._on_bead_brand_changed)
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
        self._apply_settings_to_panels(self.mode, self.mode_settings[self.mode])
        result = self.results.get(self.mode)
        if result is not None:
            self._display_result(result)
        elif self.original_img is not None:
            self._display_source()
        else:
            self.canvas.set_image(None)
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
            }
        return {
            "brand": self.bead_brand.currentData(),
            "series": self.bead_series.currentData(),
            "catalog": list(self.bead_catalog),
            "inventory_ids": [item.strip() for item in self.bead_inventory.text().split(",") if item.strip()] or None,
            "disabled_ids": [item.strip() for item in self.bead_disabled.text().split(",") if item.strip()],
            "board_width": self.bead_board_width.value(),
            "board_height": self.bead_board_height.value(),
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
                            )
                        )
                self.bead_catalog = converted or self.bead_catalog
                self._refresh_bead_catalog_combos()
            self._set_combo_data(self.bead_brand, settings.get("brand"))
            self._on_bead_brand_changed()
            self._set_combo_data(self.bead_series, settings.get("series"))
            inventory = settings.get("inventory_ids") or []
            self.bead_inventory.setText(", ".join(inventory))
            disabled = settings.get("disabled_ids") or []
            self.bead_disabled.setText(", ".join(disabled))
            self.bead_board_width.setValue(int(settings.get("board_width", 29)))
            self.bead_board_height.setValue(int(settings.get("board_height", 29)))

    @staticmethod
    def _set_combo_data(combo: QComboBox, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    # ---------- 文件 ---------- #
    def open_image(self, path: str = None):
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
        for mode in self.undo_stack:
            self.undo_stack[mode].clear()
            self.redo_stack[mode].clear()
        self.selected_entry = 0

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
        self._refresh_palette()
        self._refresh_stats()
        self._update_status()
        self._update_action_states()
        self.lbl_status.setText(f"已打开 {Path(path).name} ({width}x{height})")
        logger.info("打开图片：%s (%sx%s)", path, width, height)

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
            self._display_result(result)
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
        if result.mode == self.mode:
            self._display_result(result)
            self.lbl_status.setText(
                f"处理完成：{result.algorithm} · {result.elapsed_ms:.0f} ms"
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
    def _display_result(self, result: RenderResult):
        self.canvas.set_image(result.image, (result.grid.spec.width, result.grid.spec.height))
        self.canvas.set_editable(True)
        self._refresh_palette()
        self._refresh_stats()
        self._update_status()
        self._update_action_states()

    def _display_source(self):
        if self.original_img is None:
            self.canvas.set_image(None)
            return
        height, width = self.original_img.shape[:2]
        self.canvas.set_image(self.original_img, (width, height))
        self.canvas.set_editable(False)
        self._refresh_palette()
        self._refresh_stats()
        self._update_status()

    def _refresh_palette(self):
        self.palette_list.blockSignals(True)
        self.palette_list.clear()
        result = self._current_result()
        if result is None:
            self.palette_list.blockSignals(False)
            return

        counts = result.stats.get("counts", {})
        for index, entry in enumerate(result.grid.entries):
            pixmap = QPixmap(16, 16)
            pixmap.fill(QColor(*entry.rgb))
            item = QListWidgetItem(QIcon(pixmap), f"{entry.name}  ×{int(counts.get(entry.id, 0))}")
            item.setData(Qt.UserRole, index)
            self.palette_list.addItem(item)
        self.selected_entry = min(max(self.selected_entry, 0), max(0, self.palette_list.count() - 1))
        if self.palette_list.count():
            self.palette_list.setCurrentRow(self.selected_entry)
        self.palette_list.blockSignals(False)

    def _on_palette_selected(self, row):
        if row >= 0:
            self.selected_entry = row

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
            lines.append(
                f"<p><b>版本</b>：{stats.get('edition')} {stats.get('version')}<br>"
                f"<b>候选方块</b>：{stats.get('candidate_blocks')}<br>"
                f"<b>方块种类</b>：{stats.get('block_types')}<br>"
                f"<b>合法率</b>：{stats.get('legal_rate', 0) * 100:.1f}%<br>"
                f"<b>ΔE00 均值 / P95</b>：{stats.get('mean_delta_e00', 0):.2f} / {stats.get('p95_delta_e00', 0):.2f}</p>"
            )
        elif result.mode == "beads":
            lines.append(
                f"<p><b>品牌/系列</b>：{stats.get('brand')} / {stats.get('series')}<br>"
                f"<b>总珠子</b>：{stats.get('total_beads')}<br>"
                f"<b>使用颜色</b>：{stats.get('used_colors')}<br>"
                f"<b>底板</b>：{stats.get('boards')} 块（{stats.get('board_size')}）<br>"
                f"<b>色卡已验证</b>：{'是' if stats.get('verified_catalog') else '否'}</p>"
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
        self.lbl_zoom.setText(f"{value:.2f}×")

    # ---------- 编辑 ---------- #
    def _on_tool_changed(self, action):
        self.tool = action.data()
        self.lbl_status.setText(f"工具：{action.text()}")

    def _on_stroke_started(self):
        self._stroke_pending = True

    def _on_cell_pressed(self, col, row):
        self._apply_tool(col, row)

    def _on_cell_dragged(self, col, row):
        if self.tool in ("paint", "erase"):
            self._apply_tool(col, row)

    def _ensure_undo(self):
        if not self._stroke_pending:
            return
        result = self._current_result()
        if result is None:
            return
        stack = self.undo_stack[self.mode]
        stack.append(result.grid.labels.copy())
        if len(stack) > 50:
            stack.pop(0)
        self.redo_stack[self.mode].clear()
        self._stroke_pending = False

    def _apply_tool(self, col, row):
        result = self._current_result()
        if result is None or self._thread is not None:
            return
        labels = result.grid.labels
        height, width = labels.shape
        if not (0 <= col < width and 0 <= row < height):
            return

        if self.tool == "pick":
            value = int(labels[row, col])
            if value >= 0:
                self.selected_entry = value
                self.palette_list.setCurrentRow(value)
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
            labels[labels == target] = new_value
        else:
            if int(labels[row, col]) == new_value:
                return
            self._ensure_undo()
            labels[row, col] = new_value

        self._refresh_after_edit()

    def _refresh_after_edit(self):
        result = self._current_result()
        if result is None:
            return
        labels = result.grid.labels
        result.image = render_grid(labels, result.grid.entries, transparent=(result.mode == "pixel"))
        flat = labels.reshape(-1)
        valid = flat[flat >= 0]
        values, counts = np.unique(valid, return_counts=True) if valid.size else (np.array([]), np.array([]))
        result.stats["counts"] = {
            result.grid.entries[int(value)].id: int(count) for value, count in zip(values, counts)
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
        self.canvas.set_image(result.image, (result.grid.spec.width, result.grid.spec.height))
        self._refresh_palette()
        self._refresh_stats()
        self._update_status()
        self._update_action_states()

    def undo(self):
        stack = self.undo_stack[self.mode]
        result = self._current_result()
        if not stack or result is None:
            return
        self.redo_stack[self.mode].append(result.grid.labels.copy())
        result.grid.labels = stack.pop()
        self._refresh_after_edit()

    def redo(self):
        stack = self.redo_stack[self.mode]
        result = self._current_result()
        if not stack or result is None:
            return
        self.undo_stack[self.mode].append(result.grid.labels.copy())
        result.grid.labels = stack.pop()
        self._refresh_after_edit()

    # ---------- 主题/视图 ---------- #
    def canvas_fit(self):
        self.canvas.fit_to_view()

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
            "内置 Minecraft 与拼豆色值为屏幕近似，未包含受版权保护的贴图。",
        )

    def _update_action_states(self):
        result = self._current_result()
        has_result = result is not None
        busy = self._thread is not None
        for action in (self.act_save_project, self.act_export_png, self.act_export_csv, self.act_export_pdf):
            action.setEnabled(has_result and not busy)
        self.act_undo.setEnabled(bool(self.undo_stack[self.mode]) and not busy)
        self.act_redo.setEnabled(bool(self.redo_stack[self.mode]) and not busy)

    # ---------- 其它 ---------- #
    def _restore_window_state(self):
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("splitter_state")
        if state:
            self.splitter.restoreState(state)
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
        current_brand = self.bead_brand.currentData()
        self.bead_brand.blockSignals(True)
        self.bead_brand.clear()
        for brand in brands:
            self.bead_brand.addItem(brand, brand)
        if current_brand and current_brand in brands:
            self.bead_brand.setCurrentIndex(self.bead_brand.findData(current_brand))
        self.bead_brand.blockSignals(False)
        self._on_bead_brand_changed()
        series = sorted(
            {item.series for item in self.bead_catalog if item.brand == self.bead_brand.currentData()}
        )
        self.bead_series.clear()
        for item in series:
            self.bead_series.addItem(item, item)
        self.bead_catalog_note.setText(f"内置近似色卡：{len(self.bead_catalog)} 色（未验证）")

    def _on_bead_brand_changed(self):
        brand = self.bead_brand.currentData()
        current = self.bead_series.currentData()
        self.bead_series.blockSignals(True)
        self.bead_series.clear()
        for series in sorted({item.series for item in self.bead_catalog if item.brand == brand}):
            self.bead_series.addItem(series, series)
        if current:
            index = self.bead_series.findData(current)
            if index >= 0:
                self.bead_series.setCurrentIndex(index)
        self.bead_series.blockSignals(False)

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
        self.settings.setValue("mode", self.mode)
        self.settings.setValue("theme", self._theme)
        super().closeEvent(event)
