##############################
# utils/logger.py - 日志配置
##############################

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 日志格式
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_resource_path(relative_path: str) -> Path:
    """ 获取资源路径（兼容开发和打包环境） """
    if hasattr(sys, '_MEIPASS'):  # 判断是否为打包后的应用
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).resolve().parent.parent  # 根据实际层级调整
    return base_dir / relative_path


def configure_logger():
    """ 配置全局日志系统 """

    # 获取日志目录路径
    log_dir = get_resource_path("Moge/utils/logs")
    log_dir.mkdir(parents=True, exist_ok=True)  # 确保日志目录存在

    # 日志文件路径
    log_file = log_dir / "app.log"

    # 创建日志器
    logger = logging.getLogger("Moge")  # 日志器名称
    logger.setLevel(logging.DEBUG)  # 设置日志级别为 DEBUG（可以根据需要调整）

    # 清除已有的 handlers（防止重复添加）
    if logger.hasHandlers():
        logger.handlers.clear()

    # 文件 handler（按 50MB 轮转，保留 7 个备份）
    file_handler = RotatingFileHandler(
        log_file,  # 日志文件路径
        maxBytes=50 * 1024 * 1024,  # 最大文件大小：50MB
        backupCount=7,  # 保留 7 个备份
        encoding="utf-8"  # 设置编码为 UTF-8
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    file_handler.setLevel(logging.INFO)

    # 控制台 handler（用于输出到终端）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    console_handler.setLevel(logging.DEBUG)

    # 添加 handlers 到日志器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def get_module_logger(name: str):
    """ 获取模块日志器 """
    return logging.getLogger(f"Moge.{name}")

