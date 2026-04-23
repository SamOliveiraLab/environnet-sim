"""EnvironNets Desktop Application.

Launch with:
    python -m environnets
    or:
    environnets  (after pip install -e .)
"""

import os
import sys
import logging

import PyQt6
os.environ.setdefault(
    "QT_PLUGIN_PATH",
    os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "plugins"),
)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

Qt.HighDpiScaleFactorRoundingPolicy  # ensure enum loaded
QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)

from environnets.core.config import get, get_section
from environnets.ui.main_window import MainWindow

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(get("app", "name", "EnvironNets"))
    app.setOrganizationName("OliveiraLab")

    ui_cfg = get_section("ui")
    window = MainWindow()
    window.resize(
        ui_cfg.get("window_width", 1280),
        ui_cfg.get("window_height", 800),
    )
    window.setMinimumSize(
        ui_cfg.get("min_width", 860),
        ui_cfg.get("min_height", 580),
    )
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
