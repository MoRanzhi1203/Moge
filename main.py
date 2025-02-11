##############################
# main.py - 程序入口
##############################

import sys

from PyQt5.QtCore import QSharedMemory
from PyQt5.QtWidgets import QApplication, QMessageBox

from Moge.utils.logger_config import configure_logger
from Moge.ui.main_window import MainWindow


def is_another_instance_running():
    """ 检查是否已有另一个程序实例在运行 """
    shared_memory = QSharedMemory('app_single_instance_shared_memory')  # 创建共享内存
    if shared_memory.attach():  # 如果共享内存已经存在，表示程序已经运行
        return True
    if not shared_memory.create(1):  # 如果共享内存不能创建，表示已经有实例在运行
        return True
    return False


def main():
    # 初始化日志
    logger = configure_logger()  # 调用日志配置函数
    logger.info("====== 应用程序启动 ======")

    # 检查是否已有程序实例在运行
    if is_another_instance_running():
        logger.warning("应用程序已经在运行，请关闭当前实例后再启动。")
        QMessageBox.warning(None, "警告", "应用程序已经在运行，请关闭当前实例后再启动。")
        sys.exit(1)  # 退出当前程序，防止重复启动

    # 创建Qt应用
    app = QApplication(sys.argv)  # sys.argv是命令行参数列表

    # 初始化主窗口
    window = MainWindow()  # 创建MainWindow对象
    window.setWindowTitle('墨格 - 图像像素化处理器')  # 设置窗口标题
    window.show()  # 显示窗口

    # 记录启动完成
    logger.info("主窗口初始化完成")

    # 启动事件循环
    exit_code = app.exec_()  # 启动事件循环，直到退出
    logger.info(f"应用程序退出，代码: {exit_code}")  # 记录退出代码

    sys.exit(exit_code)  # 程序退出时返回退出代码


if __name__ == "__main__":
    # 程序入口
    main()  # 调用main()函数
