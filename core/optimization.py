##############################
# core/optimization.py - 空间与调色板优化
##############################

from typing import Callable, Optional

import numpy as np

from Moge.core.color_spaces import delta_e_00, srgb_to_lab


def reduce_isolated(
    labels: np.ndarray,
    entries: list,
    max_delta: float = 6.0,
    iterations: int = 1,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> tuple[np.ndarray, int]:
    """
    将孤立单元合并到色差最近的邻居，减少碎片但不删除真实细节
    :param max_delta: 允许合并的最大 CIEDE2000 色差
    :return: (新标签, 改动单元数)
    """
    if not entries:
        return labels.copy(), 0

    result = np.asarray(labels, dtype=np.int32).copy()
    palette_lab = srgb_to_lab(np.array([entry.rgb for entry in entries], dtype=np.uint8))
    height, width = result.shape
    changed_total = 0

    for _ in range(max(1, iterations)):
        changed = 0
        for row in range(height):
            for col in range(width):
                value = int(result[row, col])
                if value < 0:
                    continue

                neighbors = []
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    r = row + dy
                    c = col + dx
                    if 0 <= r < height and 0 <= c < width:
                        neighbor = int(result[r, c])
                        if neighbor >= 0 and neighbor != value:
                            neighbors.append(neighbor)
                if not neighbors or any(
                    0 <= r < height and 0 <= c < width and int(result[r, c]) == value
                    for r, c in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1))
                ):
                    continue

                unique_neighbors = np.unique(np.array(neighbors, dtype=np.int32))
                deltas = delta_e_00(palette_lab[value], palette_lab[unique_neighbors])
                best = int(np.argmin(deltas))
                if float(deltas[best]) <= max_delta:
                    result[row, col] = unique_neighbors[best]
                    changed += 1

        changed_total += changed
        if changed == 0:
            break

    return result, changed_total
