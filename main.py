##############################
# main.py - 程序入口
##############################

import sys
from pathlib import Path

# 确保 Moge 包可被导入，支持从任意工作目录启动
_PACKAGE_PARENT = str(Path(__file__).resolve().parent.parent)
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)

from PyQt5.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from Moge.ui.main_window import MainWindow  # noqa: E402
from Moge.utils.logger_config import configure_logger  # noqa: E402


class SingleInstanceGuard:
    """ 基于本地套接字的单实例守卫（进程退出后端点自动释放） """

    def __init__(self, key="Moge_single_instance"):
        self._key = key
        self._server = None

    def acquire(self):
        """ 尝试占用单实例端点，成功返回 True """
        probe = QLocalSocket()
        probe.connectToServer(self._key)
        if probe.waitForConnected(300):  # 已有实例在监听
            probe.disconnectFromServer()
            return False

        # 清理异常退出遗留的端点后重新监听
        QLocalServer.removeServer(self._key)
        self._server = QLocalServer()
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        return self._server.listen(self._key)


def main():
    # 初始化日志
    logger = configure_logger()  # 调用日志配置函数
    logger.info("====== 应用程序启动 ======")

    # 必须先创建 Qt 应用，再使用任何 Qt 控件
    app = QApplication(sys.argv)  # sys.argv是命令行参数列表

    # 检查是否已有程序实例在运行
    guard = SingleInstanceGuard()
    if not guard.acquire():
        logger.warning("应用程序已经在运行，请关闭当前实例后再启动。")
        QMessageBox.warning(None, "警告", "应用程序已经在运行，请关闭当前实例后再启动。")
        return 1  # 退出当前程序，防止重复启动

    # 初始化主窗口
    window = MainWindow()  # 创建MainWindow对象
    window.setWindowTitle('墨格 - 图像像素化处理器')  # 设置窗口标题
    window.show()  # 显示窗口

    # 记录启动完成
    logger.info("主窗口初始化完成")

    # 启动事件循环
    exit_code = app.exec_()  # 启动事件循环，直到退出
    logger.info(f"应用程序退出，代码: {exit_code}")  # 记录退出代码

    return exit_code  # 程序退出时返回退出代码


if __name__ == "__main__":
    # 程序入口
    sys.exit(main())  # 调用main()函数
