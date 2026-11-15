import numpy as np
import pytest
from Moge.core.models import GridSpec, ProcessingCancelled
from Moge.core.modes import registry
from Moge.core.pipeline import run_pipeline


def _image(seed: int = 3, size=(64, 80)) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, (*size, 3), dtype=np.uint8)


def _run(mode: str, spec: GridSpec, settings=None, image=None):
    image = _image() if image is None else image
    config = registry.build_config(mode, spec, settings or registry.default_settings(mode), image)
    return run_pipeline(image, config)


def test_pixel_pipeline_is_deterministic_and_valid():
    spec = GridSpec(24, 20)
    first = _run("pixel", spec)
    second = _run("pixel", spec)

    assert np.array_equal(first.grid.labels, second.grid.labels)
    assert first.grid.validate()
    assert first.image.shape == (20, 24, 4)
    assert first.stats["filled_cells"] == 24 * 20
    assert sum(first.stats["counts"].values()) == first.stats["filled_cells"]


def test_minecraft_pipeline_respects_version_and_legality():
    settings = dict(registry.default_settings("minecraft"))
    settings.update({"version": "1.12.2", "categories": ["concrete"]})
    result = _run("minecraft", GridSpec(20, 16), settings)

    entry_ids = {entry.id for entry in result.grid.entries}
    assert "deepslate" not in entry_ids
    assert all(entry.id.startswith(("white_", "orange_", "magenta_", "light_", "yellow_", "lime_",
                                   "pink_", "gray_", "cyan_", "purple_", "blue_", "brown_", "green_",
                                   "red_", "black_")) for entry in result.grid.entries)
    assert result.stats["legal_rate"] == 1.0
    assert result.stats["version"] == "1.12.2"
    assert result.image.shape == (16, 20, 3)


def test_beads_pipeline_board_counts_match_grid():
    spec = GridSpec(32, 24)
    result = _run("beads", spec)

    assert all(entry.id.startswith("bead:") for entry in result.grid.entries)
    assert result.stats["boards"] == 2
    assert sum(board["beads"] for board in result.stats["board_stats"]) == result.stats["total_beads"]
    assert result.stats["total_beads"] == 32 * 24


def test_pipeline_can_be_cancelled():
    image = _image()
    config = registry.build_config("pixel", GridSpec(16, 16), registry.default_settings("pixel"), image)
    with pytest.raises(ProcessingCancelled):
        run_pipeline(image, config, should_cancel=lambda: True)


def test_pipeline_reports_monotonic_progress():
    updates = []

    def progress(value, message):
        updates.append(value)

    image = _image()
    config = registry.build_config("pixel", GridSpec(16, 16), registry.default_settings("pixel"), image)
    run_pipeline(image, config, progress=progress)

    assert updates
    assert updates == sorted(updates)
    assert updates[-1] >= 90


def test_smooth_preset_reduces_or_keeps_isolated_cells():
    settings = dict(registry.default_settings("pixel"))
    settings.update({"preset": "custom", "optimize": False})
    baseline = _run("pixel", GridSpec(24, 24), settings)

    settings = dict(settings)
    settings.update({"preset": "smooth", "optimize": True})
    smoothed = _run("pixel", GridSpec(24, 24), settings)

    assert smoothed.stats["isolated_cells"] <= baseline.stats["isolated_cells"]
