"""Pan-Auto — 百度网盘自动转存桌面工具

入口：启动 Qt 应用、初始化数据库、打开主窗口。
"""
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

# QtWebEngine 需要在创建 QApplication 前共享 OpenGL 上下文
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
import PySide6.QtWebEngineWidgets  # noqa: F401  确保 WebEngine 初始化

from app.config import APP_NAME
from app.db import init_db
from app.theme import APP_QSS
from app.ui.main_window import MainWindow


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    # 字体：用更平滑的渲染（关闭 hinting + 抗锯齿），贴近 Chromium 观感
    font = QFont("Microsoft YaHei", 10)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    app.setStyleSheet(APP_QSS)

    init_db()

    window = MainWindow()
    window.show()
    QTimer.singleShot(1500, window.check_updates_on_startup)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
