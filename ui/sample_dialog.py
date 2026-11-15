##############################
# ui/sample_dialog.py - 内置示例图库面板
##############################

from pathlib import Path

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from Moge.core.samples import categories, image_path, load_manifest, thumbnail_path


class SampleLibraryDialog(QDialog):
    """ 缩略图网格 + 预览 + 许可信息；离线读取本地资源 """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("示例图库")
        self.resize(980, 640)
        self.entries = load_manifest()
        self.selected_entry = None
        self.use_recommended = True
        self._build_ui()
        self._populate()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标题 / 作者 / 分类")
        self.search.setClearButtonEnabled(True)
        self.category = QComboBox()
        self.category.addItem("全部分类", "")
        for category in categories(self.entries):
            self.category.addItem(category, category)
        top.addWidget(self.search, 1)
        top.addWidget(self.category)
        layout.addLayout(top)

        self.splitter = QSplitter(Qt.Horizontal)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.IconMode)
        self.grid.setIconSize(QSize(148, 108))
        self.grid.setGridSize(QSize(168, 148))
        self.grid.setResizeMode(QListWidget.Adjust)
        self.grid.setMovement(QListWidget.Static)
        self.grid.setSpacing(6)
        self.grid.setWordWrap(True)
        self.splitter.addWidget(self.grid)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.preview = QLabel("选择一张示例图片")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(280, 220)
        self.preview.setStyleSheet("background:#1b1e25; border:1px solid #3a3f4b;")
        self.preview.setScaledContents(False)
        self.info = QTextBrowser()
        self.info.setOpenExternalLinks(True)
        self.info.setMinimumHeight(120)
        right_layout.addWidget(self.preview, 1)
        right_layout.addWidget(self.info)
        self.btn_recommended = QPushButton("使用推荐参数")
        self.btn_current = QPushButton("保留当前参数")
        self.btn_recommended.setEnabled(False)
        self.btn_current.setEnabled(False)
        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_recommended)
        buttons.addWidget(self.btn_current)
        right_layout.addLayout(buttons)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        layout.addWidget(self.splitter, 1)

        self.search.textChanged.connect(self._populate)
        self.category.currentIndexChanged.connect(lambda _index: self._populate())
        self.grid.currentItemChanged.connect(self._on_selected)
        self.grid.itemDoubleClicked.connect(lambda _item: self._accept(True))
        self.btn_recommended.clicked.connect(lambda: self._accept(True))
        self.btn_current.clicked.connect(lambda: self._accept(False))

    def _populate(self):
        query = self.search.text().strip().lower()
        category = self.category.currentData() or ""
        self.grid.clear()
        selected_item = None
        for entry in self.entries:
            if category and entry.get("category") != category:
                continue
            haystack = f"{entry.get('title','')} {entry.get('author','')} {entry.get('category','')}".lower()
            if query and query not in haystack:
                continue
            thumb = thumbnail_path(entry)
            icon = QIcon(QPixmap(str(thumb))) if Path(thumb).is_file() else QIcon()
            item = QListWidgetItem(icon, str(entry.get("title") or entry.get("id")))
            item.setData(Qt.UserRole, entry)
            item.setToolTip(f"{entry.get('title')}\n{entry.get('author')} · {entry.get('license')}")
            self.grid.addItem(item)
            if self.selected_entry and entry.get("id") == self.selected_entry.get("id"):
                selected_item = item
        if selected_item is not None:
            self.grid.setCurrentItem(selected_item)
        elif self.grid.count():
            self.grid.setCurrentRow(0)
        else:
            self.selected_entry = None
            self._show_info(None)

    def _on_selected(self, current, _previous):
        entry = current.data(Qt.UserRole) if current else None
        self.selected_entry = entry
        self._show_info(entry)

    def _show_info(self, entry):
        enabled = entry is not None
        self.btn_recommended.setEnabled(enabled)
        self.btn_current.setEnabled(enabled)
        if entry is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("没有匹配的示例图片")
            self.info.setHtml("")
            return
        image = image_path(entry)
        pixmap = QPixmap(str(image)) if image.is_file() else QPixmap()
        if not pixmap.isNull():
            self.preview.setPixmap(
                pixmap.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self.preview.setText("")
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("图片文件缺失")
        grid = entry.get("recommended_grid") or {}
        self.info.setHtml(
            f"<h3>{entry.get('title')}</h3>"
            f"<p><b>分类</b>：{entry.get('category')}<br>"
            f"<b>作者</b>：{entry.get('author')}<br>"
            f"<b>许可</b>：<a href='{entry.get('license_url') or entry.get('source_url')}'>"
            f"{entry.get('license')}</a><br>"
            f"<b>来源</b>：<a href='{entry.get('source_url')}'>原始页面</a><br>"
            f"<b>尺寸</b>：{entry.get('width')}×{entry.get('height')}（推荐网格 "
            f"{grid.get('width')}×{grid.get('height')}）<br>"
            f"<b>SHA-256</b>：{entry.get('sha256', '')[:16]}…</p>"
            f"<p>{entry.get('description') or ''}</p>"
            f"<p><i>{entry.get('attribution') or ''}</i></p>"
        )

    def _accept(self, recommended: bool):
        if self.selected_entry is None:
            return
        self.use_recommended = bool(recommended)
        self.accept()
