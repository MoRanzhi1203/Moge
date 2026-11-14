import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pytest
from Moge.core.models import GridSpec
from Moge.core.modes import registry
from Moge.core.pipeline import run_pipeline
from Moge.exporters.blueprint_pdf import export_blueprint_pdf
from Moge.exporters.csv import export_materials_csv, material_rows
from Moge.exporters.png import export_png
from Moge.exporters.project import load_project, save_project


def _result(mode="pixel", seed=4):
    image = np.random.default_rng(seed).integers(0, 256, (48, 64, 4), dtype=np.uint8)
    image[..., 3] = 255
    image[0, 0, 3] = 0
    config = registry.build_config(mode, GridSpec(20, 15), registry.default_settings(mode), image)
    return run_pipeline(image, config)


def test_png_export_supports_unicode_path():
    result = _result()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "测试 图像.png"
        exported = export_png(result, str(path), cell_size=6)
        assert Path(exported).read_bytes()[:4] == b"\x89PNG"


def test_csv_export_lists_used_entries():
    result = _result()
    rows = material_rows(result)
    assert rows
    assert sum(row["count"] for row in rows) == result.stats["filled_cells"]

    with tempfile.TemporaryDirectory() as directory:
        path = export_materials_csv(result, str(Path(directory) / "materials.csv"))
        content = Path(path).read_text(encoding="utf-8-sig")
        assert content.splitlines()[0].startswith("id,name")
        assert "count" in content


def test_project_roundtrip_preserves_grid_and_settings():
    result = _result()
    with tempfile.TemporaryDirectory() as directory:
        path = save_project(str(Path(directory) / "demo.moge"), result, "source.png")
        document = load_project(path)

    assert document.mode == "pixel"
    assert document.grid is not None
    assert np.array_equal(document.grid.labels, result.grid.labels)
    assert [entry.id for entry in document.grid.entries] == [entry.id for entry in result.grid.entries]
    assert document.settings["quantizer"] == result.settings["quantizer"]


def test_project_rejects_unknown_members():
    result = _result()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "bad.moge"
        save_project(str(path), result)
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("evil.txt", "x")
        with pytest.raises(ValueError):
            load_project(str(path))


def test_project_rejects_future_schema():
    result = _result()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "future.moge"
        payload = save_project(str(path), result)
        with zipfile.ZipFile(payload, "r") as archive:
            manifest = archive.read("manifest.json")
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("manifest.json", manifest.replace(b'"schema": 1', b'"schema": 99'))
        with pytest.raises(ValueError):
            load_project(payload)


def test_pdf_export_creates_multi_page_file(qapp):
    result = _result("beads")
    with tempfile.TemporaryDirectory() as directory:
        path = export_blueprint_pdf(result, str(Path(directory) / "blueprint.pdf"), "测试图纸", 8, 8)
        data = Path(path).read_bytes()
    assert data[:4] == b"%PDF"
    assert len(data) > 5000
