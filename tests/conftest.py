import os
import sys
from pathlib import Path

import pytest

# 必须在导入 PyQt5 之前设置无界面平台
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
