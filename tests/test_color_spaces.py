import numpy as np
import pytest
from Moge.core.color_spaces import (
    delta_e_00,
    delta_e_76,
    lab_to_rgb,
    nearest_lab_index,
    srgb_to_lab,
)


def test_lab_roundtrip_is_close():
    colors = np.array(
        [[255, 0, 0], [0, 255, 0], [0, 0, 255], [12, 34, 56], [200, 200, 200], [0, 0, 0], [255, 255, 255]],
        dtype=np.uint8,
    )
    rebuilt = lab_to_rgb(srgb_to_lab(colors))
    assert np.max(np.abs(rebuilt.astype(int) - colors.astype(int))) <= 1


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
        ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
        ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
        ((50.0, -1.3802, -84.2814), (50.0, 0.0, -82.7485), 1.0000),
        ((50.0, 0.0, 0.0), (50.0, -1.0, 2.0), 2.3669),
    ],
)
def test_delta_e_00_reference_pairs(first, second, expected):
    value = delta_e_00(np.array(first), np.array(second))
    assert value == pytest.approx(expected, abs=1e-4)


def test_delta_e_76_matches_lab_distance():
    first = np.array([[50.0, 0.0, 0.0], [60.0, 10.0, -5.0]])
    second = np.array([[50.0, 3.0, 4.0], [60.0, 10.0, -5.0]])
    assert np.allclose(delta_e_76(first, second), [5.0, 0.0])


def test_nearest_lab_index():
    palette = srgb_to_lab(np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.uint8))
    targets = srgb_to_lab(np.array([[250, 5, 5], [10, 240, 10]], dtype=np.uint8))
    assert np.array_equal(nearest_lab_index(palette, targets), [0, 1])
    assert nearest_lab_index(palette, targets[0]) == 0
