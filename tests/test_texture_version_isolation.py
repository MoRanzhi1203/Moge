import hashlib
import os
from pathlib import Path

import cv2
import numpy as np
import pytest
from Moge.core.grid import render_grid
from Moge.core.models import GridSpec, PaletteEntry
from Moge.core.modes import minecraft as minecraft_mode
from Moge.core.pipeline import run_pipeline
from Moge.core.render import render_textured

REAL_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Moge" / "resources"
HAS_RESOURCES = (REAL_ROOT / "index.db").is_file()
MODERN_BLOCKS = ["netherite_block", "chiseled_polished_blackstone", "mud_bricks", "target", "fletching_table"]


def _use_real_resources(monkeypatch):
    monkeypatch.setenv("MOGE_RESOURCE_DIR", str(REAL_ROOT))
    minecraft_mode._REAL_CATALOG_CACHE.clear()


def _candidates(monkeypatch, edition, version, **extra):
    settings = dict(minecraft_mode.MC_DEFAULTS)
    settings.update({"edition": edition, "version": version, "resource_mode": "real"})
    settings.update(extra)
    return minecraft_mode.candidate_blocks(settings)


def _entry(block):
    return PaletteEntry(
        id=block.block_id,
        name=block.name,
        rgb=block.rgb,
        source=block.source,
        meta={
            "texture_path": block.texture_path,
            "texture_sha256": block.texture_sha256,
            "texture": "real",
            "geometry": block.geometry,
            "block_state": block.block_state,
        },
    )


@pytest.mark.skipif(not HAS_RESOURCES, reason="本机没有真实资源索引库")
def test_java_1122_candidates_exclude_modern_blocks(monkeypatch):
    _use_real_resources(monkeypatch)
    candidates = _candidates(monkeypatch, "java", "1.12.2")
    ids = {block.block_id for block in candidates}
    assert candidates
    for block_id in MODERN_BLOCKS:
        assert block_id not in ids
    assert {"stone", "oak_planks", "cobblestone"}.issubset(ids)


@pytest.mark.skipif(not HAS_RESOURCES, reason="本机没有真实资源索引库")
def test_catalog_cache_isolated_per_version(monkeypatch):
    _use_real_resources(monkeypatch)
    old = {block.block_id for block in _candidates(monkeypatch, "java", "1.12.2")}
    new = {block.block_id for block in _candidates(monkeypatch, "java", "1.20.1")}
    assert "netherite_block" not in old and "netherite_block" in new
    assert old - new  # 1.12.2 独有方块（如旧命名）
    java_stone = next(block for block in _candidates(monkeypatch, "java", "1.20.1") if block.block_id == "stone")
    bedrock_stone = next(
        block for block in _candidates(monkeypatch, "bedrock", "1.21.50") if block.block_id == "stone"
    )
    assert java_stone.texture_sha256 != bedrock_stone.texture_sha256


@pytest.mark.skipif(not HAS_RESOURCES, reason="本机没有真实资源索引库")
@pytest.mark.parametrize(
    "edition,version,names",
    [
        ("java", "1.12.2", ("stone", "oak_planks", "cobblestone")),
        ("java", "1.20.1", ("stone", "oak_planks", "cobblestone")),
        ("java", "1.21.4", ("stone", "oak_planks", "cobblestone")),
        # 基岩版沿用旧 ID：planks 即橡木木板
        ("bedrock", "1.21.50", ("stone", "planks", "cobblestone")),
    ],
)
def test_texture_render_matches_nearest_neighbor_png(monkeypatch, edition, version, names):
    _use_real_resources(monkeypatch)
    candidates = {block.block_id: block for block in _candidates(monkeypatch, edition, version)}
    chosen = [candidates[name] for name in names]
    entries = [_entry(block) for block in chosen]
    labels = np.array([[0, 1, 2]], dtype=np.int32)

    solid = render_grid(labels, entries, transparent=False)
    assert tuple(solid[0, 0]) == chosen[0].rgb
    assert tuple(solid[0, 1]) == chosen[1].rgb
    assert tuple(solid[0, 2]) == chosen[2].rgb

    texture = render_textured(labels, entries, cell_pixels=16)
    assert texture.shape == (16, 48, 4)
    expected = []
    for block in chosen:
        assert block.texture_path and Path(block.texture_path).is_file()
        data = Path(block.texture_path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == block.texture_sha256
        image = cv2.imread(block.texture_path, cv2.IMREAD_UNCHANGED)
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
        elif image.shape[2] == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
        tile = cv2.resize(image, (16, 16), interpolation=cv2.INTER_NEAREST)
        expected.append(cv2.cvtColor(tile, cv2.COLOR_BGRA2RGBA))
    expected_array = np.hstack(expected)
    assert np.array_equal(texture, expected_array)
    assert not np.array_equal(texture[..., :3], np.repeat(np.repeat(solid, 16, 0), 16, 1)[..., :3])


@pytest.mark.skipif(not HAS_RESOURCES, reason="本机没有真实资源索引库")
def test_pipeline_materials_belong_to_target_version(monkeypatch):
    _use_real_resources(monkeypatch)
    image = np.random.default_rng(11).integers(0, 256, (96, 128, 4), dtype=np.uint8)
    image[..., 3] = 255
    settings = dict(minecraft_mode.MC_DEFAULTS)
    settings.update({"edition": "java", "version": "1.12.2", "resource_mode": "real"})
    result = run_pipeline(image, minecraft_mode.build_config(GridSpec(16, 12), settings))
    target_ids = {block.block_id for block in _candidates(monkeypatch, "java", "1.12.2")}
    assert result.stats["edition"] == "java" and result.stats["version"] == "1.12.2"
    assert all(entry.id in target_ids for entry in result.grid.entries)
    assert not ({entry.id for entry in result.grid.entries} & set(MODERN_BLOCKS))
    for entry in result.grid.entries:
        assert entry.meta["texture"] == "real"
        path = Path(entry.meta["texture_path"])
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry.meta["texture_sha256"]


@pytest.mark.skipif(not HAS_RESOURCES, reason="本机没有真实资源索引库")
def test_gui_version_switch_marks_stale_and_invalid(qapp, monkeypatch, wait_pipeline):
    from Moge.ui.main_window import RESULT_CURRENT, RESULT_INVALID, RESULT_STALE, MainWindow
    from PyQt5.QtWidgets import QMessageBox

    _use_real_resources(monkeypatch)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *args, **kwargs: None))

    window = MainWindow()
    window.original_img = np.random.default_rng(12).integers(0, 256, (96, 128, 4), dtype=np.uint8)
    window.original_img[..., 3] = 255
    window.grid_width.setValue(12)
    window.grid_height.setValue(9)
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("minecraft"))
    window._set_combo_data(window.mc_edition, "java")
    window._refresh_mc_versions()
    window._set_combo_data(window.mc_version, "1.20.1")
    window.apply_processing()
    wait_pipeline(window)

    result = window.results["minecraft"]
    assert result.stats["version"] == "1.20.1"
    assert window._mc_state_text(result)[0] == RESULT_CURRENT

    window._set_combo_data(window.mc_version, "1.12.2")
    state, message = window._mc_state_text(result)
    assert state == RESULT_INVALID
    assert "旧结果" in message
    assert "1.12.2" in message
    assert "INVALID" in window.stats_view.toPlainText() or "不支持" in window.stats_view.toPlainText()

    window.apply_processing()
    wait_pipeline(window)
    fresh = window.results["minecraft"]
    assert fresh is not result
    assert fresh.stats["version"] == "1.12.2"
    assert window._mc_state_text(fresh)[0] == RESULT_CURRENT
    assert fresh.stats.get("version_isolated") is True
    target_ids = {block.block_id for block in _candidates(monkeypatch, "java", "1.12.2")}
    assert all(entry.id in target_ids for entry in fresh.grid.entries)
    assert not ({entry.id for entry in fresh.grid.entries} & set(MODERN_BLOCKS))

    # 切换到超集版本但未重新处理：只应标记 STALE，不是 INVALID
    window._set_combo_data(window.mc_version, "1.20.1")
    state, _message = window._mc_state_text(fresh)
    assert state in (RESULT_STALE, RESULT_INVALID)
    window.close()
