import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pytest
from Moge.core.materials import (
    BEAD_CATALOG,
    MC_BLOCKS,
    BeadColor,
    board_partitions,
    catalog_brands,
    catalog_series,
    filter_beads,
    filter_blocks,
    load_bead_catalog_csv,
    load_resource_pack_zip,
    parse_version,
)


def test_version_parsing_and_filtering():
    assert parse_version("1.20.1") == (1, 20, 1)
    old = {block.block_id for block in filter_blocks("1.12.2")}
    modern = {block.block_id for block in filter_blocks("1.20.1")}
    assert "deepslate" not in old
    assert "deepslate" in modern
    assert len(old) < len(modern)


def test_filter_blocks_by_category_obtainability_and_cost():
    concrete = filter_blocks("1.20.1", categories=["concrete"])
    assert concrete and all(block.category == "concrete" for block in concrete)

    renewable = filter_blocks("1.20.1", obtainability="renewable")
    assert renewable and all(block.renewable for block in renewable)

    cheap = filter_blocks("1.20.1", max_cost_tier=1)
    assert cheap and all(block.cost_tier <= 1 for block in cheap)


def test_builtin_blocks_have_unique_ids_and_valid_colors():
    ids = [block.block_id for block in MC_BLOCKS]
    assert len(ids) == len(set(ids))
    assert all(0 <= channel <= 255 for block in MC_BLOCKS for channel in block.rgb)


def test_board_partitions_cover_every_cell_once():
    boards = board_partitions(60, 45, 29, 29)
    assert len(boards) == 6
    covered = sum(board["width"] * board["height"] for board in boards)
    assert covered == 60 * 45

    seen = set()
    for board in boards:
        for y in range(board["y0"], board["y1"]):
            for x in range(board["x0"], board["x1"]):
                assert (x, y) not in seen
                seen.add((x, y))
    assert len(seen) == 60 * 45


def test_bead_catalog_helpers():
    brands = catalog_brands(BEAD_CATALOG)
    assert brands == ["Generic"]
    series = catalog_series(BEAD_CATALOG, "Generic")
    assert series == ["Approx"]

    custom = list(BEAD_CATALOG) + [
        BeadColor("Other", "S1", "X1", "测试色", (1, 2, 3)),
    ]
    selected = filter_beads(custom, "Other", "S1")
    assert [item.code for item in selected] == ["X1"]
    assert filter_beads(BEAD_CATALOG, "Generic", "Approx", disabled_ids=["G01"])[0].code == "G02"


def test_load_bead_catalog_csv_reports_bad_rows():
    content = (
        "brand,series,code,name,rgb,source,verified\n"
        "Test,S1,A1,红,#FF0000,user,true\n"
        "Test,S1,A1,重复,#00FF00,user,false\n"
        "Test,S1,A2,坏色,not-a-color,user,false\n"
    )
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "catalog.csv"
        path.write_text(content, encoding="utf-8")
        catalog, errors = load_bead_catalog_csv(str(path))

    assert len(catalog) == 1
    assert catalog[0].rgb == (255, 0, 0)
    assert catalog[0].verified is True
    assert len(errors) == 2


def test_load_bead_catalog_csv_requires_columns():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "catalog.csv"
        path.write_text("brand,code\nA,B\n", encoding="utf-8")
        with pytest.raises(ValueError):
            load_bead_catalog_csv(str(path))


def _texture_png(bgr):
    import cv2

    image = np.zeros((4, 4, 3), np.uint8)
    image[:, :] = bgr
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def test_load_resource_pack_zip_reads_block_average_color(tmp_path):
    path = tmp_path / "pack.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("assets/minecraft/textures/block/stone.png", _texture_png((0, 0, 255)))
        archive.writestr("assets/minecraft/textures/block/unknown_block.png", _texture_png((0, 255, 0)))

    result = load_resource_pack_zip(str(path))
    assert result.loaded == 1
    assert result.overrides["stone"] == (255, 0, 0)
    assert result.skipped >= 1


def test_resource_pack_rejects_path_traversal(tmp_path):
    path = tmp_path / "evil.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../evil.png", _texture_png((0, 0, 0)))
    with pytest.raises(ValueError):
        load_resource_pack_zip(str(path))


def test_minecraft_pipeline_uses_texture_override():
    from Moge.core.models import GridSpec
    from Moge.core.modes import registry
    from Moge.core.pipeline import run_pipeline

    image = np.full((32, 32, 3), (130, 130, 130), np.uint8)
    settings = dict(registry.default_settings("minecraft"))
    settings["texture_overrides"] = {"stone": (0, 255, 0)}
    result = run_pipeline(image, registry.build_config("minecraft", GridSpec(16, 16), settings))

    stone = next(entry for entry in result.grid.entries if entry.id == "stone")
    assert stone.rgb == (0, 255, 0)
    assert stone.source == "user-resource-pack"
    assert result.stats["texture_overrides"] == 1
