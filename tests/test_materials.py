import tempfile
from pathlib import Path

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
