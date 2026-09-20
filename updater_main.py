"""Pan-Auto 独立更新器入口 → 打包成 update.exe，放在主程序旁边。

主程序运行时不能覆盖自己，所以检查 / 下载 / 校验 / 安装都在这个独立小程序里做
（协议见 app/update_client.py，界面见 app/ui/updater_window.py）。
"""
import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont

    from app.theme import APP_QSS
    from app.ui.updater_window import UpdaterWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Pan-Auto Updater")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(APP_QSS)
    win = UpdaterWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
