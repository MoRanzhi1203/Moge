##############################
# ui/theme.py - 浅色/深色主题
##############################

DARK_QSS = """
QMainWindow, QWidget { background-color: #20232a; color: #e8e8e8; }
QToolBar { background: #262a33; border: 0; spacing: 6px; padding: 4px; }
QToolBar QToolButton { padding: 5px 8px; border-radius: 4px; }
QToolBar QToolButton:hover { background: #333846; }
QToolBar QToolButton:checked { background: #2f6feb; color: #ffffff; font-weight: bold; border: 1px solid #6d9bff; }
QGroupBox { border: 1px solid #3a3f4b; border-radius: 6px; margin-top: 10px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9fb2c8; }
QPushButton { background: #2f6feb; color: white; border: 0; padding: 6px 10px; border-radius: 4px; }
QPushButton:hover { background: #3f7ffb; }
QPushButton:disabled { background: #3a3f4b; color: #8a8a8a; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    background: #2a2e37; border: 1px solid #3a3f4b; padding: 4px; border-radius: 4px;
}
QListWidget, QTextBrowser, QScrollArea { background: #262a33; border: 1px solid #3a3f4b; }
QSplitter::handle { background: #3a3f4b; }
QStatusBar { background: #262a33; }
QTabWidget::pane { border: 1px solid #3a3f4b; }
QTabBar::tab { background: #2a2e37; padding: 6px 10px; }
QTabBar::tab:selected { background: #2f6feb; }
QProgressBar { border: 1px solid #3a3f4b; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: #2f6feb; }
"""

LIGHT_QSS = """
QMainWindow, QWidget { background-color: #f4f6f9; color: #20232a; }
QToolBar { background: #ffffff; border: 0; spacing: 6px; padding: 4px; }
QToolBar QToolButton { padding: 5px 8px; border-radius: 4px; }
QToolBar QToolButton:hover { background: #e6eefc; }
QToolBar QToolButton:checked { background: #2f6feb; color: #ffffff; font-weight: bold; border: 1px solid #1d4fbf; }
QGroupBox { border: 1px solid #d5dbe5; border-radius: 6px; margin-top: 10px; padding-top: 8px; background: #ffffff; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #39557a; }
QPushButton { background: #2f6feb; color: white; border: 0; padding: 6px 10px; border-radius: 4px; }
QPushButton:hover { background: #3f7ffb; }
QPushButton:disabled { background: #c6ccd6; color: #6b7280; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    background: #ffffff; border: 1px solid #c9d1dd; padding: 4px; border-radius: 4px;
}
QListWidget, QTextBrowser, QScrollArea { background: #ffffff; border: 1px solid #d5dbe5; }
QSplitter::handle { background: #d5dbe5; }
QStatusBar { background: #ffffff; }
QTabWidget::pane { border: 1px solid #d5dbe5; }
QTabBar::tab { background: #e8edf5; padding: 6px 10px; }
QTabBar::tab:selected { background: #2f6feb; color: white; }
QProgressBar { border: 1px solid #c9d1dd; border-radius: 4px; text-align: center; }
QProgressBar::chunk { background: #2f6feb; }
"""

THEMES = {"dark": DARK_QSS, "light": LIGHT_QSS}


def apply_theme(app, name: str):
    app.setStyleSheet(THEMES.get(name, DARK_QSS))
