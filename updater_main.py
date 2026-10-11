"""Pan-Auto 独立更新器入口 → 打包成 update.exe，放在主程序旁边。

主程序运行时不能覆盖自己，所以检查 / 下载 / 校验 / 安装都在这个独立小程序里做
（协议见 app/update_client.py，界面见 app/ui/updater_window.py）。

`update.exe --server http://x.x.x.x:5244`：先把服务器地址写进 update_config.json，再正常检查更新
（换服务器 IP 后批量改用）。
"""
import sys


def _cli_server(argv: list[str]) -> str | None:
    for i, a in enumerate(argv):
        if a == "--server" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--server="):
            return a.split("=", 1)[1]
    return None


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtGui import QFont

    from app import update_client as uc
    from app.theme import APP_QSS
    from app.ui.updater_window import UpdaterWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Pan-Auto Updater")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(APP_QSS)

    server = _cli_server(sys.argv)
    if server is not None:
        try:
            uc.save_config(server, uc.load_config()["channel"])
        except (ValueError, OSError) as e:
            QMessageBox.warning(None, "Pan-Auto 更新", f"--server 参数无效，未保存：{e}")

    win = UpdaterWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
