import hashlib
from pathlib import Path

import cv2
import pytest
from Moge.core.models import GridSpec
from Moge.core.samples import (
    categories,
    image_path,
    load_manifest,
    manifest_path,
    recommended_grid,
    samples_root,
    thumbnail_path,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "assets" / "samples"
HAS_SAMPLES = (SAMPLES / "manifest.json").is_file()
EXPECTED_CATEGORIES = {
    "portraits": 3,
    "animals": 3,
    "landscapes": 3,
    "flowers": 2,
    "architecture": 2,
    "illustrations": 2,
    "transparent": 2,
    "synthetic": 2,
}


@pytest.mark.skipif(not HAS_SAMPLES, reason="示例图库尚未生成")
def test_manifest_files_and_hashes():
    entries = load_manifest()
    assert len(entries) == 19
    counts = {}
    for entry in entries:
        counts[entry["category"]] = counts.get(entry["category"], 0) + 1
    assert counts == EXPECTED_CATEGORIES
    assert samples_root() == SAMPLES and manifest_path().is_file()

    seen = set()
    for entry in entries:
        for field in (
            "id", "title", "category", "filename", "source_url", "author",
            "license", "license_url", "width", "height", "sha256", "attribution", "description",
        ):
            assert entry.get(field) is not None, (entry.get("id"), field)
        assert entry["filename"].isascii() and entry["id"].isascii()
        path = image_path(entry)
        assert path.is_file(), path
        assert thumbnail_path(entry).is_file(), thumbnail_path(entry)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == entry["sha256"]
        assert digest not in seen
        seen.add(digest)
        lower = entry["license"].lower()
        assert not any(token in lower for token in ("nc", "nd", "sa", "fair use"))
        assert ("cc0" in lower) or ("public domain" in lower) or ("cc by" in lower)


@pytest.mark.skipif(not HAS_SAMPLES, reason="示例图库尚未生成")
def test_images_decode_dimensions_and_transparency():
    entries = load_manifest()
    for entry in entries:
        image = cv2.imread(str(image_path(entry)), cv2.IMREAD_UNCHANGED)
        assert image is not None, entry["id"]
        height, width = image.shape[:2]
        assert (width, height) == (entry["width"], entry["height"])
        assert max(width, height) <= 1400
        if entry["category"] == "transparent":
            assert image.ndim == 3 and image.shape[2] == 4
            assert int(image[..., 3].min()) < 250
        if entry["category"] == "synthetic":
            assert entry["synthetic"] is True
            assert entry["license"].startswith("CC0")


@pytest.mark.skipif(not HAS_SAMPLES, reason="示例图库尚未生成")
def test_recommended_grid_keeps_aspect_ratio():
    entries = {item["id"]: item for item in load_manifest()}
    portrait = entries["portraits-1"]
    spec = recommended_grid(portrait)
    assert isinstance(spec, GridSpec)
    assert spec.height > spec.width
    landscape = entries["landscapes-2"]
    spec = recommended_grid(landscape)
    assert spec.width >= spec.height
    assert categories() == sorted(EXPECTED_CATEGORIES)


def test_frozen_bundle_resource_root(monkeypatch, tmp_path):
    import sys

    from Moge.core.samples import assets_root

    bundle = tmp_path / "bundle"
    (bundle / "assets" / "samples").mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    assert assets_root() == bundle / "assets"


def _wait(window, timeout=30000):
    from PyQt5.QtCore import QEventLoop, QTimer

    loop = QEventLoop()

    def poll():
        if window._thread is None:
            loop.quit()
        else:
            QTimer.singleShot(30, poll)

    QTimer.singleShot(30, poll)
    QTimer.singleShot(timeout, loop.quit)
    loop.exec_()
    assert window._thread is None


@pytest.mark.skipif(not HAS_SAMPLES, reason="示例图库尚未生成")
def test_gui_welcome_dialog_and_three_modes(qapp, monkeypatch):
    from Moge.ui.main_window import MainWindow
    from Moge.ui.sample_dialog import SampleLibraryDialog
    from PyQt5.QtWidgets import QMessageBox

    QMessageBox.warning = staticmethod(lambda *args, **kwargs: None)
    QMessageBox.critical = staticmethod(lambda *args, **kwargs: None)
    QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.Yes)

    entries = load_manifest()
    dialog = SampleLibraryDialog()
    assert dialog.grid.count() == len(entries)
    assert dialog.category.count() == len(categories()) + 1
    dialog.grid.setCurrentRow(0)
    qapp.processEvents()
    assert dialog.btn_recommended.isEnabled()
    assert "许可" in dialog.info.toPlainText()
    dialog._accept(True)
    chosen = dialog.selected_entry
    assert chosen is not None and dialog.use_recommended

    window = MainWindow()
    assert window.center_stack.currentWidget() is window.welcome
    assert window.btn_welcome_samples.text() == "使用示例图片"
    assert "示例图库" in window.act_samples.text()

    spec = recommended_grid(chosen)
    window.open_image(str(image_path(chosen)), suggested_spec=spec, keep_grid=False)
    assert window.original_img is not None
    assert window.center_stack.currentWidget() is window.canvas
    assert window.grid_width.value() == spec.width
    assert window.grid_height.value() == spec.height

    window.grid_width.setValue(16)
    window.grid_height.setValue(12)
    for mode in ("pixel", "minecraft", "beads"):
        window.mode_combo.setCurrentIndex(window.mode_combo.findData(mode))
        window.apply_processing()
        _wait(window)
        result = window.results[mode]
        assert result.mode == mode
        assert result.grid.spec.width == 16 and result.grid.spec.height == 12
        assert window.original_img is not None

    window.mode_combo.setCurrentIndex(window.mode_combo.findData("beads"))
    window._set_combo_data(window.bead_brand, "MARD")
    window._on_bead_brand_changed()
    window._set_combo_data(window.bead_series, "MARD 221")
    window._on_bead_series_changed()
    window.results.pop("beads", None)
    window._display_source()
    window.palette_scope.setCurrentIndex(window.palette_scope.findData("all"))
    qapp.processEvents()
    assert window.palette_list.count() > 100

    window.close()
    assert window.original_img is None
    assert not window.results
