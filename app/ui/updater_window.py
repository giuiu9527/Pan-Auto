"""独立更新器窗口（update.exe）。

状态：检查中 → 已是最新 / 发现新版本（版本对比 + 更新说明 + 立即更新 / 稍后）
→ 下载进度（可取消）→ 校验中 → 启动安装脚本后自动退出；任何一步出错显示错误。
"""
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QApplication,
    QStackedWidget,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QIcon

from app import theme
from app import update_client as uc
from app.ui.icons import make_pixmap
from app.ui.widgets import button, label, hint, StatusPill


class CheckWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            self.done.emit(uc.check())
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class InstallWorker(QThread):
    progress = Signal(int, int)
    stage = Signal(str)
    done = Signal(str)     # bat path
    failed = Signal(str)

    def __init__(self, archive: str):
        super().__init__()
        self.archive = archive
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            self.stage.emit("downloading")
            zip_path = uc.download_archive(
                self.archive, progress=self.progress.emit, cancelled=lambda: self._cancel
            )
            self.stage.emit("verifying")
            uc.verify_archive(zip_path, self.archive)
            self.stage.emit("installing")
            bat = uc.install(zip_path)
            self.done.emit(str(bat))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class UpdaterWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pan-Auto 更新")
        self.setFixedSize(480, 400)
        self.setObjectName("Root")
        self.setAttribute(Qt.WA_StyledBackground, True)
        icon = uc.app_dir() / "_internal" / "app" / "ui" / "assets" / "app.ico"
        if not icon.exists():
            icon = Path(__file__).resolve().parent / "assets" / "app.ico"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self._workers = []
        self._info = {}
        self._installing = False
        # `update.exe --auto`：无人值守（发现新版本自动开始更新；已是最新自动关闭），供自测/静默升级用
        self._auto = "--auto" in sys.argv

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        logo = QLabel()
        logo.setFixedSize(40, 40)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(f"background:{theme.PRIMARY}; border-radius:10px;")
        logo.setPixmap(make_pixmap("cloud", "#ffffff", 22, width=2.2))
        head.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = label("检查更新", "PageTitle")
        col.addWidget(self.title)
        self.subtitle = label("正在连接更新服务器…", "PageSubtitle")
        col.addWidget(self.subtitle)
        head.addLayout(col, 1)
        self.pill = StatusPill("检查中", "info")
        head.addWidget(self.pill, 0, Qt.AlignTop)
        root.addLayout(head)

        self.versions = QLabel("")
        self.versions.setStyleSheet("font-size:14px; font-weight:600;")
        root.addWidget(self.versions)

        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setObjectName("Log")
        self.notes.setPlaceholderText("更新说明会显示在这里")
        root.addWidget(self.notes, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.hide()
        root.addWidget(self.progress)

        self.status = hint("")
        root.addWidget(self.status)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.log_btn = button("打开 update.log", "Link")
        self.log_btn.clicked.connect(self._open_log)
        self.log_btn.hide()
        btns.addWidget(self.log_btn)
        btns.addStretch()
        self.later_btn = button("稍后", "Ghost")
        self.later_btn.clicked.connect(self._on_later)
        btns.addWidget(self.later_btn)
        self.retry_btn = button("重新检查", "Ghost", "refresh")
        self.retry_btn.clicked.connect(self.start_check)
        self.retry_btn.hide()
        btns.addWidget(self.retry_btn)
        self.update_btn = button("立即更新", "Primary", "download")
        self.update_btn.clicked.connect(self._on_update)
        self.update_btn.hide()
        btns.addWidget(self.update_btn)
        root.addLayout(btns)

        QTimer.singleShot(100, self.start_check)

    # ---- 检查 ----
    def start_check(self):
        self.pill.set("检查中", "info")
        self.title.setText("检查更新")
        self.subtitle.setText("正在连接更新服务器…")
        self.versions.setText(f"当前版本 v{uc.local_version()}")
        self.notes.clear()
        self.status.setText("")
        self.retry_btn.hide()
        self.update_btn.hide()
        self.progress.hide()
        if not uc.is_configured():
            self._show_error("尚未配置更新地址，请到官方渠道手动下载最新版本。")
            return
        w = CheckWorker()
        w.done.connect(self._on_checked)
        w.failed.connect(self._show_error)
        w.finished.connect(lambda x=w: self._drop(x))
        self._workers.append(w)
        w.start()

    def _on_checked(self, info: dict):
        self._info = info
        if info["has_update"]:
            self.pill.set("发现新版本", "success")
            self.title.setText("发现新版本")
            self.subtitle.setText(f"发布于 {info.get('published_at') or '—'}")
            self.versions.setText(f"v{info['local']}  →  v{info['remote']}")
            self.notes.setPlainText(info.get("notes") or "（本次没有附带更新说明）")
            self.status.setText("点「立即更新」会下载并校验更新包，然后自动关闭 Pan-Auto、覆盖安装并重新启动。")
            self.update_btn.show()
            self.later_btn.setText("稍后")
            if self._auto:
                QTimer.singleShot(300, self._on_update)
        else:
            self.pill.set("已是最新", "success")
            self.title.setText("已是最新版本")
            self.subtitle.setText("无需更新")
            self.versions.setText(f"当前版本 v{info['local']}（服务器最新 v{info['remote']}）")
            self.notes.setPlainText(info.get("notes") or "")
            self.later_btn.setText("关闭")
            self.retry_btn.show()
            if self._auto:
                QTimer.singleShot(1500, QApplication.quit)

    def _show_error(self, msg: str):
        self.pill.set("出错", "danger")
        self.title.setText("更新失败")
        self.subtitle.setText("请检查网络后重试")
        self.status.setText(msg)
        self.progress.hide()
        self.update_btn.hide()
        self.retry_btn.show()
        self.later_btn.setText("关闭")
        self.later_btn.setEnabled(True)
        self._installing = False
        if (uc.app_dir() / "update.log").exists():
            self.log_btn.show()

    # ---- 更新 ----
    def _on_update(self):
        if self._installing:
            return
        self._installing = True
        self.update_btn.hide()
        self.retry_btn.hide()
        self.later_btn.setText("取消")
        self.pill.set("下载中", "info")
        self.title.setText("正在下载更新")
        self.progress.setValue(0)
        self.progress.show()
        self.status.setText("下载中…")
        w = InstallWorker(self._info["archive"])
        w.progress.connect(self._on_progress)
        w.stage.connect(self._on_stage)
        w.done.connect(self._on_installed)
        w.failed.connect(self._show_error)
        w.finished.connect(lambda x=w: self._drop(x))
        self._workers.append(w)
        self._install_worker = w
        w.start()

    def _on_progress(self, done: int, total: int):
        mb = done / 1024 / 1024
        if total > 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(done * 100 / total))
            self.status.setText(f"下载中… {mb:.1f} / {total / 1024 / 1024:.1f} MB")
        else:
            self.progress.setRange(0, 0)
            self.status.setText(f"下载中… {mb:.1f} MB")

    def _on_stage(self, stage: str):
        if stage == "verifying":
            self.pill.set("校验中", "info")
            self.title.setText("正在校验更新包")
            self.status.setText("正在计算 SHA-256 并与服务器比对…")
            self.later_btn.setEnabled(False)
        elif stage == "installing":
            self.pill.set("安装中", "info")
            self.title.setText("正在安装")
            self.status.setText("已关闭 Pan-Auto，安装脚本会覆盖文件并自动重新启动。")

    def _on_installed(self, bat: str):
        self.status.setText("安装脚本已启动，本窗口即将关闭。")
        QTimer.singleShot(800, QApplication.quit)

    def _on_later(self):
        if self._installing:
            w = getattr(self, "_install_worker", None)
            if w is not None:
                w.cancel()
            self.later_btn.setEnabled(False)
            self.status.setText("正在取消…")
            return
        QApplication.quit()

    def _open_log(self):
        p = uc.app_dir() / "update.log"
        if p.exists() and sys.platform == "win32":
            os.startfile(str(p))  # noqa: S606

    def _drop(self, w):
        if w in self._workers:
            self._workers.remove(w)

    def closeEvent(self, e):
        if self._installing:
            e.ignore()
            return
        super().closeEvent(e)
