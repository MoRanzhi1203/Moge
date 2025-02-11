##############################
# ui/main_window.py - 主窗口布局
##############################

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QMainWindow, QLabel, QFrame, QVBoxLayout, QGroupBox, QPushButton, \
    QFormLayout, QSpinBox, QComboBox, QFileDialog, QMessageBox, QProgressDialog

from Moge.core.image_processor import img_resize, img_pixelize_mean, img_pixelize_common, color_clustering
from Moge.utils.logger_config import get_module_logger

# 获取模块日志器
logger = get_module_logger(__name__)


class MainWindow(QMainWindow):
    """ 主窗口类 """

    def __init__(self):
        """ 初始化 """
        super().__init__()  # 调用父类的构造函数
        logger.debug("开始初始化主窗口")
        self.initUI()
        self.original_img = None
        self.processed_img = None
        self.setup_connections()
        logger.info("主窗口初始化完成")

    def initUI(self):
        """ 初始化UI """
        logger.debug("开始设置UI布局")

        try:
            self.setGeometry(100, 100, 1200, 800)  # 设置窗口大小

            # 主布局
            main_widget = QWidget()  # 创建主窗口部件
            self.setCentralWidget(main_widget)  # 设置主窗口部件
            layout = QHBoxLayout(main_widget)  # 创建水平布局

            # 左侧画布
            self.canvas = QLabel()  # 创建画布标签
            self.canvas.setFrameShape(QFrame.StyledPanel)  # 设置画布为带边框的样式
            self.canvas.setAlignment(Qt.AlignCenter)  # 设置居中对齐
            self.canvas.setStyleSheet("background-color: #333;")  # 设置背景颜色
            layout.addWidget(self.canvas, 3)  # 添加画布到布局

            # 右侧控制面板
            control_panel = QFrame()  # 创建控制面板
            control_panel.setFrameShape(QFrame.StyledPanel)  # 设置控制面板为带边框的样式
            control_layout = QVBoxLayout(control_panel)  # 创建垂直布局
            control_layout.setAlignment(Qt.AlignTop)  # 设置顶部对齐
            layout.addWidget(control_panel, 1)  # 添加控制面板到布局

            # 文件操作
            file_group = QGroupBox("文件操作")  # 创建文件操作组
            file_layout = QVBoxLayout(file_group)  # 创建垂直布局
            self.btn_open = QPushButton("打开图片")  # 创建打开图片按钮
            self.btn_save = QPushButton("保存图片")  # 创建保存图片按钮
            file_layout.addWidget(self.btn_open)  # 添加打开图片按钮到布局
            file_layout.addWidget(self.btn_save)  # 添加保存图片按钮到布局
            control_layout.addWidget(file_group)  # 添加文件操作组到布局

            # 像素化参数
            pixel_group = QGroupBox("像素化参数")  # 创建像素化参数组
            pixel_layout = QFormLayout(pixel_group)  # 创建表单布局

            self.block_size = QSpinBox()  # 创建像素块大小输入框
            self.block_size.setRange(1, 100)  # 设置范围
            self.block_size.setValue(4)  # 设置默认值

            self.resize_method = QComboBox()  # 创建调整方法选择框
            self.resize_method.addItems(["向上取整", "向下取整", "四舍五入"])  # 设置选项

            self.pixel_method = QComboBox()  # 创建计算方法选择框
            self.pixel_method.addItems(["平均值", "频数值"])  # 设置选项

            pixel_layout.addRow("像素块大小:", self.block_size)  # 添加像素块大小输入框到布局
            pixel_layout.addRow("调整方法:", self.resize_method)  # 添加调整方法选择框到布局
            pixel_layout.addRow("计算方法:", self.pixel_method)  # 添加计算方法选择框到布局
            control_layout.addWidget(pixel_group)  # 添加像素化参数组到布局

            # 颜色压缩
            cluster_group = QGroupBox("颜色压缩")  # 创建颜色压缩组
            cluster_layout = QFormLayout(cluster_group)  # 创建表单布局

            self.cluster_size = QSpinBox()  # 创建聚类数量输入框
            self.cluster_size.setRange(2, 256)  # 设置范围
            self.cluster_size.setValue(16)  # 设置默认值

            cluster_layout.addRow("聚类数量:", self.cluster_size)  # 添加聚类数量输入框到布局
            control_layout.addWidget(cluster_group)  # 添加颜色压缩组到布局

            self.cluster_seed = QSpinBox()  # 创建聚类数量输入框
            self.cluster_seed.setRange(0, 10000)  # 设置范围
            self.cluster_seed.setValue(42)  # 设置默认值
            # 随机种子
            cluster_layout.addRow("随机种子:", self.cluster_seed)  # 添加执行处理按钮到布局
            control_layout.addWidget(cluster_group)  # 添加颜色压缩组到布局

            # 处理按钮
            self.btn_process = QPushButton("执行处理")  # 创建处理按钮
            control_layout.addWidget(self.btn_process)  # 添加处理按钮到布局

        except Exception as e:
            logger.critical("UI初始化失败", exc_info=True)
            raise

    def setup_connections(self):
        """ 连接信号与槽 """

        self.btn_open.clicked.connect(self.open_image)  # 打开图片按钮信号连接
        self.btn_save.clicked.connect(self.save_image)  # 保存图片按钮信号连接
        self.btn_process.clicked.connect(self.process_image)  # 处理按钮信号连接

    # ---------- 核心功能 ---------- #
    def open_image(self):
        """ 打开图片 """
        logger.info("开始打开图片流程")
        try:
            # 弹出文件选择对话框
            path, _ = QFileDialog.getOpenFileName(self, "打开图片", "", "图片文件 (*.png *.jpg *.jpeg)")

            # 检查用户是否取消了操作
            if not path:
                logger.info("用户取消了打开图片操作")
                return  # 直接返回，不做任何操作

            # 使用Qt图像加载方式解决中文路径问题
            pixmap = QPixmap(path)  # 加载图片

            # 检查加载的图片是否有效
            if pixmap.isNull():
                logger.warning("加载的图片无效")
                QMessageBox.warning(self, "警告", "无法加载该图片，请确认文件格式是否正确！")
                return

            # 转换为OpenCV格式
            qimg = pixmap.toImage()  # 转换为QImage
            qimg = qimg.convertToFormat(QImage.Format_RGB888)  # 转换为RGB888格式
            ptr = qimg.bits()  # 获取图像数据指针
            ptr.setsize(qimg.byteCount())  # 设置图像数据指针大小
            self.original_img = np.array(ptr).reshape(qimg.height(), qimg.width(), 3)  # 转换为numpy格式

            self.show_image(self.original_img)  # 显示图像
            logger.debug("图片显示更新完成")

        except Exception as e:
            logger.critical("打开图片过程中发生未处理异常", exc_info=True)
            QMessageBox.critical(self, "错误", f"图片加载异常：{str(e)}")

    def save_image(self):
        """ 保存图片 """
        logger.info("开始保存图片流程")

        path = None  # 保存路径
        try:
            if self.processed_img is None:
                logger.warning("尝试保存空图像")
                QMessageBox.warning(self, "警告", "没有可保存的处理后图像！")
                return

            if self.processed_img is not None:
                path, selected_filter = QFileDialog.getSaveFileName(
                    self, "保存图片", "", "PNG文件 (*.png);;JPEG文件 (*.jpg)"
                )

                if not path:
                    logger.debug("用户取消保存操作")
                    return

                logger.info(f"用户选择保存路径：{path} | 格式：{selected_filter}")

                # 转换颜色空间并保存
                save_img = cv2.cvtColor(self.processed_img, cv2.COLOR_RGB2BGR)
                cv2.imencode('.jpg', save_img)[1].tofile(path)

                logger.info(f"图片保存成功：{path}")
                QMessageBox.information(self, "成功", "图片保存成功！")

        except PermissionError:  # 文件写入权限被拒绝
            logger.error(f"文件写入权限被拒绝：{path}")
            QMessageBox.critical(self, "错误", "没有文件写入权限！")
        except Exception as e:  # 其他异常
            logger.critical("保存图片过程中发生未处理异常", exc_info=True)
            QMessageBox.critical(self, "错误", f"保存异常：{str(e)}")

    def show_image(self, img):
        """ 显示图片 """
        logger.debug("开始更新画布显示")
        try:
            if img is None:  # 如果图片为空，则清空画布
                self.canvas.clear()  # 清空画布
                return

            # 转换颜色空间为RGB
            h, w, ch = img.shape  # 获取图像尺寸

            logger.debug(f"准备显示图像，尺寸：{w}x{h}")

            bytes_per_line = ch * w  # 计算每行字节数
            q_img = QImage(img.data, w, h, bytes_per_line, QImage.Format_RGB888)  # 创建QImage
            pixmap = QPixmap.fromImage(q_img)  # 创建QPixmap
            self.canvas.setPixmap(pixmap.scaled(self.canvas.size(), Qt.KeepAspectRatio))  # 显示图片

            # 自适应显示
            self.canvas.setPixmap(pixmap.scaled(
                self.canvas.width() - 20,  # 减去20像素的边距
                self.canvas.height() - 20,  # 减去20像素的边距
                Qt.KeepAspectRatio,  # 保持纵横比
                Qt.SmoothTransformation  # 平滑缩放
            ))

            logger.info(f"画布已更新显示 {w}x{h} 图像")

        except Exception as e:
            logger.error("显示图片时发生异常", exc_info=True)
            self.canvas.setText("图片显示错误！")

    def process_image(self):
        """ 执行处理 """
        logger.info("开始图像处理流程")
        try:
            # 参数校验
            if self.original_img is None:
                logger.warning("未加载图像时尝试处理")
                QMessageBox.warning(self, "警告", "请先打开图片！")
                return

            # 获取处理参数
            params = {
                "block_size": self.block_size.value(),
                "resize_method": self.resize_method.currentText(),
                "pixel_method": self.pixel_method.currentText(),
                "n_clusters": self.cluster_size.value(),
                "seed": self.cluster_seed.value()
            }
            logger.info(f"处理参数：{params}")

            # 创建进度条
            progress_dialog = QProgressDialog("图像处理中...", "取消", 0, 100, self)
            progress_dialog.setWindowTitle("处理进度")
            progress_dialog.setWindowModality(Qt.WindowModal)  # 设置为模态对话框，防止点击其他地方
            progress_dialog.setMinimumDuration(0)  # 设置最短显示时长为 0，立即显示
            progress_dialog.show()  # 显示进度条

            # 图像预处理
            processed = self.original_img.copy()
            logger.debug("原始图像副本创建成功")
            progress_dialog.setLabelText("开始图像缩放处理")
            progress_dialog.setValue(10)  # 更新进度

            # 图像缩放
            logger.debug("开始图像缩放处理")
            processed = img_resize(
                processed,
                params["block_size"],
                self.resize_method.currentIndex()
            )
            logger.info(f"缩放后图像尺寸：{processed.shape}")
            progress_dialog.setValue(30)  # 更新进度

            # 像素化处理
            logger.debug("开始像素化处理")
            progress_dialog.setLabelText("开始像素化处理")
            if params["pixel_method"] == '平均值':
                processed = img_pixelize_mean(processed, params["block_size"])
                logger.debug("完成均值像素化")
            else:
                processed = img_pixelize_common(processed, params["block_size"])
                logger.debug("完成频数像素化")
            progress_dialog.setValue(50)  # 更新进度

            # 颜色聚类
            logger.debug("开始颜色聚类处理")
            progress_dialog.setLabelText("开始颜色聚类处理")
            processed = color_clustering(
                processed,
                params["n_clusters"],
                params["seed"]
            )
            logger.info(f"颜色聚类完成，最终图像尺寸：{processed.shape}")
            progress_dialog.setValue(80)  # 更新进度

            # 结果处理
            self.processed_img = processed
            self.show_image(processed)
            logger.info("图像处理流程完成")

            # 关闭进度条
            progress_dialog.setValue(100)  # 进度条填满
            QTimer.singleShot(500, progress_dialog.close)  # 延迟关闭进度条，以便显示完成状态

        except ValueError as ve:
            logger.error(f"参数错误：{str(ve)}", exc_info=True)
            QMessageBox.warning(self, "参数错误", str(ve))
        except MemoryError:
            logger.critical("内存不足，无法处理图像")
            QMessageBox.critical(self, "错误", "内存不足！")
        except Exception as e:
            logger.critical("图像处理过程中发生未处理异常", exc_info=True)
            QMessageBox.critical(self, "错误", f"处理失败：{str(e)}")
