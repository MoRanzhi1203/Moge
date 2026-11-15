import math

import numpy as np
import pytest
from Moge.core.materials import filter_blocks, load_bead_inventory_csv
from Moge.core.models import GridSpec
from Moge.core.modes import registry
from Moge.core.pipeline import run_pipeline
from Moge.exporters.csv import material_rows
from Moge.ui.canvas import GridCanvas
from Moge.ui.main_window import MainWindow


def test_filter_blocks_orientation_transparency_gravity():
    axis_only = filter_blocks("1.20.1", orientation="axis")
    assert axis_only
    assert all(block.orientation == "axis" for block in axis_only)

    no_transparent = filter_blocks("1.20.1", exclude_transparent=True)
    assert no_transparent
    assert all(not block.transparent for block in no_transparent)

    no_gravity = filter_blocks("1.20.1", exclude_gravity=True)
    assert no_gravity
    assert all(not block.gravity for block in no_gravity)


def test_minecraft_pipeline_carries_orientation_metadata():
    image = np.random.default_rng(2).integers(0, 256, (32, 32, 3), dtype=np.uint8)
    settings = dict(registry.default_settings("minecraft"))
    settings["orientation"] = "axis"
    result = run_pipeline(image, registry.build_config("minecraft", GridSpec(16, 16), settings))
    assert result.grid.entries
    assert all(entry.meta["orientation"] == "axis" for entry in result.grid.entries)
    assert all(entry.meta["visible_face"] in ("all", "top", "side", "front") for entry in result.grid.entries)


def test_load_bead_inventory_csv(tmp_path):
    path = tmp_path / "inventory.csv"
    path.write_text(
        "brand,series,code,quantity\n"
        "Generic,Approx,G01,50\n"
        "Generic,Approx,G02,0\n"
        "Generic,Approx,G03,-3\n",
        encoding="utf-8",
    )
    inventory, errors = load_bead_inventory_csv(str(path))
    assert inventory["bead:Generic:Approx:G01"] == 50
    assert inventory["bead:Generic:Approx:G02"] == 0
    assert len(errors) == 1


def test_beads_purchase_packs_and_csv_column():
    image = np.random.default_rng(3).integers(0, 256, (32, 32, 3), dtype=np.uint8)
    settings = dict(registry.default_settings("beads"))
    settings["pack_size"] = 500
    result = run_pipeline(image, registry.build_config("beads", GridSpec(16, 16), settings))

    expected = sum(math.ceil(count / 500) for count in result.stats["counts"].values())
    assert result.stats["pack_size"] == 500
    assert result.stats["packs_required"] == expected
    for row in material_rows(result):
        assert row["packs"] == math.ceil(row["count"] / 500)


def test_empty_material_set_raises():
    image = np.full((16, 16, 3), 120, np.uint8)
    settings = dict(registry.default_settings("minecraft"))
    settings["categories"] = ["not-a-real-category"]
    with pytest.raises(ValueError):
        run_pipeline(image, registry.build_config("minecraft", GridSpec(8, 8), settings))


def test_beads_inventory_restricts_candidates():
    from Moge.core.materials import BEAD_CATALOG

    image = np.random.default_rng(4).integers(0, 256, (24, 24, 3), dtype=np.uint8)
    settings = dict(registry.default_settings("beads"))
    settings.update(
        {
            "catalog": list(BEAD_CATALOG),
            "brand": "Generic",
            "series": "Approx",
            "inventory_ids": ["bead:Generic:Approx:G01"],
        }
    )
    result = run_pipeline(image, registry.build_config("beads", GridSpec(12, 12), settings))
    assert {entry.id for entry in result.grid.entries} == {"bead:Generic:Approx:G01"}
    assert all(entry.id == "bead:Generic:Approx:G01" for entry in result.grid.entries)


def test_canvas_compare_center_and_reset(qapp):
    canvas = GridCanvas()
    canvas.resize(400, 300)
    image = np.zeros((10, 12, 3), np.uint8)
    reference = np.full((10, 12, 3), 200, np.uint8)
    canvas.set_image(image, (12, 10))
    canvas.set_reference_image(reference)

    canvas.set_compare_enabled(True)
    assert canvas.compare_enabled()
    canvas.set_compare_enabled(False)
    assert not canvas.compare_enabled()

    canvas.center_on_cell(6, 5)
    canvas.reset_view()
    assert canvas.cell_at(canvas.rect().center()) is not None


def test_workbench_layout_and_palette_filters(qapp, monkeypatch):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    window = MainWindow()
    window.resize(900, 620)
    window.show()
    qapp.processEvents()

    assert window.left_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert window.palette_list.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert window.right_tabs.isVisible()
    assert window.right_tabs.width() >= 220
    assert window.canvas.width() >= 280
    assert window.left_content.minimumSizeHint().width() <= window.left_scroll.viewport().width()
    assert window.px_algorithm.findData("spectral_lab") == -1

    for mode in ("pixel", "minecraft", "beads"):
        window.mode_combo.setCurrentIndex(window.mode_combo.findData(mode))
        qapp.processEvents()
        panel = window.mode_stack.currentWidget()
        assert panel.minimumSizeHint().width() <= window.left_scroll.viewport().width()

    window.mode_combo.setCurrentIndex(window.mode_combo.findData("pixel"))
    window.original_img = np.random.default_rng(0).integers(0, 256, (32, 32, 4), dtype=np.uint8)
    window.original_img[..., 3] = 255
    window.grid_width.setValue(16)
    window.grid_height.setValue(16)
    window.apply_processing()
    from PyQt5.QtCore import QEventLoop, QTimer

    loop = QEventLoop()

    def poll():
        if window._thread is None:
            loop.quit()
        else:
            QTimer.singleShot(30, poll)

    QTimer.singleShot(30, poll)
    QTimer.singleShot(15000, loop.quit)
    loop.exec_()
    assert window._thread is None

    result = window.results["pixel"]
    window.palette_used_only.setChecked(True)
    assert window.palette_list.count() == result.stats["used_entries"]

    first_name = result.grid.entries[0].name
    from PyQt5.QtTest import QTest

    window.palette_search.setText(first_name)
    QTest.qWait(250)  # 搜索输入带防抖延迟
    assert window.palette_list.count() >= 1
    window.palette_search.clear()
    QTest.qWait(250)
    window.palette_used_only.setChecked(False)
    assert window.palette_list.count() == len(result.grid.entries)

    window.act_sidebar.setChecked(False)
    assert not window.right_tabs.isVisible()
    window.act_sidebar.setChecked(True)
    assert window.right_tabs.isVisible()
    window.close()
