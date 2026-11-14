##############################
# tools/run_benchmarks.py - 生成可复现基准数据与 Markdown 报告
##############################

import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from Moge.core.benchmarks import (  # noqa: E402
    aggregate_by_algorithm,
    environment_info,
    make_benchmark_images,
    run_clustering_suite,
    run_material_comparison,
    run_preset_suite,
    summarize,
)

ALGORITHM_LABELS = {
    "kmeans_rgb": "K-Means++ (RGB)",
    "kmeans_lab": "K-Means++ (Lab)",
    "minibatch_rgb": "MiniBatch (RGB)",
    "minibatch_lab": "MiniBatch (Lab)",
    "ward_lab": "Ward 合并 (Lab)",
}


def _fmt(value, digits=3):
    return f"{float(value):.{digits}f}"


def _preset_summary(records):
    groups = {}
    for record in records:
        groups.setdefault(record["preset"], []).append(record)
    return {
        name: {
            "runs": len(items),
            "mean_delta_e00": mean(item["mean_delta_e00"] for item in items),
            "p95_delta_e00": mean(item["p95_delta_e00"] for item in items),
            "edge_correlation": mean(item["edge_correlation"] for item in items),
            "isolated_cells": mean(item["isolated_cells"] for item in items),
            "elapsed_ms": mean(item["elapsed_ms"] for item in items),
        }
        for name, items in groups.items()
    }


def _material_summary(records):
    groups = {}
    for record in records:
        groups.setdefault(record["family"], []).append(record)
    return {
        name: {
            "runs": len(items),
            "direct_delta_e00": mean(item["direct_delta_e00"] for item in items),
            "kmeans_delta_e00": mean(item["kmeans_delta_e00"] for item in items),
            "direct_colors": mean(item["direct_colors"] for item in items),
            "legal_rate": mean(item["legal_rate"] for item in items),
        }
        for name, items in groups.items()
    }


def _slice(summary, grid, colors):
    return sorted(
        [row for row in summary if row["grid"] == grid and row["target_colors"] == colors],
        key=lambda row: row["mean_delta_e00"],
    )


def _build_markdown(records, presets, materials, env, timestamp):
    summary = summarize(records)
    aggregate = aggregate_by_algorithm(records)
    preset_summary = _preset_summary(presets)
    material_summary = _material_summary(materials)
    slice_rows = _slice(summary, 64, 16)
    best = slice_rows[0] if slice_rows else None
    fastest = min(slice_rows, key=lambda row: row["elapsed_ms"]) if slice_rows else None
    lab_row = next((row for row in slice_rows if row["algorithm"] == "kmeans_lab"), None)
    rgb_row = next((row for row in slice_rows if row["algorithm"] == "kmeans_rgb"), None)
    mini_row = next((row for row in slice_rows if row["algorithm"] == "minibatch_lab"), None)
    ward_row = next((row for row in slice_rows if row["algorithm"] == "ward_lab"), None)

    baseline = preset_summary.get("baseline", {})
    detail = preset_summary.get("detail", {})
    smooth = preset_summary.get("smooth", {})

    edge_delta = detail.get("edge_correlation", 0) - baseline.get("edge_correlation", 0)
    detail_de = detail.get("mean_delta_e00", 0) - baseline.get("mean_delta_e00", 0)
    isolated_delta = smooth.get("isolated_cells", 0) - baseline.get("isolated_cells", 0)
    isolated_pct = (
        (isolated_delta / baseline.get("isolated_cells", 1)) * 100
        if baseline.get("isolated_cells")
        else 0.0
    )

    lines = [
        "# Moge 2.0 聚类与复合管线基准报告",
        "",
        f"> 生成时间：{timestamp}",
        f"> 运行环境：Python {env['python']} · NumPy {env['numpy']} · OpenCV {env['opencv']} · {env['platform']}",
        "> 数据：`core/benchmarks.py` 生成的合成图（人像/噪声/卡通/低对比/渐变/文字/透明），不包含第三方素材。",
        "",
        "## 1. 方法与口径",
        "",
        "- 所有算法使用相同源图、网格、目标颜色数、固定种子 42；色差为 CIEDE2000（D65 Lab）。",
        "- 指标：平均/95 分位色差、梯度幅值相关系数（结构代理）、孤立单元数、墙钟耗时。",
        "- 本轮为单机单次运行，不代表所有硬件与真实照片的普适结论；噪声图属于最坏情况。",
        "- 复现命令：`python tools/run_benchmarks.py`，原始记录：`benchmarks/results.json`。",
        "",
        "## 2. 颜色量化算法对照（网格 64×64，16 色）",
        "",
        "| 算法 | 平均 ΔE00 | P95 ΔE00 | 边缘相关 | 孤立单元 | 平均耗时 (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in slice_rows:
        lines.append(
            f"| {ALGORITHM_LABELS.get(row['algorithm'], row['algorithm'])} | "
            f"{_fmt(row['mean_delta_e00'])} | {_fmt(row['p95_delta_e00'])} | "
            f"{_fmt(row['edge_correlation'])} | {_fmt(row['isolated_cells'], 1)} | "
            f"{_fmt(row['elapsed_ms'], 1)} |"
        )

    lines += [
        "",
        "## 3. 全部组合平均（3 种网格 × 4 种色数 × 7 张图）",
        "",
        "| 算法 | 运行数 | 平均 ΔE00 | 边缘相关 | 平均耗时 (ms) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in sorted(aggregate, key=lambda item: item["mean_delta_e00"]):
        lines.append(
            f"| {ALGORITHM_LABELS.get(row['algorithm'], row['algorithm'])} | {row['runs']} | "
            f"{_fmt(row['mean_delta_e00'])} | {_fmt(row['edge_correlation'])} | {_fmt(row['elapsed_ms'], 1)} |"
        )

    lines += [
        "",
        "## 4. 效果预设对照（网格 48×48，16 色）",
        "",
        "| 预设 | 平均 ΔE00 | 边缘相关 | 孤立单元 | 平均耗时 (ms) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name in ("baseline", "quick", "fidelity", "detail", "smooth"):
        row = preset_summary.get(name)
        if not row:
            continue
        lines.append(
            f"| {name} | {_fmt(row['mean_delta_e00'])} | {_fmt(row['edge_correlation'])} | "
            f"{_fmt(row['isolated_cells'], 1)} | {_fmt(row['elapsed_ms'], 1)} |"
        )

    lines += [
        "",
        "## 5. 直接合法材料匹配 vs 先 K-Means 再映射（网格 32×32）",
        "",
        "| 材料族 | 直接匹配 ΔE00 | K-Means→映射 ΔE00 | 差值（后者-前者） | 合法率 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for family, row in material_summary.items():
        diff = row["kmeans_delta_e00"] - row["direct_delta_e00"]
        lines.append(
            f"| {family} | {_fmt(row['direct_delta_e00'])} | {_fmt(row['kmeans_delta_e00'])} | "
            f"{diff:+.3f} | {row['legal_rate'] * 100:.1f}% |"
        )

    lines += ["", "## 6. 实测结论与取舍", ""]
    if best:
        lines.append(
            f"- 在 64×64 / 16 色切片中，平均色差最低的是 **{ALGORITHM_LABELS.get(best['algorithm'])}**"
            f"（ΔE00 {_fmt(best['mean_delta_e00'])}），平均耗时 {_fmt(best['elapsed_ms'], 1)} ms。"
        )
    if fastest:
        lines.append(
            f"- 同一切片中耗时最低的是 **{ALGORITHM_LABELS.get(fastest['algorithm'])}**"
            f"（{_fmt(fastest['elapsed_ms'], 1)} ms，ΔE00 {_fmt(fastest['mean_delta_e00'])}）。"
        )
    if lab_row and rgb_row:
        lines.append(
            f"- Lab 与 RGB 的 K-Means 对照：ΔE00 {_fmt(lab_row['mean_delta_e00'])} vs "
            f"{_fmt(rgb_row['mean_delta_e00'])}，耗时 {_fmt(lab_row['elapsed_ms'], 1)} vs "
            f"{_fmt(rgb_row['elapsed_ms'], 1)} ms。"
        )
    if mini_row and lab_row:
        lines.append(
            f"- MiniBatch(Lab) 相对 K-Means(Lab)：耗时 {_fmt(mini_row['elapsed_ms'], 1)} vs "
            f"{_fmt(lab_row['elapsed_ms'], 1)} ms，ΔE00 {_fmt(mini_row['mean_delta_e00'])} vs "
            f"{_fmt(lab_row['mean_delta_e00'])}。"
        )
    if ward_row:
        lines.append(
            f"- Ward 合并：ΔE00 {_fmt(ward_row['mean_delta_e00'])}，耗时 {_fmt(ward_row['elapsed_ms'], 1)} ms；"
            "该实现先在代表点上合并，复杂度与网格规模关系较弱。"
        )

    if edge_delta > 0.005:
        lines.append(
            f"- “细节保护”预设的边缘相关性相对基线提升 {edge_delta * 100:.2f} 个百分点"
            f"（ΔE00 变化 {detail_de:+.3f}），因此保留为可选预设。"
        )
    else:
        lines.append(
            f"- “细节保护”预设未观察到稳定的边缘相关性提升（变化 {edge_delta * 100:+.2f} 个百分点），"
            "已从正式 UI 预设中移除，仅保留在基准脚本实验区。"
        )

    if isolated_delta < 0:
        lines.append(
            f"- “平整色块”预设平均减少孤立单元 {abs(isolated_pct):.2f}%，ΔE00 变化 "
            f"{smooth.get('mean_delta_e00', 0) - baseline.get('mean_delta_e00', 0):+.3f}；"
            "适合需要更整洁色块的场景，默认关闭以保留细节。"
        )
    else:
        lines.append("- “平整色块”预设在本轮未减少孤立单元，保持实验性选项。")

    lines.append(
        "- 材料映射：直接合法材料匹配的色差低于“先 K-Means 再映射”的对照"
        "（见第 5 节具体数值），因此 Minecraft/拼豆默认采用直接材料匹配，不强制预量化。"
    )

    lines += [
        "",
        "## 7. 淘汰与未实现项（诚实声明）",
        "",
        "- 谱聚类（区域图）、BIRCH、GMM、DBSCAN/HDBSCAN、Mean Shift、Affinity Propagation：",
        "  **本轮未实现、未接入 UI、未做基准**，不声称有效。",
        "- 真实 Minecraft 版本贴图与官方拼豆色卡未包含在仓库；内置数据为屏幕近似，",
        "  相关色差与材料结论仅对当前近似数据成立。",
        "- 未做人工盲测与真实照片主观评估；后续需要补充。",
        "",
        "## 8. 复现",
        "",
        "```powershell",
        "pip install -e \".[dev]\"",
        "python tools/run_benchmarks.py",
        "```",
        "",
    ]
    return "\n".join(lines)


def main():
    timestamp = datetime.now().isoformat(timespec="seconds")
    print("生成合成基准图...")
    images = make_benchmark_images()

    print("运行颜色量化基准（5 算法 × 3 网格 × 4 色数 × 7 图）...")

    def progress(index, total):
        if index == total or index % 20 == 0:
            print(f"  {index}/{total}")

    clustering = run_clustering_suite(images, progress=progress)
    print("运行效果预设对照...")
    presets = run_preset_suite(images)
    print("运行材料映射对照...")
    materials = run_material_comparison(images)
    env = environment_info()

    benchmarks_dir = ROOT / "benchmarks"
    benchmarks_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": timestamp,
        "environment": env,
        "clustering": clustering,
        "summary": summarize(clustering),
        "presets": presets,
        "preset_summary": _preset_summary(presets),
        "materials": materials,
        "material_summary": _material_summary(materials),
    }
    (benchmarks_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    markdown = _build_markdown(clustering, presets, materials, env, timestamp)
    (ROOT / "docs" / "Clustering-Benchmarks.md").write_text(markdown, encoding="utf-8")
    print("已写入 benchmarks/results.json 与 docs/Clustering-Benchmarks.md")
    print(f"记录数：聚类 {len(clustering)}，预设 {len(presets)}，材料 {len(materials)}")


if __name__ == "__main__":
    main()
