"""Pan-Auto — 网盘自动转存/同步桌面工具

入口：正常启动 GUI；带 --baidu-login 时以子进程模式跑 WebView2 登录。
"""
import sys


def _run_login() -> int:
    """子进程模式：用系统 WebView2 打开百度登录，抓 Cookie 后退出。"""
    from app.baidu.webview_login import run
    return run()


def main() -> int:
    if "--baidu-login" in sys.argv:
        return _run_login()

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFont

    from app.config import APP_NAME
    from app.db import init_db
    from app.theme import APP_QSS
    from app.ui.main_window import MainWindow

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    # 字体：更平滑的渲染
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
