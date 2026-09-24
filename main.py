"""Pan-Auto — 网盘自动转存/同步桌面工具

入口：正常启动 GUI；带 --baidu-login 时以子进程模式跑 WebView2 登录；
带 --headless 时只跑后台定时调度器，不建任何窗口（供 IMM 投屏 Next 的
原生「网盘工具」标签驱动 —— 那边直接读写这里的 SQLite 数据库，调度器
在自己的 60 秒扫描周期内就会捡起新增/修改的任务，不需要另外的通信协议）。
"""
import sys


def _run_login() -> int:
    """子进程模式：用系统 WebView2 打开百度登录，抓 Cookie 后退出。"""
    from app.baidu.webview_login import run
    return run()


def _run_api(command: str) -> int:
    """One-shot JSON bridge for the native IMM 投屏 UI (see app/api_bridge.py).

    Reads one JSON object of arguments from stdin, calls the matching
    existing Pan-Auto function, prints exactly one JSON object
    `{"ok": true, "data": ...}` or `{"ok": false, "error": "..."}` to
    stdout, then exits. No Qt event loop needed -- these calls are already
    plain synchronous functions once you strip the QThread wrapper the
    PySide6 UI used to keep its own window responsive.
    """
    import json

    from app.db import init_db
    from app import api_bridge

    # Windows: a redirected/piped stdout still encodes to the console's ANSI
    # codepage (GBK) by default, not UTF-8 -- print() would silently mangle
    # or crash on non-ASCII filenames. Force real UTF-8 bytes on the wire so
    # the C++ side gets valid JSON regardless of the system codepage. Same
    # applies to stdin: read raw bytes and decode as UTF-8 ourselves.
    stdin_bytes = sys.stdin.buffer.read()

    def emit(payload: dict) -> None:
        sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.flush()

    init_db()
    try:
        raw = stdin_bytes.decode("utf-8")
        args = json.loads(raw) if raw.strip() else {}
        data = api_bridge.dispatch(command, args)
        emit({"ok": True, "data": data})
        return 0
    except Exception as e:  # noqa: BLE001
        emit({"ok": False, "error": str(e)})
        return 1


def _run_headless() -> int:
    """无界面模式：只初始化数据库、跑后台调度器，不创建任何窗口。

    用 QSharedMemory 做单实例保护：如果已经有一个 --headless（或未来其它
    调用方）实例在跑，直接退出，避免两个调度器同时轮询同一个数据库。
    """
    from PySide6.QtCore import QCoreApplication, QSharedMemory

    from app.db import init_db
    from app.core.scheduler import Scheduler

    app = QCoreApplication(sys.argv)

    guard = QSharedMemory("PanAuto-HeadlessSingleInstance")
    if not guard.create(1):
        print("Pan-Auto headless already running, exiting.")
        return 0

    init_db()
    scheduler = Scheduler()
    scheduler.start()
    return app.exec()


def main() -> int:
    if "--baidu-login" in sys.argv:
        return _run_login()
    if "--headless" in sys.argv:
        return _run_headless()
    if "--api" in sys.argv:
        idx = sys.argv.index("--api")
        command = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        return _run_api(command)

    # Windows：设置 AppUserModelID 让任务栏显示自定义图标
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PanAuto.App")

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

    # 单实例：已有一份在跑就把它唤到前台，本进程直接退出（否则两个托盘图标、两个调度器）
    from app.single_instance import SingleInstance

    guard = SingleInstance(app)
    if not guard.try_acquire():
        return 0

    # 清掉上次被强杀留下的幽灵托盘图标
    from app.tray_cleanup import refresh_tray_icons

    refresh_tray_icons()

    # 字体：更平滑的渲染
    font = QFont("Microsoft YaHei", 10)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    app.setStyleSheet(APP_QSS)

    init_db()

    window = MainWindow()
    guard.command.connect(window.on_ipc_command)
    window.show()
    QTimer.singleShot(1500, window.check_updates_on_startup)
    try:
        return app.exec()
    finally:
        guard.release()


if __name__ == "__main__":
    raise SystemExit(main())
