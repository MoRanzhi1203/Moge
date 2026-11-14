import numpy as np
import pytest
from Moge.core.image_processor import (
    ProcessingCancelled,
    ResizeMode,
    color_clustering,
    img_pixelize_common,
    img_pixelize_mean,
    img_resize,
)


def _reference_mean(img, block_size):
    """ 改造前的逐块均值实现，用作回归基准 """
    h, w = img.shape[:2]
    processed = img.copy().astype(np.float32)
    for y in range(0, h, block_size):
        for x in range(0, w, block_size):
            y_end, x_end = min(y + block_size, h), min(x + block_size, w)
            processed[y:y_end, x:x_end] = np.mean(processed[y:y_end, x:x_end], axis=(0, 1))
    return processed.astype(np.uint8)


def _reference_mode(img, block_size):
    """ 改造前的逐像素频数实现，用作回归基准 """
    h, w = img.shape[:2]
    processed = img.copy().astype(np.float32)

    def mode_color(block):
        counter = {}
        for y in range(block.shape[0]):
            for x in range(block.shape[1]):
                pixel = tuple(block[y, x][:3])
                counter[pixel] = counter.get(pixel, 0) + 1
        return max(counter, key=counter.get)

    for i in range(0, w, block_size):
        for j in range(0, h, block_size):
            region = img[j:min(j + block_size, h), i:min(i + block_size, w)]
            processed[j:min(j + block_size, h), i:min(i + block_size, w)] = mode_color(region)
    return processed.astype(np.uint8)


@pytest.mark.parametrize(
    ("mode", "expected_shape"),
    [
        (ResizeMode.CEIL, (1008, 2000, 3)),
        (ResizeMode.FLOOR, (1000, 1992, 3)),
        (ResizeMode.ROUND, (1000, 2000, 3)),
    ],
)
def test_resize_modes(mode, expected_shape):
    image = np.zeros((1001, 1999, 3), np.uint8)
    assert img_resize(image, 8, mode).shape == expected_shape


def test_resize_accepts_mode_name():
    image = np.zeros((1001, 1999, 3), np.uint8)
    assert img_resize(image, 8, "四舍五入").shape == (1000, 2000, 3)


@pytest.mark.parametrize("block_size", [0, -1])
def test_resize_rejects_invalid_block_size(block_size):
    with pytest.raises(ValueError):
        img_resize(np.zeros((10, 10, 3), np.uint8), block_size, ResizeMode.CEIL)


def test_resize_rejects_unknown_mode():
    with pytest.raises(ValueError):
        img_resize(np.zeros((16, 16, 3), np.uint8), 4, 0)


@pytest.mark.parametrize(
    ("shape", "block_size"),
    [((64, 64, 3), 8), ((120, 95, 3), 5), ((66, 63, 3), 3)],
)
def test_pixelize_mean_matches_reference(shape, block_size):
    image = np.random.default_rng(1).integers(0, 256, shape, dtype=np.uint8)
    np.testing.assert_array_equal(
        img_pixelize_mean(image, block_size), _reference_mean(image, block_size)
    )


@pytest.mark.parametrize(("shape", "block_size"), [((64, 64, 3), 8), ((48, 48, 3), 4)])
def test_pixelize_mode_matches_reference(shape, block_size):
    image = np.random.default_rng(2).integers(0, 256, shape, dtype=np.uint8)
    np.testing.assert_array_equal(
        img_pixelize_common(image, block_size), _reference_mode(image, block_size)
    )


def test_pixelize_handles_non_aligned_size():
    image = np.random.default_rng(3).integers(0, 256, (101, 199, 3), dtype=np.uint8)
    assert img_pixelize_mean(image, 8).shape == image.shape
    assert img_pixelize_common(image, 8).shape == image.shape


def test_pixelize_mean_rejects_invalid_block_size():
    with pytest.raises(ValueError):
        img_pixelize_mean(np.zeros((16, 16, 3), np.uint8), 0)


def test_pixelize_mode_can_be_cancelled():
    calls = {"count": 0}

    def should_cancel():
        calls["count"] += 1
        return calls["count"] > 1

    with pytest.raises(ProcessingCancelled):
        img_pixelize_common(np.zeros((512, 512, 3), np.uint8), 8, should_cancel=should_cancel)


def test_pixelize_mode_reports_progress():
    seen = []
    img_pixelize_common(np.zeros((64, 64, 3), np.uint8), 8, progress_callback=seen.append)
    assert seen
    assert seen[-1] == pytest.approx(1.0)


def test_cluster_limits_color_count():
    image = np.random.default_rng(4).integers(0, 256, (48, 48, 3), dtype=np.uint8)
    result = color_clustering(image, 4, 42)
    assert result.shape == image.shape
    assert len(np.unique(result.reshape(-1, 3), axis=0)) <= 4


def test_cluster_is_deterministic():
    image = np.random.default_rng(5).integers(0, 256, (64, 64, 3), dtype=np.uint8)
    np.testing.assert_array_equal(color_clustering(image, 8, 7), color_clustering(image, 8, 7))


def test_cluster_returns_input_when_colors_within_limit():
    image = np.zeros((16, 16, 3), np.uint8)
    image[:, :8] = (255, 0, 0)
    np.testing.assert_array_equal(color_clustering(image, 4, 0), image)


def test_cluster_rejects_invalid_color_count():
    with pytest.raises(ValueError):
        color_clustering(np.zeros((16, 16, 3), np.uint8), 0, 0)


def test_cluster_can_be_cancelled():
    image = np.random.default_rng(6).integers(0, 256, (256, 256, 3), dtype=np.uint8)
    with pytest.raises(ProcessingCancelled):
        color_clustering(image, 8, 1, should_cancel=lambda: True)
