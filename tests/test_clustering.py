import numpy as np
import pytest
from Moge.core.clustering import ALGORITHM_INFO, quantize
from Moge.core.models import ProcessingCancelled


@pytest.mark.parametrize("algorithm", list(ALGORITHM_INFO.keys()))
def test_quantize_is_deterministic(algorithm):
    pixels = np.random.default_rng(11).integers(0, 256, (48, 48, 3), dtype=np.uint8)
    first = quantize(pixels, 8, algorithm, seed=7)
    second = quantize(pixels, 8, algorithm, seed=7)
    assert np.array_equal(first.labels, second.labels)
    assert np.array_equal(first.centers_rgb, second.centers_rgb)
    assert len(first.centers_rgb) <= 8


def test_quantize_clamps_to_existing_colors():
    pixels = np.zeros((10, 10, 3), np.uint8)
    pixels[:5, :] = (255, 0, 0)
    pixels[5:, :] = (0, 255, 0)
    output = quantize(pixels, 16, "kmeans_lab", seed=1)
    assert len(output.centers_rgb) == 2
    assert output.diagnostics["requested_colors"] == 16
    assert output.diagnostics["actual_colors"] == 2


def test_quantize_rejects_invalid_arguments():
    pixels = np.zeros((4, 4, 3), np.uint8)
    with pytest.raises(ValueError):
        quantize(pixels, 0, "kmeans_lab")
    with pytest.raises(ValueError):
        quantize(pixels, 4, "not-an-algorithm")


def test_quantize_can_be_cancelled():
    pixels = np.random.default_rng(2).integers(0, 256, (32, 32, 3), dtype=np.uint8)
    with pytest.raises(ProcessingCancelled):
        quantize(pixels, 8, "kmeans_lab", should_cancel=lambda: True)
