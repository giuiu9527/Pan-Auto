"""百度登录：调用系统 WebView2（Edge）打开登录页，抓取 Cookie。

不再内置 Chromium（QtWebEngine），改为在**独立子进程**里跑 pywebview + WebView2，
体积大幅缩小。缺少 WebView2 运行时时弹窗引导下载；始终可改用「用 Cookie 添加」兜底。

对外仍暴露 LoginDialog + logged_in 信号，设置页无需改动。
"""
import sys
import json
import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QThread, QUrl
from PySide6.QtGui import QDesktopServices

from app.baidu.webview_login import RESULT_PREFIX, WEBVIEW2_DOWNLOAD, webview2_installed


def _login_command() -> list[str]:
    """启动自身的登录子进程命令（打包版 / 源码版）。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--baidu-login"]
    return [sys.executable, str(Path(sys.argv[0]).resolve()), "--baidu-login"]


class LoginWorker(QThread):
    done = Signal(dict)

    def __init__(self):
        super().__init__()
        self._proc: subprocess.Popen | None = None

    def run(self):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._proc = subprocess.Popen(
                _login_command(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=flags,
            )
            out, _ = self._proc.communicate(timeout=360)
        except subprocess.TimeoutExpired:
            self._kill()
            self.done.emit({"ok": False, "error": "登录超时"})
            return
        except Exception as e:  # noqa: BLE001
            self.done.emit({"ok": False, "error": str(e)})
            return

        result = {"ok": False, "error": "登录进程无返回"}
        for line in (out or "").splitlines():
            if line.startswith(RESULT_PREFIX):
                try:
                    result = json.loads(line[len(RESULT_PREFIX):])
                except json.JSONDecodeError:
                    pass
                break
        self.done.emit(result)

    def stop(self):
        self._kill()

    def _kill(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:  # noqa: BLE001
                pass


class LoginDialog(QDialog):
    logged_in = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登录百度网盘")
        self.setFixedSize(380, 160)
        self._worker: LoginWorker | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        self.hint = QLabel("正在打开登录窗口…\n请在弹出的浏览器窗口中登录百度网盘。")
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.hint)
        lay.addStretch()

        row = QHBoxLayout()
        row.addStretch()
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("Ghost")
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)

    def exec(self):
        if not webview2_installed():
            self._prompt_install()
            return QDialog.Rejected
        self._worker = LoginWorker()
        self._worker.done.connect(self._on_done)
        self._worker.start()
        return super().exec()

    def _on_done(self, result: dict):
        if result.get("ok") and result.get("cookies", {}).get("BDUSS"):
            self.logged_in.emit(result["cookies"])
            self.accept()
            return
        if result.get("code") == "webview2_missing":
            self._prompt_install()
        else:
            QMessageBox.warning(
                self,
                "登录未完成",
                (result.get("error") or "未获取到登录信息") + "\n可改用「用 Cookie 添加」。",
            )
        self.reject()

    def reject(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
        super().reject()

    def _prompt_install(self):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("缺少 WebView2 运行时")
        box.setText(
            "浏览器登录需要系统的 Microsoft Edge WebView2 运行时。\n"
            "点击「下载」安装后重试；也可直接改用「用 Cookie 添加」。"
        )
        dl = box.addButton("下载 WebView2", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is dl:
            QDesktopServices.openUrl(QUrl(WEBVIEW2_DOWNLOAD))
