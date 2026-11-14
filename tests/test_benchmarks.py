import numpy as np
import pytest
from Moge.core.benchmarks import (
    aggregate_by_algorithm,
    edge_correlation,
    environment_info,
    evaluate_result,
    make_benchmark_images,
    run_clustering_suite,
    run_material_comparison,
    run_preset_suite,
    summarize,
)
from Moge.core.models import GridSpec
from Moge.core.modes import pixel, registry
from Moge.core.pipeline import run_pipeline


def test_benchmark_images_are_deterministic_and_cover_types():
    first = make_benchmark_images(32)
    second = make_benchmark_images(32)
    assert list(first) == ["portrait", "noise", "cartoon", "low_contrast", "gradient", "text", "transparent"]
    assert np.array_equal(first["noise"], second["noise"])
    assert first["transparent"].shape[2] == 4
    assert all(image.shape[0] == 32 for image in first.values())


def test_edge_correlation_special_cases():
    flat = np.full((8, 8, 3), 128, np.uint8)
    assert edge_correlation(flat, flat) == 1.0
    gradient = np.tile(np.arange(8, dtype=np.uint8)[None, :, None], (8, 1, 3))
    assert edge_correlation(flat, gradient) == 0.0


def test_evaluate_flat_image_has_no_color_error():
    image = np.full((32, 32, 3), 90, np.uint8)
    config = registry.build_config("pixel", GridSpec(16, 16), registry.default_settings("pixel"))
    result = run_pipeline(image, config)
    metrics = evaluate_result(image, result)
    assert metrics["mean_delta_e00"] == pytest.approx(0.0, abs=1e-6)
    assert metrics["isolated_cells"] == 0


def test_clustering_suite_and_summaries_quick():
    images = {"cartoon": make_benchmark_images(24)["cartoon"]}
    records = run_clustering_suite(images, grid_sizes=(16,), color_counts=(4,), algorithms=("kmeans_lab", "ward_lab"))
    assert len(records) == 2

    summary = summarize(records)
    assert len(summary) == 2
    assert all(row["runs"] == 1 for row in summary)

    aggregate = aggregate_by_algorithm(records)
    assert {row["algorithm"] for row in aggregate} == {"kmeans_lab", "ward_lab"}


def test_preset_suite_quick_covers_variants():
    images = {"gradient": make_benchmark_images(24)["gradient"]}
    records = run_preset_suite(images, grid_size=16)
    assert {record["preset"] for record in records} == {
        "baseline", "quick", "fidelity", "detail", "smooth"
    }
    assert all("mean_delta_e00" in record for record in records)


def test_material_comparison_quick():
    images = {"cartoon": make_benchmark_images(24)["cartoon"]}
    records = run_material_comparison(images, grid_size=16)
    assert {record["family"] for record in records} == {"minecraft", "beads"}
    assert all(record["legal_rate"] == 1.0 for record in records)
    assert all(record["direct_colors"] > 0 for record in records)


def test_environment_info_has_versions():
    info = environment_info()
    assert info["python"] and info["numpy"] and info["opencv"]


def test_auto_preset_rules_and_ui_options():
    image = np.random.default_rng(1).integers(0, 256, (32, 32, 3), dtype=np.uint8)
    large = pixel.resolve_settings({"preset": "auto", "colors": 16}, image, GridSpec(256, 256))
    assert large["preset"] == "quick"
    assert large["algorithm"] == "minibatch_rgb"

    flat = np.full((32, 32, 3), 100, np.uint8)
    small = pixel.resolve_settings({"preset": "auto", "colors": 16}, flat, GridSpec(32, 32))
    assert small["preset"] == "fidelity"
    assert "auto_reason" in small

    preset_keys = {key for key, _ in pixel.PRESET_OPTIONS}
    assert "detail" not in preset_keys
    assert "edge" not in {key for key, _ in pixel.SAMPLING_OPTIONS}
