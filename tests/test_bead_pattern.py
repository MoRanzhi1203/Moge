##############################
# tests/test_bead_pattern.py - 拼豆施工图坐标/标记/图例/底板/工程读写
##############################

from pathlib import Path

import numpy as np
import pytest
from Moge.core.beads.pattern import (
    bead_summary,
    board_regions,
    board_stats,
    build_cells,
    legend_rows,
    symbol_for_index,
)
from Moge.core.models import GridSpec, PaletteEntry
from Moge.core.modes import registry
from Moge.core.pipeline import run_pipeline
from Moge.exporters.bead_sheet import BeadSheetOptions, export_bead_png
from Moge.exporters.legend_sheet import LegendSheetOptions, export_legend_png
from Moge.exporters.project import load_project, save_project
from Moge.ui.canvas import GridCanvas
from Moge.ui.main_window import MainWindow
from PyQt5.QtCore import QSize
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QFileDialog, QListView


def _bead_result(width=16, height=16, seed=7, transparent=False):
    image = np.random.default_rng(seed).integers(0, 256, (height * 2, width * 2, 4), dtype=np.uint8)
    image[..., 3] = 255
    if transparent:
        image[:, :width, 3] = 0
    config = registry.build_config("beads", GridSpec(width, height), registry.default_settings("beads"), image)
    return run_pipeline(image, config)


def _entries():
    return [
        PaletteEntry(
            id="bead:Test:Series:W01",
            name="白",
            rgb=(245, 245, 240),
            source="test",
            meta={"brand": "Test", "series": "Series", "code": "W01", "material": "solid"},
        ),
        PaletteEntry(
            id="bead:Test:Series:B01",
            name="黑",
            rgb=(20, 20, 20),
            source="test",
            meta={"brand": "Test", "series": "Series", "code": "B01", "material": "solid"},
        ),
        PaletteEntry(
            id="bead:Test:Series:T01",
            name="透明",
            rgb=(180, 210, 230),
            source="test",
            meta={"brand": "Test", "series": "Series", "code": "T01", "material": "transparent"},
        ),
    ]


def test_canvas_axis_alignment_and_guides(qapp):
    canvas = GridCanvas()
    canvas.resize(900, 700)
    canvas.set_image(np.zeros((20, 20, 3), dtype=np.uint8), (20, 20))
    canvas.configure_beads(
        {
            "view_mode": "blueprint",
            "axis_x": True,
            "axis_y": True,
            "coordinate_numbers": True,
            "coordinate_step": 1,
            "grid": True,
            "guide5": True,
            "guide10": True,
        }
    )
    canvas.fit_to_view()
    qapp.processEvents()

    rect = canvas.cell_rect(0, 0)
    cell = rect.width()
    ticks = canvas.axis_tick_positions("x")
    assert [index for index, _position in ticks] == list(range(20))
    for index, position in ticks:
        assert position == pytest.approx(rect.left() + (index + 0.5) * cell)

    guides_5 = canvas.guide_line_positions("x", 5)
    assert guides_5 == pytest.approx([rect.left() + index * cell for index in (5, 10, 15)])
    guides_10 = canvas.guide_line_positions("y", 10)
    assert guides_10 == pytest.approx([rect.top() + index * cell for index in (10,)])


def test_blank_cells_are_not_white_beads():
    entries = _entries()
    labels = np.array([[0, -1], [1, -1]], dtype=np.int32)
    summary = bead_summary(labels, entries)
    assert summary["total_beads"] == 2
    assert summary["empty_cells"] == 2
    assert summary["white_beads"] == 1

    rows = {row["code"]: row for row in legend_rows(labels, entries, include_unused=False)}
    assert set(rows) == {"W01", "B01"}
    assert rows["W01"]["count"] == 1
    assert rows["W01"]["ratio"] == pytest.approx(0.5)
    assert rows["W01"]["symbol"]

    cells = build_cells(labels, entries)
    assert len(cells) == 4
    assert cells[0]["is_empty"] is False and cells[0]["code"] == "W01"
    assert cells[1]["is_empty"] is True and cells[1]["bead_id"] == ""
    assert cells[3]["is_empty"] is True


def test_transparent_material_flags_and_symbol_uniqueness():
    entries = _entries()
    labels = np.array([[2, 2], [0, 1]], dtype=np.int32)
    summary = bead_summary(labels, entries)
    assert summary["transparent_beads"] == 2
    assert summary["special_beads"] == 2
    cells = build_cells(labels, entries)
    assert cells[0]["material"] == "transparent"
    assert cells[0]["transparent"] is True
    assert cells[0]["special"] is True

    symbols = [symbol_for_index(index) for index in range(220)]
    assert len(set(symbols)) == len(symbols)


def test_board_regions_and_board_stats():
    regions = board_regions(60, 60, 29, 29)
    assert [region["label"] for region in regions] == [
        "A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3",
    ]
    assert (regions[0]["x0"], regions[0]["y0"], regions[0]["x1"], regions[0]["y1"]) == (0, 0, 29, 29)
    assert (regions[-1]["x0"], regions[-1]["y0"], regions[-1]["x1"], regions[-1]["y1"]) == (58, 58, 60, 60)

    labels = np.full((60, 60), -1, dtype=np.int32)
    labels[0, 0] = 0
    stats = board_stats(labels, 29, 29)
    assert stats[0]["beads"] == 1
    assert stats[0]["empty"] == 29 * 29 - 1
    assert stats[1]["beads"] == 0


def test_pipeline_keeps_transparent_cells_blank():
    image = np.full((32, 32, 4), 200, dtype=np.uint8)
    image[..., 3] = 255
    image[:, :16, 3] = 0
    result = run_pipeline(
        image,
        registry.build_config("beads", GridSpec(16, 16), registry.default_settings("beads"), image),
    )
    assert result.grid.labels.shape == (16, 16)
    assert int(np.count_nonzero(result.grid.labels < 0)) == 128
    assert result.stats["empty_cells"] == 128
    assert result.stats["total_beads"] == 128
    assert result.image.shape[2] == 4
    assert np.all(result.image[:, :8, 3] == 0)


def test_project_roundtrip_preserves_cell_metadata(tmp_path):
    result = _bead_result(8, 8, transparent=True)
    locked = np.zeros_like(result.grid.labels, dtype=bool)
    locked[0, 0] = True
    path = save_project(str(tmp_path / "beads.moge"), result, "source.png", locked=locked)
    document = load_project(path)
    grid = document.grid
    assert grid is not None
    assert np.array_equal(grid.labels, result.grid.labels)
    assert len(grid.cells) == grid.spec.width * grid.spec.height
    assert grid.symbols
    assert grid.cells[0]["locked"] is True
    non_empty = [cell for cell in grid.cells if not cell["is_empty"]]
    empty = [cell for cell in grid.cells if cell["is_empty"]]
    assert non_empty and empty
    cell = non_empty[0]
    for key in ("x", "y", "bead_id", "brand", "series", "code", "name", "rgb", "hex", "symbol", "is_empty"):
        assert key in cell
    entry_by_id = {entry.id: entry for entry in grid.entries}
    assert cell["code"] == entry_by_id[cell["bead_id"]].meta.get("code")
    assert cell["symbol"] == grid.symbols[cell["bead_id"]]
    assert empty[0]["bead_id"] == ""


def test_legend_sort_rules_are_explicit(qapp):
    entries = [
        PaletteEntry(
            id=f"bead:Sort:Series:{code}",
            name=f"Sort Series {code}",
            rgb=(index * 20 % 255, 80, 120),
            meta={"brand": "Sort", "series": "Series", "code": code},
        )
        for index, code in enumerate(("A10", "A2", "B1", "A1"))
    ]
    window = MainWindow()
    window.palette_sort.setCurrentIndex(window.palette_sort.findData("code"))
    rows = window._palette_rows(entries, {}, False)
    assert [row[1].meta["code"] for row in rows] == ["A1", "A2", "A10", "B1"]

    counts = {
        entries[0].id: 5,
        entries[1].id: 3,
        entries[2].id: 1,
    }
    window.palette_sort.setCurrentIndex(window.palette_sort.findData("count"))
    rows = window._palette_rows(entries, counts, False)
    assert [row[1].meta["code"] for row in rows] == ["A10", "A2", "B1", "A1"]
    window.close()


def test_legend_layout_adapts_columns(qapp):
    window = MainWindow()
    window.resize(1800, 1000)
    window.show()
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("beads"))
    qapp.processEvents()

    window.splitter.setSizes([320, 760, 700])
    window._apply_legend_layout()
    qapp.processEvents()
    assert window.palette_list.viewMode() == QListView.IconMode
    assert window.palette_list.gridSize().width() >= 250
    first = window.palette_list.visualItemRect(window.palette_list.item(0))
    second = window.palette_list.visualItemRect(window.palette_list.item(1))
    assert first.y() == second.y()
    assert first.x() != second.x()
    assert window.palette_list.item(0).sizeHint().height() >= 40

    window.splitter.setSizes([320, 1050, 220])
    window._apply_legend_layout()
    qapp.processEvents()
    assert window.palette_list.viewMode() == QListView.ListMode
    window.close()


def test_all_color_legend_without_image(qapp):
    window = MainWindow()
    window.resize(900, 660)
    window.show()
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("beads"))
    qapp.processEvents()
    assert window.bead_brand.count() >= 1
    assert window.bead_series.count() >= 1
    expected = len(window._bead_catalog_entries())
    assert expected > 0
    assert window.palette_list.count() == expected
    assert "全部色卡" in window.palette_note.text()

    first = window.palette_list.item(0)
    assert first.sizeHint().height() >= QSize(0, 40).height()
    assert "符号" in first.text() or "Series" in first.text()
    assert window.btn_export_legend.isEnabled()
    window.close()


def test_legend_png_export(qapp, tmp_path):
    rows = [
        {
            "primary": "A01 白",
            "secondary": "MARD · 221 · 符号 0",
            "count_text": "×120 · 40.0%",
            "used": True,
            "rgb": (245, 245, 240),
            "transparent": False,
            "special": False,
        },
        {
            "primary": "A02 黑",
            "secondary": "MARD · 221 · 符号 1",
            "count_text": "×60 · 20.0%",
            "used": True,
            "rgb": (20, 20, 20),
            "transparent": False,
            "special": False,
        },
        {
            "primary": "T01 透明蓝",
            "secondary": "MARD · 221 · 透明 · 符号 2",
            "count_text": "×30 · 10.0%",
            "used": True,
            "rgb": (140, 190, 220),
            "transparent": True,
            "special": True,
        },
        {
            "primary": "A10 未使用颜色",
            "secondary": "MARD · 221 · 符号 3",
            "count_text": "未使用",
            "used": False,
            "rgb": (120, 80, 160),
            "transparent": False,
            "special": False,
        },
    ]
    path = export_legend_png(
        rows,
        str(tmp_path / "legend.png"),
        LegendSheetOptions(
            title="测试图例",
            subtitle="MARD 221 · 全部颜色 · 4 色 · 排序：用量（多→少）",
            theme="light",
            columns=2,
            width=700,
        ),
    )
    data = Path(path).read_bytes()
    assert data[:4] == b"\x89PNG"
    image = QImage(path)
    assert image.width() >= 1400
    assert image.height() > 200


def test_legend_export_button_writes_png(qapp, tmp_path, monkeypatch):
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("beads"))
    qapp.processEvents()
    assert window.btn_export_legend.isEnabled()

    target = tmp_path / "panel-legend.png"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(target), "PNG 图片 (*.png)")),
    )
    window.export_legend_png_file()
    assert target.is_file()
    assert target.read_bytes()[:4] == b"\x89PNG"
    window.close()


def test_view_switch_does_not_reprocess(qapp, wait_pipeline, monkeypatch):
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    window = MainWindow()
    window.resize(900, 660)
    window.show()
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("beads"))
    image = np.random.default_rng(3).integers(0, 256, (32, 32, 4), dtype=np.uint8)
    image[..., 3] = 255
    window.original_img = image
    window.grid_width.setValue(16)
    window.grid_height.setValue(16)
    window.apply_processing()
    wait_pipeline(window)

    result = window.results["beads"]
    labels_before = result.grid.labels.copy()
    task_before = window._task_counter
    result_before = result

    for preset in ("blueprint", "mono", "preview", "legend"):
        window._apply_bead_preset(preset)
        qapp.processEvents()
        assert window._task_counter == task_before
        assert window.results["beads"] is result_before
        assert np.array_equal(result.grid.labels, labels_before)
        assert window.bead_view_mode == preset

    assert window.center_stack.currentWidget() is window.legend_page
    window._apply_bead_preset("preview")
    qapp.processEvents()
    assert window.center_stack.currentWidget() is window.canvas
    assert window.canvas.bead_options()["view_mode"] == "preview"
    window.close()


def test_bead_png_export_modes(qapp, tmp_path):
    result = _bead_result(10, 10)
    for mode in ("preview", "blueprint", "mono"):
        path = export_bead_png(
            result,
            str(tmp_path / f"{mode}.png"),
            BeadSheetOptions(mode=mode, cell_size=18, show_legend=mode != "preview"),
        )
        data = Path(path).read_bytes()
        assert data[:4] == b"\x89PNG"
    preview_size = (tmp_path / "preview.png").stat().st_size
    blueprint_size = (tmp_path / "blueprint.png").stat().st_size
    assert blueprint_size > preview_size
