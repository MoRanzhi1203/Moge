##############################
# tests/test_unified_workspace.py - 三模式统一工作台适配/视图/工程/导出
##############################

from pathlib import Path

import numpy as np
from Moge.core.models import GridSpec, PaletteEntry
from Moge.core.modes import registry
from Moge.core.palette_exchange import export_palette_csv, load_palette_csv, remap_to_palette
from Moge.core.pipeline import run_pipeline
from Moge.core.workbench import get_adapter, prepare_result
from Moge.exporters.bead_sheet import BeadSheetOptions, export_partition_pngs
from Moge.exporters.project import load_project, save_project
from Moge.ui.main_window import LEGEND_DATA_ROLE, MainWindow


def _image(size=32, transparent=False):
    image = np.random.default_rng(11).integers(0, 256, (size, size, 4), dtype=np.uint8)
    image[..., 3] = 255
    if transparent:
        image[:, :size // 2, 3] = 0
    return image


def _result(mode, width=12, height=12, transparent=False, seed=11):
    image = _image(max(width, height) * 2, transparent=transparent)
    rng = np.random.default_rng(seed)
    image[..., :3] = rng.integers(0, 256, image[..., :3].shape, dtype=np.uint8)
    config = registry.build_config(mode, GridSpec(width, height), registry.default_settings(mode), image)
    return run_pipeline(image, config)


def test_adapters_produce_mode_specific_legend_payloads():
    pixel = _result("pixel")
    pixel_symbols = prepare_result(pixel)
    pixel_adapter = get_adapter("pixel")
    pixel_payload = pixel_adapter.legend_payload(
        pixel.grid.entries[0], 0, 3, 10, pixel_symbols,
        {"show_counts": True, "locked_counts": {0: 2}},
    )
    assert pixel_payload["primary"].startswith("#001")
    assert "#" in pixel_payload["secondary"]
    assert "RGB" in pixel_payload["secondary"]
    assert "锁定 2" in pixel_payload["secondary"]

    mc = _result("minecraft")
    mc_symbols = prepare_result(mc)
    mc_payload = get_adapter("minecraft").legend_payload(
        mc.grid.entries[0], 0, 1, 2, mc_symbols,
        {"show_counts": True, "edition": "java", "version": "1.20.1"},
    )
    assert mc_payload["secondary"].startswith(mc.grid.entries[0].id)
    assert "java 1.20.1" in mc_payload["secondary"]
    assert mc_payload["thumbnail_path"] == str(mc.grid.entries[0].meta.get("texture_path") or "")

    beads = _result("beads")
    bead_symbols = prepare_result(beads)
    bead = get_adapter("beads")
    bead_payload = bead.legend_payload(
        beads.grid.entries[0], 0, 1, 2, bead_symbols,
        {"show_counts": True},
    )
    meta = beads.grid.entries[0].meta
    assert meta.get("brand") in bead_payload["secondary"]
    assert bead_payload["primary"].startswith(str(meta.get("code") or ""))


def test_minecraft_browse_uses_current_version():
    adapter = get_adapter("minecraft")
    entries = adapter.browse_entries(
        {"settings": {"edition": "java", "version": "1.20.1", "resource_mode": "approx"}}
    )
    assert entries
    assert all(entry.meta.get("edition") == "java" for entry in entries)
    assert all(entry.meta.get("version") == "1.20.1" for entry in entries)
    assert len({entry.id for entry in entries}) == len(entries)
    assert all(entry.meta.get("symbol") for entry in entries)


def test_pixel_palette_import_and_export(tmp_path):
    result = _result("pixel", transparent=True)
    prepare_result(result)
    palette_path = tmp_path / "palette.csv"
    palette_path.write_text("name,hex\n红,#CC2233\n蓝,#2244CC\n", encoding="utf-8")
    palette = load_palette_csv(str(palette_path))
    assert len(palette) == 2

    labels, entries = remap_to_palette(result.grid.labels, result.grid.entries, palette)
    assert len(entries) == 2
    assert set(np.unique(labels[labels >= 0])).issubset({0, 1})
    assert int(np.count_nonzero(labels < 0)) > 0

    export_path = export_palette_csv(result, str(tmp_path / "exported.csv"))
    content = Path(export_path).read_text(encoding="utf-8-sig")
    assert content.splitlines()[0].startswith("index,name,hex")
    assert "count" in content


def test_project_roundtrip_cells_for_all_modes(tmp_path):
    for mode in ("pixel", "minecraft", "beads"):
        result = _result(mode)
        path = save_project(str(tmp_path / f"{mode}.moge"), result)
        document = load_project(path)
        grid = document.grid
        assert grid is not None
        assert len(grid.cells) == grid.spec.width * grid.spec.height
        assert grid.symbols
        non_empty = [cell for cell in grid.cells if not cell["is_empty"]]
        assert non_empty
        assert non_empty[0]["code"]
        assert non_empty[0]["symbol"] == grid.symbols[non_empty[0]["bead_id"]]


def test_view_presets_do_not_touch_document_all_modes(qapp, monkeypatch):
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    window = MainWindow()
    window.resize(1100, 760)
    window.show()
    for mode in ("pixel", "minecraft", "beads"):
        result = _result(mode)
        window.results[mode] = result
        window.mode = mode
        window._display_result(result)
        labels_before = result.grid.labels.copy()
        task_before = window._task_counter
        for preset in ("blueprint", "mono", "preview", "legend"):
            window._apply_bead_preset(preset)
            qapp.processEvents()
            assert window._task_counter == task_before
            assert np.array_equal(result.grid.labels, labels_before)
        payload = window.palette_list.item(0).data(LEGEND_DATA_ROLE)
        assert payload["primary"]
        assert payload["count_text"]
    window.close()


def test_no_result_browse_all_modes(qapp):
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    for mode, marker in (("pixel", "参考调色板"), ("minecraft", "候选方块"), ("beads", "全部色卡")):
        window.mode = mode
        window.mode_combo.setCurrentIndex(window.mode_combo.findData(mode))
        window.results.clear()
        window._refresh_palette()
        qapp.processEvents()
        assert window.palette_list.count() > 0
        assert marker in window.palette_note.text()
    window.close()


def test_bead_legend_removes_duplicate_display_prefix():
    entry = PaletteEntry(
        id="bead:MARD:MARD 221:A1",
        name="MARD MARD 221 A1 A1",
        rgb=(250, 245, 205),
        meta={"brand": "MARD", "series": "MARD 221", "code": "A1"},
    )
    symbols = get_adapter("beads").prepare_entries([entry])
    payload = get_adapter("beads").legend_payload(
        entry, 0, 5, 10, symbols, {"show_counts": True}
    )
    assert payload["primary"] == "A1"
    assert payload["secondary"].startswith("MARD 221")
    assert "MARD · MARD" not in payload["secondary"]


def test_hover_uses_one_based_coordinates(qapp):
    window = MainWindow()
    result = _result("pixel")
    window.results["pixel"] = result
    window.mode = "pixel"
    window._display_result(result)
    window._on_hover(0, 0)
    text = window.lbl_hover.text()
    assert "X 1" in text and "Y 1" in text
    window.close()


def test_partition_png_export(tmp_path):
    result = _result("beads", width=16, height=16)
    paths = export_partition_pngs(
        result,
        str(tmp_path),
        BeadSheetOptions(mode="blueprint", cell_size=12, board_width=8, board_height=8),
    )
    assert len(paths) == 4
    for path in paths:
        assert Path(path).read_bytes()[:4] == b"\x89PNG"
