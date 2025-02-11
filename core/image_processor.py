##############################
# core/image_processor.py - 图像处理核心
##############################

import math
from collections import defaultdict

import cv2
import numpy as np
from sklearn.cluster import KMeans


def img_resize(img, block_size, resize_method):
    """
    图像缩放
    :param img:           待处理图像
    :param block_size:    像素块大小
    :param resize_method: 调整方法
    :return:
    """

    h, w = img.shape[:2]  # 获取图像尺寸，h为高度，w为宽度

    # 调整图像大小
    if resize_method == '向上取整':
        # 向上取整
        new_h = math.ceil(h // block_size) * block_size
        new_w = math.ceil(w // block_size) * block_size
    elif resize_method == '向下取整':
        # 向下取整
        new_h = math.floor(h // block_size) * block_size
        new_w = math.floor(w // block_size) * block_size
    elif resize_method == '四舍五入':
        # 四舍五入
        new_h = math.floor(h / block_size) * block_size
        new_w = math.floor(w / block_size) * block_size
    else:
        # 异常处理
        new_h = h
        new_w = w

    # 调整图像大小以适应像素块大小
    if new_h != h or new_w != w:  # 如果调整后图像大小不同于原图大小
        img = cv2.resize(img, (new_w, new_h))  # 调整图像大小

    return img


def img_pixelize_mean(img, block_size):
    """
    图像均值像素化
    :param img:        待处理图像
    :param block_size: 像素块大小
    :return:
    """

    h, w = img.shape[:2]  # 获取图像尺寸，h为高度，w为宽度

    # 创建处理副本
    processed = img.copy().astype(np.float32)

    # 分块处理
    for y in range(0, h, block_size):
        for x in range(0, w, block_size):
            y_end = min(y + block_size, h)
            x_end = min(x + block_size, w)

            # 计算区块均值
            block = processed[y:y_end, x:x_end]
            avg_color = np.mean(block, axis=(0, 1))

            # 填充颜色
            processed[y:y_end, x:x_end] = avg_color

    return processed.astype(np.uint8)


def img_pixelize_common(img, block_size):
    """
    图像频数像素化
    :param img:        待处理图像
    :param block_size: 像素块大小
    """

    h, w = img.shape[:2]

    # 创建处理副本
    processed = img.copy().astype(np.float32)

    # 计算图像中每个像素块的最常见颜色及其频率
    def mode_color(block, ignore_alpha=False):
        """
        计算像素块中最常见的颜色及其频率
        :param block:
        :param ignore_alpha:
        :return:
        """

        counter = defaultdict(int)
        total = 0
        for y in range(block.shape[0]):
            for x in range(block.shape[1]):
                pixel = block[y, x]
                # 忽略alpha通道或透明像素
                if len(pixel) < 4 or ignore_alpha or pixel[3] != 0:
                    counter[tuple(pixel[:3])] += 1
                else:
                    counter[(-1, -1, -1)] += 1
                total += 1

        if total > 0:
            common_color = max(counter, key=counter.get)
            if common_color == (-1, -1, -1):  # 如果透明像素最多，则返回 None
                return None, None
            else:
                return common_color, counter[common_color] / total
        else:
            return None, None

    # 对图像进行像素化处理
    for i in range(0, w, block_size):
        for j in range(0, h, block_size):
            # 获取每个像素块的区域
            region = img[j:min(j + block_size, h), i:min(i + block_size, w)]

            # 获取该区域的最常见颜色
            most_common_color, _ = mode_color(region)

            if most_common_color:
                # 将该区域填充为最常见的颜色
                processed[j:min(j + block_size, h), i:min(i + block_size, w)] = most_common_color

    return processed.astype(np.uint8)


def color_clustering(img, n_colors, seed):
    """
    颜色聚类
    :param img:      待处理图像
    :param n_colors:    聚类数
    :return:
    """

    h, w = img.shape[:2]

    # 转换为二维数组
    pixels = img.reshape(-1, 3)

    # 执行聚类
    kmeans = KMeans(n_clusters=n_colors, random_state=seed)
    labels = kmeans.fit_predict(pixels)

    # 生成压缩图像
    compressed = kmeans.cluster_centers_[labels].reshape(h, w, 3)
    return compressed.astype(np.uint8)
