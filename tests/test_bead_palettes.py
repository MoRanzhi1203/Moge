import csv
import json
import os
import zipfile
from pathlib import Path

import numpy as np
import pytest
from Moge.core.beads.catalog import (
    available_materials,
    available_sizes,
    load_catalog,
    load_catalog_with_meta,
    nearest_cross_brand,
    preferred_selection,
)
from Moge.core.models import GridSpec
from Moge.core.modes import beads as beads_mode
from Moge.core.pipeline import run_pipeline

REAL_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Moge" / "palettes"
HAS_PALETTES = (REAL_ROOT / "beads.db").is_file()


def _settings(**overrides):
    settings = dict(beads_mode.BEAD_DEFAULTS)
    settings.update(overrides)
    return settings


@pytest.mark.skipif(not HAS_PALETTES, reason="本机没有拼豆色卡数据库")
def test_palette_database_contains_public_brands():
    catalog, meta = load_catalog_with_meta()
    assert len(catalog) >= 4000
    brands = {item.brand for item in catalog}
    for brand in ("MARD", "Hama", "Perler", "Artkal", "COCO", "Nabbi"):
        assert brand in brands
    assert len({item for item in catalog if item.brand == "MARD" and item.series == "MARD 221"}) == 221
    assert len({item for item in catalog if item.brand == "MARD" and item.series == "MARD 291"}) == 291

    trust = meta["trust_counts"]
    assert trust.get("official", 0) > 0
    assert trust.get("community", 0) > 0
    assert trust.get("sampled", 0) > 0
    assert meta["conflicts"] > 0
    assert all(source["license"] == "MIT" for source in meta["sources"])

    sample = next(item for item in catalog if item.trust == "official")
    assert sample.source_url.startswith("http") and sample.license == "MIT"


@pytest.mark.skipif(not HAS_PALETTES, reason="本机没有拼豆色卡数据库")
def test_default_selection_prefers_mard_221():
    catalog = load_catalog()
    assert preferred_selection(catalog) == ("MARD", "MARD 221")
    candidates = beads_mode.selectable_beads(_settings())
    assert len(candidates) == 221
    assert all(item.brand == "MARD" and item.series == "MARD 221" for item in candidates)
    assert all(item.code.startswith(("A", "B", "C", "D", "E", "F", "G", "H", "M")) for item in candidates)


@pytest.mark.skipif(not HAS_PALETTES, reason="本机没有拼豆色卡数据库")
def test_filters_by_size_family_and_material():
    catalog = load_catalog()
    hama_sizes = available_sizes(catalog, "Hama")
    assert {"5mm", "2.6mm", "10mm"}.issubset(set(hama_sizes))
    artkal_materials = available_materials(catalog, "Artkal", "Artkal C 197")
    assert {"transparent", "glow", "pearl", "solid"}.issubset(set(artkal_materials))

    glow = beads_mode.selectable_beads(
        _settings(brand="Artkal", series="Artkal C 197", material_filter="glow", catalog=catalog)
    )
    assert glow and all(item.material == "glow" for item in glow)
    transparent = beads_mode.selectable_beads(
        _settings(brand="Artkal", series="Artkal C 197", material_filter="transparent", catalog=catalog)
    )
    assert transparent and all(item.material == "transparent" for item in transparent)

    reds = beads_mode.selectable_beads(
        _settings(brand="MARD", series="MARD 221", family_filter="红色", catalog=catalog)
    )
    assert reds and all(item.color_family == "红色" for item in reds)


@pytest.mark.skipif(not HAS_PALETTES, reason="本机没有拼豆色卡数据库")
def test_cross_brand_match_is_reference_only():
    catalog = load_catalog()
    mard = beads_mode.selectable_beads(_settings(catalog=catalog))
    match, distance = nearest_cross_brand(mard[0].rgb, catalog, brand="MARD")
    assert match.brand != "MARD"
    assert distance >= 0
    assert match.license == "MIT"
    assert match.id != mard[0].id


@pytest.mark.skipif(not HAS_PALETTES, reason="本机没有拼豆色卡数据库")
def test_bead_pipeline_uses_real_codes():
    image = np.random.default_rng(7).integers(0, 256, (96, 128, 3), dtype=np.uint8)
    config = beads_mode.build_config(GridSpec(16, 12), _settings())
    result = run_pipeline(image, config)
    stats = result.stats
    assert stats["brand"] == "MARD" and stats["series"] == "MARD 221"
    assert stats["candidate_colors"] == 221
    assert stats["catalog_license"] == "MIT"
    assert stats["catalog_trust_counts"]
    assert stats["catalog_material_counts"]
    assert result.grid.entries
    for entry in result.grid.entries:
        assert entry.meta["code"]
        assert entry.meta["brand"] == "MARD"
        assert entry.meta["trust"] in ("official", "community", "sampled", "unknown")
        assert entry.meta["source_url"].startswith("http")
        assert entry.meta["license"] == "MIT"


@pytest.mark.skipif(not HAS_PALETTES, reason="本机没有拼豆色卡数据库")
def test_csv_export_includes_sources(tmp_path):
    from Moge.exporters.csv import export_materials_csv

    image = np.random.default_rng(8).integers(0, 256, (64, 64, 3), dtype=np.uint8)
    result = run_pipeline(image, beads_mode.build_config(GridSpec(10, 8), _settings()))
    target = tmp_path / "materials.csv"
    export_materials_csv(result, str(target))
    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert {"brand", "series", "code", "size", "material", "trust", "license", "source_url"}.issubset(rows[0])
    assert rows[0]["license"] == "MIT"
    assert rows[0]["code"]


@pytest.mark.skipif(not HAS_PALETTES, reason="本机没有拼豆色卡数据库")
def test_project_strips_catalog_but_keeps_settings(tmp_path):
    from Moge.exporters.project import load_project, save_project

    image = np.random.default_rng(9).integers(0, 256, (64, 64, 3), dtype=np.uint8)
    result = run_pipeline(image, beads_mode.build_config(GridSpec(10, 8), _settings()))
    path = tmp_path / "beads.moge"
    save_project(str(path), result, None)

    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert "catalog" not in (manifest["settings"].get("params") or {})
    assert manifest["settings"]["params"]["brand"] == "MARD"

    loaded = load_project(str(path))
    assert np.array_equal(loaded.grid.labels, result.grid.labels)
    assert loaded.settings["params"]["series"] == "MARD 221"


@pytest.mark.skipif(not HAS_PALETTES, reason="本机没有拼豆色卡数据库")
def test_gui_brand_switch_and_palette_update(qapp):
    from Moge.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QMessageBox

    QMessageBox.warning = staticmethod(lambda *args, **kwargs: None)
    QMessageBox.critical = staticmethod(lambda *args, **kwargs: None)
    window = MainWindow()
    assert window.bead_brand.currentData() == "MARD"
    assert window.bead_series.currentData() == "MARD 221"
    assert "SQLite" in window.bead_catalog_note.text()

    index = window.bead_brand.findData("Hama")
    assert index >= 0
    window.bead_brand.setCurrentIndex(index)
    series = {window.bead_series.itemData(i) for i in range(window.bead_series.count())}
    assert {"Hama Midi", "Hama Mini", "Hama Maxi"}.issubset(series)
    window._set_combo_data(window.bead_series, "Hama Mini")
    sizes = {window.bead_size.itemData(i) for i in range(window.bead_size.count())}
    assert "2.6mm" in sizes
    materials = {window.bead_material.itemData(i) for i in range(window.bead_material.count())}
    assert "" in materials
    window.close()
