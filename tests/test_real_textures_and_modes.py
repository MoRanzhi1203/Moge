import os
from pathlib import Path

import numpy as np
import pytest
from Moge.core.document import GridDocument
from Moge.core.models import GridSpec, PaletteEntry

REAL_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Moge" / "resources"
HAS_REAL_RESOURCES = (REAL_ROOT / "index.db").is_file()


def _use_real_resources(monkeypatch):
    from Moge.core.modes import minecraft as minecraft_mode

    monkeypatch.setenv("MOGE_RESOURCE_DIR", str(REAL_ROOT))
    minecraft_mode._REAL_CATALOG_CACHE.clear()


def _document(labels=None):
    spec = GridSpec(4, 3)
    entries = [
        PaletteEntry(id="stone", name="石头", rgb=(125, 125, 125)),
        PaletteEntry(id="oak_planks", name="橡木木板", rgb=(162, 130, 78)),
    ]
    if labels is None:
        labels = np.zeros((3, 4), dtype=np.int32)
    return GridDocument(spec=spec, mode="minecraft", labels=labels, entries=entries)


def test_grid_document_undo_redo_and_lock():
    document = _document()
    document.push_history()
    document.labels[0, 0] = 1
    assert document.can_undo
    assert document.undo()
    assert document.labels[0, 0] == 0
    assert document.can_redo
    assert document.redo()
    assert document.labels[0, 0] == 1

    assert document.toggle_lock(1, 1) is True
    assert document.is_locked(1, 1)
    document.set_selection((0, 0), (1, 1))
    assert document.selection == (0, 0, 1, 1)
    document.lock_selection(True)
    assert document.locked[0:2, 0:2].all()
    document.clear_selection()
    assert document.selection is None


@pytest.mark.skipif(not HAS_REAL_RESOURCES, reason="本机没有真实资源索引库")
def test_java_1201_records_are_traceable(monkeypatch):
    _use_real_resources(monkeypatch)
    from Moge.core.resources.database import ResourceDatabase
    from Moge.core.resources.paths import database_path

    database = ResourceDatabase(database_path())
    row = database.get_version("java", "1.20.1")
    assert row is not None and row["status"] == "ready"
    blocks = database.get_blocks("java", "1.20.1")
    coverage = database.block_coverage("java", "1.20.1")
    database.close()

    assert coverage["total_blocks"] == len(blocks)
    assert coverage["textured_blocks"] > 500
    assert coverage["full_cube_blocks"] > 200
    sample = next(block for block in blocks if block["block_id"] == "stone")
    face = sample["faces"]["all"]
    assert sample["edition"] == "java" and sample["version"] == "1.20.1"
    assert face["sha256"] and face["path"] and Path(face["path"]).is_file()
    assert sample["verified"] == 1
    assert sample["source_hash"]
    assert sample["geometry"] == "full_cube"


@pytest.mark.skipif(not HAS_REAL_RESOURCES, reason="本机没有真实资源索引库")
def test_geometry_filter_excludes_partial_blocks(monkeypatch):
    _use_real_resources(monkeypatch)
    from Moge.core.modes import minecraft as minecraft_mode

    settings = dict(minecraft_mode.MC_DEFAULTS)
    settings.update({"edition": "java", "version": "1.20.1", "resource_mode": "auto"})
    candidates = minecraft_mode.candidate_blocks(settings)
    ids = {block.block_id for block in candidates}

    for excluded in ("glass_pane", "end_rod", "redstone_wire", "oak_slab", "oak_stairs", "torch"):
        assert excluded not in ids
    for included in ("stone", "glass", "oak_planks", "white_concrete"):
        assert included in ids
    assert all(block.geometry == "full_cube" for block in candidates)


@pytest.mark.skipif(not HAS_REAL_RESOURCES, reason="本机没有真实资源索引库")
def test_texture_renderer_uses_real_png(monkeypatch):
    _use_real_resources(monkeypatch)
    from Moge.core.modes import minecraft as minecraft_mode
    from Moge.core.render import render_textured

    settings = dict(minecraft_mode.MC_DEFAULTS)
    settings.update({"edition": "java", "version": "1.20.1", "resource_mode": "auto"})
    candidates = minecraft_mode.candidate_blocks(settings)
    stone = next(block for block in candidates if block.block_id == "stone")
    assert stone.texture_path and Path(stone.texture_path).is_file()

    entries = [
        PaletteEntry(
            id=stone.block_id,
            name=stone.name,
            rgb=stone.rgb,
            meta={"texture_path": stone.texture_path},
        )
    ]
    labels = np.zeros((2, 3), dtype=np.int32)
    image = render_textured(labels, entries, cell_pixels=16)
    assert image.shape == (32, 48, 4)
    assert image[..., 3].all()
    unique_pixels = np.unique(image[..., :3].reshape(-1, 3), axis=0)
    assert len(unique_pixels) > 1  # 真实贴图包含纹理细节，不是单色填充


@pytest.mark.skipif(not HAS_REAL_RESOURCES, reason="本机没有真实资源索引库")
def test_minecraft_pipeline_reports_split_coverage(monkeypatch):
    _use_real_resources(monkeypatch)
    from Moge.core.modes import minecraft as minecraft_mode
    from Moge.core.pipeline import run_pipeline

    image = np.random.default_rng(0).integers(0, 256, (120, 160, 4), dtype=np.uint8)
    image[..., 3] = 255
    config = minecraft_mode.build_config(
        GridSpec(16, 12),
        {"edition": "java", "version": "1.20.1", "resource_mode": "auto"},
    )
    result = run_pipeline(image, config)
    stats = result.stats
    assert stats["resource_source"] == "mojang-resource"
    for key in ("vanilla_coverage", "renderable_coverage", "pack_coverage"):
        payload = stats[key]
        assert payload["denominator"] > 0
        assert 0 <= payload["numerator"] <= payload["denominator"]
    assert stats["vanilla_coverage"]["numerator"] > 500
    assert all(entry.meta["texture"] == "real" for entry in result.grid.entries)
    assert all(entry.meta["texture_path"] for entry in result.grid.entries)


def test_canvas_view_mode_never_edits(qapp):
    from Moge.ui.canvas import GridCanvas
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest

    canvas = GridCanvas()
    canvas.resize(420, 320)
    canvas.set_image(np.zeros((10, 10, 3), dtype=np.uint8), (10, 10))
    canvas.set_editable(True)
    canvas.show()
    qapp.processEvents()

    pressed, inspected = [], []
    canvas.cellPressed.connect(lambda col, row: pressed.append((col, row)))
    canvas.cellInspected.connect(lambda col, row: inspected.append((col, row)))

    canvas.set_interaction_mode("view")
    QTest.mouseClick(canvas, Qt.LeftButton, pos=canvas.rect().center())
    qapp.processEvents()
    assert pressed == []
    assert inspected

    canvas.set_interaction_mode("edit")
    QTest.mouseClick(canvas, Qt.LeftButton, pos=canvas.rect().center())
    qapp.processEvents()
    assert pressed
    canvas.close()


@pytest.mark.skipif(not HAS_REAL_RESOURCES, reason="本机没有真实资源索引库")
def test_gui_preview_switch_does_not_change_stats(qapp, monkeypatch, wait_pipeline):
    from Moge.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QMessageBox

    _use_real_resources(monkeypatch)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    window = MainWindow()
    window.original_img = np.random.default_rng(1).integers(0, 256, (96, 128, 4), dtype=np.uint8)
    window.original_img[..., 3] = 255
    window.grid_width.setValue(12)
    window.grid_height.setValue(9)
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("minecraft"))
    window.apply_processing()
    wait_pipeline(window)

    result = window.results["minecraft"]
    assert result.stats["resource_source"] == "mojang-resource"
    counts_before = dict(result.stats["counts"])
    labels_before = result.grid.labels.copy()

    assert window.act_preview_texture.isEnabled()
    window.act_preview_texture.trigger()
    assert window.preview_style == "texture"
    assert result.stats["counts"] == counts_before
    assert np.array_equal(result.grid.labels, labels_before)
    image = window.canvas.image()
    assert image is not None
    assert image.height() == result.grid.spec.height * 16

    window.act_preview_solid.trigger()
    assert window.canvas.image().height() == result.grid.spec.height
    window.close()


@pytest.mark.skipif(not HAS_REAL_RESOURCES, reason="本机没有真实资源索引库")
def test_gui_edit_lock_and_project_roundtrip(qapp, tmp_path, monkeypatch, wait_pipeline):
    from Moge.exporters.project import load_project, save_project
    from Moge.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QMessageBox

    _use_real_resources(monkeypatch)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    window = MainWindow()
    window.original_img = np.random.default_rng(2).integers(0, 256, (64, 64, 4), dtype=np.uint8)
    window.original_img[..., 3] = 255
    window.grid_width.setValue(8)
    window.grid_height.setValue(6)
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("pixel"))
    window.apply_processing()
    wait_pipeline(window)

    window.act_edit_mode.trigger()
    result = window.results["pixel"]
    window.tool = "paint"
    window.selected_entry = min(1, len(result.grid.entries) - 1)
    window._on_stroke_started()
    window._on_cell_pressed(1, 1)
    assert result.grid.labels[1, 1] == window.selected_entry

    # 锁定后再次编辑不改变数据
    painted = int(result.grid.labels[1, 1])
    window.tool = "lock"
    window._on_stroke_started()
    window._on_cell_pressed(1, 1)
    assert window.documents["pixel"].is_locked(1, 1)
    window.tool = "paint"
    window.selected_entry = 0
    window._on_stroke_started()
    window._on_cell_pressed(1, 1)
    assert int(result.grid.labels[1, 1]) == painted

    path = tmp_path / "roundtrip.moge"
    save_project(str(path), result, None)
    loaded = load_project(str(path))
    assert loaded.grid is not None
    assert np.array_equal(loaded.grid.labels, result.grid.labels)
    window.close()
