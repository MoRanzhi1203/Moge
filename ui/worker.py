##############################
# ui/worker.py - 图像处理工作线程
##############################

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from Moge.core.models import ProcessingCancelled
from Moge.core.pipeline import run_pipeline
from Moge.utils.logger_config import get_module_logger

logger = get_module_logger(__name__)


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
