import numpy as np
import pytest
from Moge.core.image_processor import ResizeMode
from Moge.core.models import PixelMethod, ProcessingParams
from Moge.ui.worker import ProcessingWorker


def _params(method, block_size=4):
    return ProcessingParams(
        block_size=block_size,
        resize_mode=ResizeMode.FLOOR,
        pixel_method=method,
        n_clusters=4,
        seed=1,
    )


@pytest.mark.parametrize("method", [PixelMethod.MEAN, PixelMethod.MODE])
def test_worker_pipeline_emits_result(qapp, method):
    image = np.random.default_rng(7).integers(0, 256, (64, 64, 3), dtype=np.uint8)
    worker = ProcessingWorker(image, _params(method))

    results = {}
    worker.finished.connect(lambda img: results.setdefault("image", img))
    worker.failed.connect(lambda message: results.setdefault("error", message))
    worker.run()

    assert "error" not in results
    assert results["image"].shape == image.shape


def test_worker_reports_cancellation(qapp):
    worker = ProcessingWorker(np.zeros((128, 128, 3), np.uint8), _params(PixelMethod.MEAN))
    cancelled = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.cancel()
    worker.run()

    assert cancelled


def test_worker_reports_failure(qapp):
    worker = ProcessingWorker(np.zeros((16, 16, 3), np.uint8), _params(PixelMethod.MEAN, block_size=0))
    errors = []
    worker.failed.connect(errors.append)
    worker.run()

    assert errors
    assert "像素块大小" in errors[0]
