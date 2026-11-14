##############################
# ui/worker.py - 图像处理工作线程
##############################

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from Moge.core.image_processor import (
    ProcessingCancelled,
    color_clustering,
    img_pixelize_common,
    img_pixelize_mean,
    img_resize,
)
from Moge.core.models import PixelMethod
from Moge.core.pipeline import run_pipeline
from Moge.utils.logger_config import get_module_logger

logger = get_module_logger(__name__)


class ProcessingWorker(QObject):
    """ 在独立线程中执行图像处理，避免阻塞界面 """

    progress = pyqtSignal(int, str)  # 进度百分比、状态文本
    finished = pyqtSignal(object)  # 处理结果（numpy 数组）
    failed = pyqtSignal(str)  # 错误信息
    cancelled = pyqtSignal()  # 用户取消

    def __init__(self, image, params):
        super().__init__()
        self._image = image
        self._params = params
        self._cancel_requested = False

    def cancel(self):
        """ 请求取消（在下一个检查点生效） """
        self._cancel_requested = True

    def _should_cancel(self):
        return self._cancel_requested

    def _raise_if_cancelled(self):
        if self._cancel_requested:
            raise ProcessingCancelled()

    @pyqtSlot()
    def run(self):
        """ 处理入口（由 QThread.started 触发） """
        params = self._params
        try:
            self.progress.emit(5, "开始图像缩放处理")
            processed = img_resize(self._image, params.block_size, params.resize_mode)
            self._raise_if_cancelled()
            self.progress.emit(20, "图像缩放完成")

            if params.pixel_method is PixelMethod.MEAN:
                processed = img_pixelize_mean(processed, params.block_size)
                self.progress.emit(45, "均值像素化完成")
            else:
                processed = img_pixelize_common(
                    processed,
                    params.block_size,
                    should_cancel=self._should_cancel,
                    progress_callback=lambda ratio: self.progress.emit(
                        20 + int(25 * ratio), "正在按频数像素化"
                    ),
                )
                self.progress.emit(45, "频数像素化完成")
            self._raise_if_cancelled()

            processed = color_clustering(
                processed,
                params.n_clusters,
                params.seed,
                should_cancel=self._should_cancel,
                progress_callback=lambda ratio: self.progress.emit(
                    45 + int(45 * ratio), "正在压缩颜色"
                ),
            )
            self._raise_if_cancelled()

            self.progress.emit(95, "图像处理完成")
            self.finished.emit(np.ascontiguousarray(processed))

        except ProcessingCancelled:
            logger.info("用户取消了图像处理")
            self.cancelled.emit()
        except MemoryError:
            logger.critical("内存不足，无法处理图像")
            self.failed.emit("内存不足，无法处理该图像")
        except Exception as exc:  # 兜底，保证异常不会吞在线程里
            logger.critical("图像处理过程中发生未处理异常", exc_info=True)
            self.failed.emit(str(exc))

class PipelineWorker(QObject):
    """ Moge 2.0 通用管线工作线程，携带任务 ID 防止旧结果覆盖新结果 """

    progress = pyqtSignal(int, int, str)  # task_id, 百分比, 状态
    finished = pyqtSignal(int, object)  # task_id, RenderResult
    failed = pyqtSignal(int, str)
    cancelled = pyqtSignal(int)

    def __init__(self, image, config, task_id: int = 0):
        super().__init__()
        self._image = image
        self._config = config
        self._task_id = int(task_id)
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def _should_cancel(self):
        return self._cancel_requested

    @pyqtSlot()
    def run(self):
        try:
            result = run_pipeline(
                self._image,
                self._config,
                progress=lambda value, message: self.progress.emit(self._task_id, value, message),
                should_cancel=self._should_cancel,
            )
            self.finished.emit(self._task_id, result)
        except ProcessingCancelled:
            logger.info("任务 %s 已取消", self._task_id)
            self.cancelled.emit(self._task_id)
        except MemoryError:
            logger.critical("任务 %s 内存不足", self._task_id)
            self.failed.emit(self._task_id, "内存不足，无法处理该图像")
        except Exception as exc:  # 兜底，保证异常不会吞在线程里
            logger.critical("任务 %s 处理失败", self._task_id, exc_info=True)
            self.failed.emit(self._task_id, str(exc))
