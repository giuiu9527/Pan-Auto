"""单实例保护 + 进程间小命令（Windows 命名管道，基于 QLocalServer）。

- GUI 启动时 `SingleInstance.try_acquire()`：已有实例在跑就把「show」发给它然后退出，
  不再第二份窗口 / 第二个托盘图标 / 第二个调度器。
- 更新器在覆盖文件前先发「quit」让主程序**正常退出**（自己收掉托盘图标），
  等不到再 taskkill（见 update_client.kill_main_program）。
"""
from __future__ import annotations

import getpass
import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = f"PanAuto-GUI-{getpass.getuser() or 'user'}"
# Windows 上 QLocalServer 的实际管道名，供不带 Qt 的进程直接 open() 写命令
PIPE_PATH = "\\\\.\\pipe\\" + SERVER_NAME


def send_command(cmd: str, timeout_ms: int = 1500) -> bool:
    """给已运行的实例发一条命令（show / quit）。没有实例在跑返回 False。"""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write((cmd.strip() + "\n").encode("utf-8"))
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


class SingleInstance(QObject):
    """持有本进程的 QLocalServer；收到命令后发 `command(str)` 信号。"""

    command = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server: QLocalServer | None = None

    def try_acquire(self) -> bool:
        """成为主实例返回 True；已有实例则通知它显示窗口并返回 False。"""
        if send_command("show"):
            return False
        # 上一次异常退出可能留下残留的管道名，先清一次再监听
        QLocalServer.removeServer(SERVER_NAME)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        if not self._server.listen(SERVER_NAME):
            # 极少数情况：监听失败就放弃单实例保护，程序照常运行
            self._server = None
        return True

    def _on_connection(self):
        assert self._server is not None
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        sock.readyRead.connect(lambda s=sock: self._read(s))
        sock.disconnected.connect(sock.deleteLater)

    def _read(self, sock: QLocalSocket):
        data = bytes(sock.readAll()).decode("utf-8", "ignore")
        for line in data.splitlines():
            cmd = line.strip().lower()
            if cmd:
                self.command.emit(cmd)

    def release(self):
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(SERVER_NAME)
            self._server = None


def graceful_quit_running_instance_raw(timeout: float = 1.0) -> bool:
    """不依赖 Qt 事件循环：直接写命名管道发「quit」（供 update.exe 用）。"""
    if sys.platform != "win32":
        return False
    try:
        with open(PIPE_PATH, "r+b", buffering=0) as f:
            f.write(b"quit\n")
        return True
    except OSError:
        return False
