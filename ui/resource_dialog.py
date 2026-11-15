##############################
# ui/resource_dialog.py - Minecraft 版本资源管理
##############################

from pathlib import Path

from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from Moge.core.resources.manager import JAVA_TARGETS, ResourceManager
from Moge.core.resources.paths import resource_root
from Moge.utils.logger_config import get_module_logger

logger = get_module_logger(__name__)


class ResourceTaskWorker(QObject):
    """ 在后台顺序获取/校验多个版本，支持取消与进度 """

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, root, tasks, force: bool = False):
        super().__init__()
        self.root = root
        self.tasks = list(tasks)
        self.force = force
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        results = []
        try:
            with ResourceManager(self.root) as manager:
                total = max(1, len(self.tasks))
                for index, (edition, version) in enumerate(self.tasks):
                    if self._cancel:
                        self.cancelled.emit()
                        return
                    self.progress.emit(int(100 * index / total), f"获取 {edition} {version}")
                    if edition == "java":
                        result = manager.fetch_java(
                            version,
                            force=self.force,
                            progress=lambda percent, text, i=index: self.progress.emit(
                                int((i * 100 + percent) / total), text
                            ),
                            should_cancel=lambda: self._cancel,
                        )
                    else:
                        result = manager.fetch_bedrock(
                            version,
                            force=self.force,
                            progress=lambda percent, text, i=index: self.progress.emit(
                                int((i * 100 + percent) / total), text
                            ),
                            should_cancel=lambda: self._cancel,
                        )
                    results.append(result)
            self.finished.emit(results)
        except Exception as exc:
            if self._cancel:
                self.cancelled.emit()
            else:
                logger.error("资源任务失败", exc_info=True)
                self.failed.emit(str(exc))


class TexturePreviewDialog(QDialog):
    """ 查看真实方块贴图与面选择 """

    def __init__(self, manager: ResourceManager, edition: str, version: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"真实贴图预览 - {edition} {version}")
        self.resize(760, 520)
        self.manager = manager
        self.blocks = [block for block in manager.db.get_blocks(edition, version) if block["faces"]]

        layout = QHBoxLayout(self)
        self.list = QTableWidget(0, 2)
        self.list.setHorizontalHeaderLabels(["方块", "面"])
        self.list.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.list, 1)

        right = QVBoxLayout()
        self.face_combo = QComboBox()
        for face in ("top", "side", "bottom", "front"):
            self.face_combo.addItem(face, face)
        self.image = QLabel("选择方块查看贴图")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(320, 320)
        self.image.setStyleSheet("background:#20232a;color:#ddd;")
        right.addWidget(self.face_combo)
        right.addWidget(self.image, 1)
        layout.addLayout(right, 1)

        for block in self.blocks:
            row = self.list.rowCount()
            self.list.insertRow(row)
            item = QTableWidgetItem(block["block_id"])
            item.setData(Qt.UserRole, block)
            self.list.setItem(row, 0, item)
            self.list.setItem(row, 1, QTableWidgetItem(", ".join(sorted(block["faces"]))))

        self.list.currentCellChanged.connect(self._show_current)
        self.face_combo.currentIndexChanged.connect(self._show_current)
        if self.blocks:
            self.list.selectRow(0)

    def _show_current(self, *args):
        row = self.list.currentRow()
        if row < 0:
            return
        item = self.list.item(row, 0)
        block = item.data(Qt.UserRole) if item else None
        if not block:
            return
        face = self.face_combo.currentData()
        data = block["faces"].get(face) or block["faces"].get("side") or next(iter(block["faces"].values()))
        path = self.manager.texture_preview_path(data["sha256"]) if data else None
        if path and Path(path).exists():
            pixmap = QPixmap(path)
            self.image.setPixmap(pixmap.scaled(320, 320, Qt.KeepAspectRatio, Qt.FastTransformation))
            self.image.setText("")
        else:
            self.image.setPixmap(QPixmap())
            self.image.setText("贴图文件缺失")


class ResourceManagerDialog(QDialog):
    """ 版本资源管理：获取、校验、删除、重建、对比、预览 """

    resourcesChanged = pyqtSignal()

    def __init__(self, parent=None, root=None):
        super().__init__(parent)
        self.setWindowTitle("Minecraft 版本资源管理")
        self.resize(980, 620)
        self.root = root or resource_root()
        self.manager = ResourceManager(self.root)
        self.thread = None
        self.worker = None
        self._build_ui()
        self.refresh_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.edition_combo = QComboBox()
        self.edition_combo.addItem("Java 版", "java")
        self.edition_combo.addItem("基岩版", "bedrock")
        self.edition_combo.currentIndexChanged.connect(lambda _i: self.refresh_table())
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索版本...")
        self.search.textChanged.connect(lambda _t: self.refresh_table())
        self.btn_sync = QPushButton("刷新元数据")
        self.btn_sync.clicked.connect(self.sync_metadata)
        top.addWidget(QLabel("版本:"))
        top.addWidget(self.edition_combo)
        top.addWidget(self.search, 1)
        top.addWidget(self.btn_sync)
        layout.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["版本", "类型", "状态", "方块数", "来源"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.btn_fetch = QPushButton("获取选中")
        self.btn_targets = QPushButton("获取目标版本")
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.btn_verify = QPushButton("校验")
        self.btn_delete = QPushButton("删除")
        self.btn_rebuild = QPushButton("重建索引")
        self.btn_diff = QPushButton("对比选中")
        self.btn_preview = QPushButton("查看贴图")
        for button in (
            self.btn_fetch, self.btn_targets, self.btn_cancel, self.btn_verify,
            self.btn_delete, self.btn_rebuild, self.btn_diff, self.btn_preview,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.log = QLabel("")
        self.log.setWordWrap(True)
        layout.addWidget(self.progress)
        layout.addWidget(self.log)

        self.btn_fetch.clicked.connect(lambda: self.start_fetch(False))
        self.btn_targets.clicked.connect(lambda: self.start_fetch(True))
        self.btn_cancel.clicked.connect(self.cancel_tasks)
        self.btn_verify.clicked.connect(self.verify_selected)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_rebuild.clicked.connect(self.rebuild_selected)
        self.btn_diff.clicked.connect(self.diff_selected)
        self.btn_preview.clicked.connect(self.preview_selected)

    def _rows(self):
        edition = self.edition_combo.currentData()
        try:
            rows = self.manager.list_bedrock_versions() if edition == "bedrock" else self.manager.list_java_versions(True)
        except Exception as exc:
            self.log.setText(f"版本列表读取失败：{exc}")
            return []
        query = self.search.text().strip().lower()
        if query:
            rows = [row for row in rows if query in row["version"].lower()]
        return rows

    def refresh_table(self):
        rows = self._rows()
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [
                row["version"], row.get("version_type", ""), row.get("state") or row["status"],
                str(row.get("blocks", 0)), row.get("tag", "") or row["edition"],
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, (row["edition"], row["version"]))
                self.table.setItem(index, col, item)

    def _selected_tasks(self):
        tasks = []
        for row in sorted({index.row() for index in self.table.selectedIndexes()}):
            item = self.table.item(row, 0)
            if item:
                data = item.data(Qt.UserRole)
                if data:
                    tasks.append(data)
        return tasks

    def start_fetch(self, targets: bool):
        if self.thread is not None:
            return
        edition = self.edition_combo.currentData()
        if targets:
            if edition == "java":
                tasks = [("java", version) for version in JAVA_TARGETS]
            else:
                tasks = [("bedrock", row["version"]) for row in self.manager.list_bedrock_versions()]
        else:
            tasks = self._selected_tasks()
        if not tasks:
            QMessageBox.information(self, "提示", "请先选择版本")
            return
        self._start_tasks(tasks)

    def _start_tasks(self, tasks, force: bool = False):
        self.worker = ResourceTaskWorker(self.root, tasks, force=force)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        for signal in (self.worker.finished, self.worker.failed, self.worker.cancelled):
            signal.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._on_thread_finished)
        self._set_busy(True)
        self.thread.start()

    def _set_busy(self, busy: bool):
        self.progress.setVisible(busy)
        self.btn_cancel.setEnabled(busy)
        for button in (self.btn_fetch, self.btn_targets, self.btn_verify, self.btn_delete,
                       self.btn_rebuild, self.btn_diff, self.btn_preview, self.btn_sync):
            button.setEnabled(not busy)
        if busy:
            self.progress.setValue(0)

    def _on_progress(self, percent, text):
        self.progress.setValue(percent)
        self.log.setText(text)

    def _on_finished(self, results):
        self.log.setText(f"完成 {len(results)} 个版本")
        self.refresh_table()
        self.resourcesChanged.emit()

    def _on_failed(self, message):
        self.log.setText(f"失败：{message}")
        QMessageBox.critical(self, "资源获取失败", message)

    def _on_cancelled(self):
        self.log.setText("已取消")

    def _on_thread_finished(self):
        self._set_busy(False)
        self.thread = None
        self.worker = None

    def cancel_tasks(self):
        if self.worker is not None:
            self.worker.cancel()
            self.log.setText("正在取消...")

    def sync_metadata(self):
        try:
            self.manager.sync_java_manifest(force=True)
            from Moge.core.resources.bedrock import fetch_releases

            fetch_releases(self.root, force=True)
            self.log.setText("版本元数据已刷新")
            self.refresh_table()
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"元数据刷新失败：{exc}")

    def verify_selected(self):
        for edition, version in self._selected_tasks():
            try:
                result = self.manager.verify(edition, version, full=True)
                QMessageBox.information(
                    self, "校验结果",
                    f"{edition} {version}: {'正常' if result['ok'] else '缺失 ' + str(len(result['missing']))}"
                )
            except Exception as exc:
                QMessageBox.critical(self, "错误", str(exc))

    def delete_selected(self):
        tasks = self._selected_tasks()
        if not tasks:
            return
        if QMessageBox.question(self, "确认", f"删除 {len(tasks)} 个版本的本地缓存？") != QMessageBox.Yes:
            return
        for edition, version in tasks:
            try:
                self.manager.delete(edition, version)
            except Exception as exc:
                QMessageBox.critical(self, "错误", str(exc))
        self.refresh_table()
        self.resourcesChanged.emit()

    def rebuild_selected(self):
        for edition, version in self._selected_tasks():
            try:
                self.manager.rebuild(edition, version)
            except Exception as exc:
                QMessageBox.critical(self, "错误", str(exc))
        self.refresh_table()
        self.resourcesChanged.emit()

    def diff_selected(self):
        tasks = self._selected_tasks()
        if len(tasks) != 2 or tasks[0][0] != tasks[1][0]:
            QMessageBox.information(self, "提示", "请选择同一版本类型的两个版本")
            return
        edition = tasks[0][0]
        diff = self.manager.diff(edition, tasks[0][1], tasks[1][1])
        text = (
            f"{tasks[0][1]} vs {tasks[1][1]}\n"
            f"共同方块：{diff['common']}\n"
            f"仅前者：{len(diff['only_in_a'])}，仅后者：{len(diff['only_in_b'])}\n"
            + "\n".join(diff["only_in_b"][:20])
        )
        QMessageBox.information(self, "版本差异", text)

    def preview_selected(self):
        tasks = self._selected_tasks()
        if not tasks:
            return
        edition, version = tasks[0]
        dialog = TexturePreviewDialog(self.manager, edition, version, self)
        dialog.exec_()

    def closeEvent(self, event):
        if self.thread is not None and self.thread.isRunning():
            self.cancel_tasks()
            self.thread.wait(5000)
        self.manager.close()
        super().closeEvent(event)
