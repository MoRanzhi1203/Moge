import os
from pathlib import Path

import numpy as np
import pytest
from Moge.core.grid import render_grid
from Moge.core.models import GridSpec
from Moge.core.modes import minecraft as minecraft_mode
from Moge.core.pipeline import run_pipeline
from Moge.core.render import load_texture_tile, render_textured

REAL_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Moge" / "resources"
PERSON_PATH = Path(r"E:\画稿\原图\J4.jpg")
HAS_RESOURCES = (REAL_ROOT / "index.db").is_file()


def test_glazed_terracotta_category_is_independent():
    from Moge.core.resources.catalog import metadata_for

    assert metadata_for("red_glazed_terracotta")["category"] == "glazed"
    assert metadata_for("white_terracotta")["category"] == "terracotta"


def _settings(**overrides):
    settings = dict(minecraft_mode.MC_DEFAULTS)
    settings.update({"edition": "java", "version": "1.20.1", "resource_mode": "real"})
    settings.update(overrides)
    return settings


@pytest.mark.skipif(not HAS_RESOURCES, reason="本机没有真实资源索引库")
def test_all_matching_strategies_produce_valid_results(monkeypatch):
    from Moge.core.modes import minecraft as mc

    monkeypatch.setenv("MOGE_RESOURCE_DIR", str(REAL_ROOT))
    mc._REAL_CATALOG_CACHE.clear()
    image = np.random.default_rng(20).integers(0, 256, (72, 96, 4), dtype=np.uint8)
    image[..., 3] = 255
    target = {block.block_id for block in mc.candidate_blocks(_settings())}
    for strategy, _label in mc.MATCHING_OPTIONS:
        result = run_pipeline(image, mc.build_config(GridSpec(12, 9), _settings(matching_strategy=strategy)))
        assert result.stats["matching_strategy"] == strategy
        assert result.grid.entries
        assert all(entry.id in target for entry in result.grid.entries)
        assert 0 <= result.stats["texture_feature_error"] < 1.0


@pytest.mark.skipif(not HAS_RESOURCES or not PERSON_PATH.is_file(), reason="缺少真实资源或人物图片")
def test_real_artwork_uses_version_png_per_cell(monkeypatch):
    import cv2
    from Moge.core.modes import minecraft as mc

    monkeypatch.setenv("MOGE_RESOURCE_DIR", str(REAL_ROOT))
    mc._REAL_CATALOG_CACHE.clear()
    data = np.fromfile(str(PERSON_PATH), dtype=np.uint8)
    person = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    assert person is not None
    person = cv2.cvtColor(person, cv2.COLOR_BGR2RGBA)
    result = run_pipeline(person, mc.build_config(GridSpec(64, 64), _settings()))
    stats = result.stats
    assert stats["edition"] == "java" and stats["version"] == "1.20.1"
    assert stats["mean_delta_e00"] < 5.0
    assert stats["p95_delta_e00"] < 10.0
    assert stats["texture_feature_error"] < 0.10
    assert stats["used_entries"] >= 20

    document = result.grid
    texture = render_textured(document.labels, document.entries, 16)
    solid = render_grid(document.labels, document.entries, transparent=False)
    counts = stats["counts"]
    used = sorted(
        [entry for entry in document.entries if counts.get(entry.id, 0) > 0],
        key=lambda entry: -int(counts.get(entry.id, 0)),
    )
    assert len(used) >= 10
    checked = 0
    differing = 0
    for entry in used:
        index = document.entries.index(entry)
        positions = np.argwhere(document.labels == index)
        if len(positions) == 0:
            continue
        row, col = int(positions[0][0]), int(positions[0][1])
        tile = load_texture_tile(entry.meta["texture_path"], 16)
        assert tile is not None
        block = texture[row * 16:(row + 1) * 16, col * 16:(col + 1) * 16]
        assert np.array_equal(block, tile)
        solid_block = np.repeat(
            np.repeat(np.array(entry.rgb, np.uint8)[None, None, :], 16, axis=0), 16, axis=1
        )
        assert solid[row, col].tolist() == list(entry.rgb)
        if not np.array_equal(block[..., :3], solid_block):
            differing += 1
        checked += 1
        if checked >= 10:
            break
    assert checked >= 10
    assert differing >= 5


@pytest.mark.skipif(not HAS_RESOURCES, reason="本机没有真实资源索引库")
def test_restricted_palette_flags_quality_loss(monkeypatch):
    from Moge.core.modes import minecraft as mc

    monkeypatch.setenv("MOGE_RESOURCE_DIR", str(REAL_ROOT))
    mc._REAL_CATALOG_CACHE.clear()
    image = np.random.default_rng(21).integers(0, 256, (96, 96, 4), dtype=np.uint8)
    image[..., 3] = 255
    result = run_pipeline(
        image,
        mc.build_config(GridSpec(24, 24), _settings(categories=["terracotta"])),
    )
    assert result.stats["candidate_blocks"] < 80
    assert result.stats["quality_warning"] is True
    assert "色差" in result.stats["quality_message"]
    assert result.stats["render_limitations"]


@pytest.mark.skipif(not HAS_RESOURCES, reason="本机没有真实资源索引库")
def test_gui_preview_mode_is_exclusive_and_labelled(qapp, monkeypatch):
    from Moge.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setenv("MOGE_RESOURCE_DIR", str(REAL_ROOT))
    minecraft_mode._REAL_CATALOG_CACHE.clear()
    QMessageBox.warning = staticmethod(lambda *args, **kwargs: None)
    QMessageBox.critical = staticmethod(lambda *args, **kwargs: None)
    image = np.random.default_rng(22).integers(0, 256, (48, 64, 4), dtype=np.uint8)
    image[..., 3] = 255
    result = run_pipeline(image, minecraft_mode.build_config(GridSpec(12, 9), _settings()))
    window = MainWindow()
    window.results["minecraft"] = result
    window.mode = "minecraft"
    window.mode_combo.blockSignals(True)
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("minecraft"))
    window.mode_combo.blockSignals(False)
    window._display_result(result)
    assert window.lbl_preview.text() == "预览：纯色"
    window.act_preview_texture.trigger()
    assert window.lbl_preview.text() == "预览：真实纹理"
    assert window.act_preview_texture.isChecked()
    assert not window.act_preview_solid.isChecked()
    window.act_preview_solid.trigger()
    assert window.lbl_preview.text() == "预览：纯色"
    assert window.act_preview_solid.isChecked()
    assert not window.act_preview_texture.isChecked()
    window.close()
