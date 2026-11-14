##############################
# core/image_processor.py - 图像处理核心
##############################

import math
from enum import Enum

import cv2
import numpy as np


class ResizeMode(Enum):
    """ 图像尺寸调整方式（UI 显示文本与算法参数保持一致） """

    CEIL = '向上取整'
    FLOOR = '向下取整'
    ROUND = '四舍五入'


class ProcessingCancelled(Exception):
    """ 用户取消处理时抛出，用于中断计算流程 """


def _fit_length(length, block_size, mode):
    """
    将单边长度调整为像素块大小的整数倍
    :param length:     原始长度
    :param block_size: 像素块大小
    :param mode:       ResizeMode 调整方式
    :return:           调整后的长度
    """

    if mode is ResizeMode.CEIL:
        fitted = math.ceil(length / block_size) * block_size
    elif mode is ResizeMode.ROUND:
        fitted = math.floor(length / block_size + 0.5) * block_size
    else:  # ResizeMode.FLOOR
        fitted = (length // block_size) * block_size

    return max(block_size, fitted)  # 至少保留一个像素块


def img_resize(img, block_size, resize_method):
    """
    图像缩放
    :param img:           待处理图像
    :param block_size:    像素块大小
    :param resize_method: 调整方法（ResizeMode 或对应的中文名称）
    :return:              调整尺寸后的图像
    """

    if block_size < 1:
        raise ValueError("像素块大小必须大于 0")

    mode = ResizeMode(resize_method)  # 兼容传入中文名称的调用方
    h, w = img.shape[:2]  # 获取图像尺寸，h为高度，w为宽度

    new_h = _fit_length(h, block_size, mode)
    new_w = _fit_length(w, block_size, mode)

    # 调整图像大小以适应像素块大小
    if new_h != h or new_w != w:  # 如果调整后图像大小不同于原图大小
        img = cv2.resize(img, (new_w, new_h))  # 调整图像大小

    return img


def _pad_to_blocks(img, block_size):
    """ 将图像边缘补齐为像素块整数倍（复制边缘像素，不改变画面内容） """
    h, w = img.shape[:2]
    pad_h, pad_w = (-h) % block_size, (-w) % block_size
    if pad_h or pad_w:
        img = np.pad(img, ((0, pad_h), (0, pad_w), (0, 0)), mode='edge')
    return img


def img_pixelize_mean(img, block_size):
    """
    图像均值像素化（向量化实现）
    :param img:        待处理图像
    :param block_size: 像素块大小
    :return:           像素化后的图像
    """

    if block_size < 1:
        raise ValueError("像素块大小必须大于 0")

    h, w = img.shape[:2]
    padded = _pad_to_blocks(img, block_size)
    block_rows = padded.shape[0] // block_size
    block_cols = padded.shape[1] // block_size

    # 一次性按块求均值，再用最近邻复制回原尺寸
    blocks = padded.reshape(block_rows, block_size, block_cols, block_size, 3)
    avg = blocks.mean(axis=(1, 3), dtype=np.float32).astype(np.uint8)
    processed = np.repeat(np.repeat(avg, block_size, axis=0), block_size, axis=1)

    return processed[:h, :w]


def _mode_colors(blocks):
    """
    逐块计算众数颜色
    :param blocks: (块数, 块内像素数, 3) 的 uint8 数组
    :return:       每个块的众数颜色（打包为 uint32，平局时取最先出现的颜色）
    """

    # 将 RGB 打包成单个整数，便于快速比较与去重
    packed = (blocks[..., 0].astype(np.uint32) << 16) | \
             (blocks[..., 1].astype(np.uint32) << 8) | \
             blocks[..., 2].astype(np.uint32)

    colors = np.empty(len(packed), np.uint32)
    for i, row in enumerate(packed):
        values, first_index, counts = np.unique(row, return_index=True, return_counts=True)
        if len(values) == len(row):  # 块内颜色互不相同，直接取左上角像素
            colors[i] = row[0]
            continue

        max_count = counts.max()
        mask = counts == max_count
        # 与原实现一致：众数并列时取最先出现的颜色
        colors[i] = values[mask][np.argmin(first_index[mask])]

    return colors


def img_pixelize_common(img, block_size, should_cancel=None, progress_callback=None):
    """
    图像频数像素化（向量化实现）
    :param img:               待处理图像
    :param block_size:        像素块大小
    :param should_cancel:     可选取消检查函数，返回 True 时抛出 ProcessingCancelled
    :param progress_callback: 可选进度回调，参数为 0~1 的比例
    :return:                  像素化后的图像
    """

    if block_size < 1:
        raise ValueError("像素块大小必须大于 0")

    h, w = img.shape[:2]
    padded = _pad_to_blocks(img, block_size)
    block_rows = padded.shape[0] // block_size
    block_cols = padded.shape[1] // block_size

    processed_blocks = np.empty((block_rows, block_cols, 3), np.uint8)
    chunk_rows = max(1, 4000 // max(1, block_cols))  # 控制单批内存占用与取消响应延迟

    for r0 in range(0, block_rows, chunk_rows):
        if should_cancel is not None and should_cancel():
            raise ProcessingCancelled()

        r1 = min(r0 + chunk_rows, block_rows)
        blocks = padded[r0 * block_size:r1 * block_size, :, :].reshape(
            r1 - r0, block_size, block_cols, block_size, 3
        ).transpose(0, 2, 1, 3, 4).reshape(-1, block_size * block_size, 3)

        colors = _mode_colors(blocks).reshape(r1 - r0, block_cols)
        processed_blocks[r0:r1, :, 0] = (colors >> 16) & 0xFF
        processed_blocks[r0:r1, :, 1] = (colors >> 8) & 0xFF
        processed_blocks[r0:r1, :, 2] = colors & 0xFF

        if progress_callback is not None:
            progress_callback(r1 / block_rows)

    processed = np.repeat(np.repeat(processed_blocks, block_size, axis=0), block_size, axis=1)

    return processed[:h, :w]


def color_clustering(img, n_colors, seed, should_cancel=None, progress_callback=None):
    """
    颜色聚类压缩（采样拟合 + 分批归类，使用 OpenCV 实现）
    :param img:               待处理图像
    :param n_colors:          聚类数量
    :param seed:              随机种子
    :param should_cancel:     可选取消检查函数，返回 True 时抛出 ProcessingCancelled
    :param progress_callback: 可选进度回调，参数为 0~1 的比例
    :return:                  颜色压缩后的图像
    """

    if n_colors < 1:
        raise ValueError("聚类数量必须大于 0")

    h, w = img.shape[:2]
    pixels = img.reshape(-1, 3)
    total = len(pixels)

    # 采样：控制拟合规模，避免全分辨率聚类的分钟级耗时
    step = max(1, total // 50000)
    sample_u8 = pixels[::step]
    sample = sample_u8.astype(np.float32)

    # 颜色数本来就不超过目标值，直接返回原图
    if len(np.unique(sample_u8, axis=0)) <= n_colors:
        if progress_callback is not None:
            progress_callback(1.0)
        return img.copy()

    cv2.setRNGSeed(int(seed))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, _, centers = cv2.kmeans(
        sample, n_colors, None, criteria, 1, cv2.KMEANS_PP_CENTERS
    )

    # 分批计算到各聚类中心的距离，避免生成 N×K 的巨型中间数组
    out = np.empty((total, 3), np.uint8)
    batch_size = 100000
    centers_sq = (centers * centers).sum(axis=1)
    batch_count = max(1, (total + batch_size - 1) // batch_size)

    for batch_index, start in enumerate(range(0, total, batch_size)):
        if should_cancel is not None and should_cancel():
            raise ProcessingCancelled()

        end = min(start + batch_size, total)
        batch = pixels[start:end].astype(np.float32)
        distances = (batch * batch).sum(axis=1)[:, None] - 2.0 * batch @ centers.T + centers_sq[None, :]
        out[start:end] = centers[np.argmin(distances, axis=1)].astype(np.uint8)

        if progress_callback is not None:
            progress_callback((batch_index + 1) / batch_count)

    return out.reshape(h, w, 3)
