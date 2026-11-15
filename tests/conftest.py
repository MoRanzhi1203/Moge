import os
import sys
import tempfile
from pathlib import Path

import pytest
from PyQt5.QtCore import QSettings

# 隔离测试使用的 QSettings，避免污染用户界面状态
_SETTINGS_DIR = tempfile.mkdtemp(prefix="moge-settings-")
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, _SETTINGS_DIR)

# 必须在导入 PyQt5 之前设置无界面平台
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 测试使用独立的资源缓存，避免读取或污染用户本地资源库
os.environ.setdefault("MOGE_RESOURCE_DIR", tempfile.mkdtemp(prefix="moge-resources-"))

# 兼容未安装为包时直接从仓库根目录运行 pytest
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT.parent))


@pytest.fixture(scope="session")
def qapp():
    """ 提供唯一的 QApplication 实例，供涉及 Qt 的测试使用 """
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
