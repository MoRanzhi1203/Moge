import numpy as np
from Moge.ui.main_window import MainWindow
from PyQt5.QtWidgets import QMessageBox


def test_workbench_three_modes_edit_and_switch(qapp, monkeypatch, wait_pipeline):
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))

    window = MainWindow()
    window.original_img = np.random.default_rng(0).integers(0, 256, (48, 64, 4), dtype=np.uint8)
    window.original_img[..., 3] = 255
    window.grid_width.setValue(20)
    window.grid_height.setValue(15)

    for mode in ("pixel", "minecraft", "beads"):
        window.mode_combo.setCurrentIndex(window.mode_combo.findData(mode))
        window.apply_processing()
        wait_pipeline(window)
        result = window.results[mode]
        assert result is not None
        assert result.grid.validate()
        assert result.image.shape[0] == 15
        assert result.grid.spec.width == 20

    window.mode_combo.setCurrentIndex(window.mode_combo.findData("pixel"))
    result = window.results["pixel"]
    original = result.grid.labels.copy()

    window.act_edit_mode.trigger()
    assert window.interaction_mode == "edit"
    window.tool = "paint"
    window.selected_entry = min(1, len(result.grid.entries) - 1)
    window._on_stroke_started()
    window._on_cell_pressed(2, 2)
    assert result.grid.labels[2, 2] == window.selected_entry

    window.undo()
    assert np.array_equal(result.grid.labels, original)
    window.redo()
    assert result.grid.labels[2, 2] == window.selected_entry

    # 切换模式不清空源图
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("beads"))
    assert window.original_img is not None
    window.close()
