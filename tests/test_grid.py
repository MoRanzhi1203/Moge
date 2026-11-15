import numpy as np
import pytest
from Moge.core.grid import (
    ensure_rgb,
    isolated_cells,
    render_grid,
    sample_grid,
    upscale_grid,
)
from Moge.core.models import GridSpec, PaletteEntry, ResizeMode


def test_grid_spec_validation_and_derivation():
    with pytest.raises(ValueError):
        GridSpec(0, 10)
    spec = GridSpec.from_block_size((101, 199, 3), 8, ResizeMode.CEIL)
    assert (spec.width, spec.height) == (25, 13)
    floor = GridSpec.from_block_size((101, 199, 3), 8, ResizeMode.FLOOR)
    assert (floor.width, floor.height) == (24, 12)


def test_ensure_rgb_composites_alpha():
    image = np.zeros((2, 2, 4), np.uint8)
    image[..., :3] = 255
    image[..., 3] = 255
    image[0, 0, 3] = 0
    rgb, diagnostics = ensure_rgb(image)
    assert rgb.shape == (2, 2, 3)
    assert diagnostics["transparent_pixels"] == 1
    assert tuple(rgb[0, 0]) == (255, 255, 255)


@pytest.mark.parametrize("method", ["mean", "mode", "center", "edge"])
def test_sample_grid_methods(method):
    image = np.random.default_rng(1).integers(0, 256, (60, 80, 3), dtype=np.uint8)
    grid = sample_grid(image, GridSpec(20, 15), method)
    assert grid.shape == (15, 20, 3)


def test_render_grid_supports_transparency():
    entries = [
        PaletteEntry("a", "红", (255, 0, 0)),
        PaletteEntry("b", "蓝", (0, 0, 255)),
    ]
    labels = np.array([[0, -1], [1, 0]], dtype=np.int32)
    rgb = render_grid(labels, entries)
    rgba = render_grid(labels, entries, transparent=True)
    assert tuple(rgb[0, 0]) == (255, 0, 0)
    assert tuple(rgb[0, 1]) == (0, 0, 0)
    assert rgba.shape == (2, 2, 4)
    assert rgba[0, 1, 3] == 0
    assert rgba[0, 0, 3] == 255


def test_upscale_grid_repeats_cells():
    image = np.array([[[1, 2, 3], [4, 5, 6]]], dtype=np.uint8)
    assert upscale_grid(image, 2).shape == (2, 4, 3)


def test_isolated_cells_count():
    labels = np.array([[0, 0, 0], [0, 1, 0], [0, 0, 0]])
    assert isolated_cells(labels) == 1
    assert isolated_cells(np.zeros((3, 3), np.int32)) == 0
