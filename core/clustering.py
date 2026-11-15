##############################
# core/clustering.py - 颜色量化算法注册表
##############################

from dataclasses import dataclass, field
from typing import Callable, Optional

import cv2
import numpy as np

from Moge.core.color_spaces import lab_to_rgb, srgb_to_lab
from Moge.core.image_processor import ProcessingCancelled


@dataclass
class ClusterOutput:
    """ 量化结果：RGB 代表色、每个样本的标签与诊断信息 """

    centers_rgb: np.ndarray
    labels: np.ndarray
    diagnostics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class AlgorithmInfo:
    """ 算法元信息，用于 UI 展示与基准测试 """

    key: str
    label: str
    space: str
    description: str


ALGORITHM_INFO: dict[str, AlgorithmInfo] = {
    "kmeans_rgb": AlgorithmInfo("kmeans_rgb", "K-Means++ (RGB)", "rgb", "通用基线，速度稳定"),
    "kmeans_lab": AlgorithmInfo("kmeans_lab", "K-Means++ (Lab)", "lab", "感知色差更均衡"),
    "minibatch_rgb": AlgorithmInfo("minibatch_rgb", "MiniBatch K-Means (RGB)", "rgb", "大图快速预览"),
    "minibatch_lab": AlgorithmInfo("minibatch_lab", "MiniBatch K-Means (Lab)", "lab", "快速且感知友好"),
    "ward_lab": AlgorithmInfo("ward_lab", "Ward 合并 (Lab)", "lab", "代表点层次合并，色块更整齐"),
    "spectral_lab": AlgorithmInfo(
        "spectral_lab", "谱聚类区域 (实验)", "lab", "仅限 ≤1024 个网格区域，实验区使用"
    ),
}

# 仅在基准实验中启用，不进入正式 UI
EXPERIMENTAL_ALGORITHMS = {"spectral_lab"}
SPECTRAL_MAX_NODES = 1024


def _subsample(pixels: np.ndarray, limit: int = 50000) -> np.ndarray:
    if len(pixels) <= limit:
        return pixels
    step = max(1, len(pixels) // limit)
    return pixels[::step][:limit]


def _features(pixels: np.ndarray, space: str) -> np.ndarray:
    if space == "lab":
        return srgb_to_lab(pixels).astype(np.float32)
    return pixels.astype(np.float32)


def _kmeans_once(features: np.ndarray, k: int, seed: int):
    cv2.setRNGSeed(int(seed))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
    _, labels, centers = cv2.kmeans(
        features, k, None, criteria, 1, cv2.KMEANS_PP_CENTERS
    )
    return centers.astype(np.float32), labels.reshape(-1).astype(np.int32)


def _minibatch(features: np.ndarray, k: int, seed: int, batch_size: int = 4096, max_iter: int = 20):
    rng = np.random.default_rng(seed)
    count = len(features)
    if count <= k:
        return features.copy(), np.arange(count, dtype=np.int32)

    centers = features[rng.choice(count, size=k, replace=False)].copy()
    counts = np.ones(k, dtype=np.float64)

    for _ in range(max_iter):
        order = rng.permutation(count)
        for start in range(0, count, batch_size):
            batch = features[order[start:start + batch_size]]
            distances = (
                np.sum(batch * batch, axis=1)[:, None]
                - 2.0 * batch @ centers.T
                + np.sum(centers * centers, axis=1)[None, :]
            )
            labels = np.argmin(distances, axis=1)
            batch_counts = np.bincount(labels, minlength=k).astype(np.float64)
            sums = np.stack(
                [
                    np.bincount(labels, weights=batch[:, dim], minlength=k)
                    for dim in range(features.shape[1])
                ],
                axis=1,
            )
            counts += batch_counts
            centers = (centers * (counts - batch_counts)[:, None] + sums) / np.maximum(counts, 1.0)[:, None]

    labels = _assign(features, centers)
    return centers.astype(np.float32), labels


def _ward(features: np.ndarray, k: int, seed: int, initial: int = 64):
    unique_count = len(np.unique(features, axis=0))
    initial = min(initial, unique_count)
    if initial <= k:
        centers = np.unique(features, axis=0).astype(np.float32)
        labels = _assign(features, centers)
        return centers, labels

    centers, initial_labels = _kmeans_once(features, initial, seed)
    counts = np.bincount(initial_labels, minlength=len(centers)).astype(np.float64)

    while len(centers) > k:
        diff = centers[:, None, :] - centers[None, :, :]
        squared = np.sum(diff * diff, axis=2)
        weights = counts[:, None] * counts[None, :] / (counts[:, None] + counts[None, :] + 1e-9)
        cost = squared * weights
        np.fill_diagonal(cost, np.inf)
        upper = np.triu_indices(len(centers), k=1)
        flat_index = int(np.argmin(cost[upper]))
        i = int(upper[0][flat_index])
        j = int(upper[1][flat_index])
        total = counts[i] + counts[j]
        centers[i] = (centers[i] * counts[i] + centers[j] * counts[j]) / total
        counts[i] = total
        centers = np.delete(centers, j, axis=0)
        counts = np.delete(counts, j)

    labels = _assign(features, centers)
    return centers.astype(np.float32), labels


def _assign(features: np.ndarray, centers: np.ndarray, batch_size: int = 100000) -> np.ndarray:
    labels = np.empty(len(features), dtype=np.int32)
    centers_sq = np.sum(centers * centers, axis=1)
    for start in range(0, len(features), batch_size):
        batch = features[start:start + batch_size]
        distances = (
            np.sum(batch * batch, axis=1)[:, None]
            - 2.0 * batch @ centers.T
            + centers_sq[None, :]
        )
        labels[start:start + len(batch)] = np.argmin(distances, axis=1)
    return labels


def _spectral(features: np.ndarray, k: int, seed: int, neighbors: int = 8):
    """ 在网格区域图上做归一化谱聚类；只允许小规模节点，避免 N×N 爆炸 """
    count = len(features)
    if count > SPECTRAL_MAX_NODES:
        raise ValueError(f"谱聚类仅支持 ≤{SPECTRAL_MAX_NODES} 个区域，当前 {count}")

    squared = np.sum(features * features, axis=1)
    distance2 = squared[:, None] + squared[None, :] - 2.0 * features @ features.T
    np.maximum(distance2, 0.0, out=distance2)

    neighbor_count = min(max(1, neighbors), max(1, count - 1))
    order = np.argsort(distance2, axis=1)[:, 1:neighbor_count + 1]
    positive = distance2[distance2 > 0]
    sigma = float(np.median(positive)) if positive.size else 1.0
    sigma = max(sigma, 1e-9)

    weights = np.zeros_like(distance2)
    rows = np.arange(count)[:, None]
    weights[rows, order] = np.exp(-distance2[rows, order] / (2.0 * sigma))
    weights = np.maximum(weights, weights.T)

    degree = weights.sum(axis=1)
    degree[degree == 0] = 1.0
    inv_sqrt = 1.0 / np.sqrt(degree)
    laplacian = np.eye(count) - (inv_sqrt[:, None] * weights * inv_sqrt[None, :])

    _values, vectors = np.linalg.eigh(laplacian)
    embedding = vectors[:, 1:k + 1]
    norms = np.linalg.norm(embedding, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    embedding = embedding / norms

    _centers, labels = _kmeans_once(embedding.astype(np.float32), k, seed)
    centers = np.stack(
        [
            features[labels == index].mean(axis=0) if np.any(labels == index) else features.mean(axis=0)
            for index in range(k)
        ]
    )
    return centers.astype(np.float32), labels


def quantize(
    pixels: np.ndarray,
    target_colors: int,
    algorithm: str = "kmeans_lab",
    seed: int = 42,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> ClusterOutput:
    """ 对 RGB 像素执行颜色量化，返回代表色与全量标签 """
    if target_colors < 1:
        raise ValueError("目标颜色数必须大于 0")
    if algorithm not in ALGORITHM_INFO:
        raise ValueError(f"未知量化算法：{algorithm}")

    rgb = np.asarray(pixels, dtype=np.uint8).reshape(-1, 3)
    if len(rgb) == 0:
        raise ValueError("没有可量化的像素")

    if should_cancel is not None and should_cancel():
        raise ProcessingCancelled()

    sample = _subsample(rgb)
    unique_count = len(np.unique(sample, axis=0))
    k = min(target_colors, unique_count)
    space = ALGORITHM_INFO[algorithm].space
    features = _features(sample, space)

    if k <= 1:
        center = features.mean(axis=0, keepdims=True).astype(np.float32)
        labels = np.zeros(len(rgb), dtype=np.int32)
        centers_rgb = np.clip(np.rint(center), 0, 255).astype(np.uint8)
        if space == "lab":
            centers_rgb = lab_to_rgb(center)
        return ClusterOutput(centers_rgb=centers_rgb, labels=labels, diagnostics={"actual_colors": 1})

    if algorithm.startswith("minibatch"):
        centers, _ = _minibatch(features, k, seed)
        iterations = 20
        fallback = False
    elif algorithm == "ward_lab":
        centers, _ = _ward(features, k, seed)
        iterations = 0
        fallback = False
    elif algorithm == "spectral_lab":
        if len(features) > SPECTRAL_MAX_NODES:
            centers, _ = _kmeans_once(features, k, seed)
            fallback = True
        else:
            centers, _ = _spectral(features, k, seed)
            fallback = False
        iterations = 0
    else:
        centers, _ = _kmeans_once(features, k, seed)
        iterations = 20
        fallback = False

    if should_cancel is not None and should_cancel():
        raise ProcessingCancelled()

    # 全量像素分批映射，避免 N×K×3 的巨型中间数组
    all_features = _features(rgb, space)
    labels = _assign(all_features, centers)

    if space == "lab":
        centers_rgb = lab_to_rgb(centers)
    else:
        centers_rgb = np.clip(np.rint(centers), 0, 255).astype(np.uint8)

    diagnostics = {
        "requested_colors": float(target_colors),
        "actual_colors": float(len(centers_rgb)),
        "sample_size": float(len(sample)),
        "space": space,
        "iterations": float(iterations),
        "spectral_fallback": float(fallback),
    }
    return ClusterOutput(centers_rgb=centers_rgb, labels=labels, diagnostics=diagnostics)


def algorithm_labels() -> list[str]:
    return [info.label for info in ALGORITHM_INFO.values()]


def algorithm_keys() -> list[str]:
    return list(ALGORITHM_INFO.keys())
