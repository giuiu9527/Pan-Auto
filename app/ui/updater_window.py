"""独立更新器窗口（update.exe）。

状态：检查中 → 已是最新 / 发现新版本（版本对比 + 更新说明 + 立即更新 / 稍后）
→ 下载进度（可取消）→ 校验中 → 启动安装脚本后自动退出；任何一步出错显示错误，
并给出「修改服务器地址」入口（服务器换 IP 后，已安装的用户靠它继续更新）。

「更新服务器设置」页：服务器地址 + 高级（链接路径）+ 测试连接 / 保存 / 恢复默认，
存到 %APPDATA%\\Pan-Auto\\update_config.json（逻辑都在 app/update_client.py）。
"""
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QApplication,
    QStackedWidget,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QIcon

from app import theme
from app import update_client as uc
from app.ui.icons import make_icon, make_pixmap
from app.ui.widgets import button, label, field_label, hint, muted, StatusPill


class CheckWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, server=None, channel=None):
        super().__init__()
        self.server = server
        self.channel = channel

    def run(self):
        try:
            self.done.emit(uc.check(self.server, self.channel))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class InstallWorker(QThread):
    progress = Signal(int, int)
    stage = Signal(str)
    done = Signal(str)     # bat path
    failed = Signal(str)

    def __init__(self, info: dict):
        super().__init__()
        self.info = info
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            self.stage.emit("downloading")
            zip_path = uc.download_archive(
                self.info["archive"], self.info["archive_url"],
                progress=self.progress.emit, cancelled=lambda: self._cancel,
            )
            self.stage.emit("verifying")
            uc.verify_archive(zip_path, self.info["checksum_url"])
            self.stage.emit("installing")
            bat = uc.install(zip_path)
            self.done.emit(str(bat))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


def _effective_source() -> str:
    """界面/日志里显示当前用的更新源（调试环境变量优先）。"""
    env = os.environ.get("PAN_AUTO_UPDATE_BASE", "").strip()
    if env:
        return f"{env}（调试环境变量 PAN_AUTO_UPDATE_BASE）"
    return uc.current_server()


class UpdaterWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pan-Auto 更新")
        self.setFixedSize(520, 440)
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
        self._test_seq = 0
        self._head_state = None
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

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_main_page())
        self.stack.addWidget(self._build_settings_page())
        root.addWidget(self.stack, 1)

        QTimer.singleShot(100, self.start_check)

    # ---- 页面 ----
    def _build_main_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.versions = QLabel("")
        self.versions.setStyleSheet("font-size:14px; font-weight:600;")
        lay.addWidget(self.versions)

        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setObjectName("Log")
        self.notes.setPlaceholderText("更新说明会显示在这里")
        lay.addWidget(self.notes, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.hide()
        lay.addWidget(self.progress)

        self.status = hint("")
        lay.addWidget(self.status)
        self.server_line = muted("")
        lay.addWidget(self.server_line)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.settings_btn = button("更新服务器设置", "Link", "settings", theme.PRIMARY)
        self.settings_btn.clicked.connect(self._open_settings)
        btns.addWidget(self.settings_btn)
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
        self.fix_btn = button("修改服务器地址", "Primary", "settings")
        self.fix_btn.clicked.connect(self._open_settings)
        self.fix_btn.hide()
        btns.addWidget(self.fix_btn)
        self.update_btn = button("立即更新", "Primary", "download")
        self.update_btn.clicked.connect(self._on_update)
        self.update_btn.hide()
        btns.addWidget(self.update_btn)
        lay.addLayout(btns)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(field_label("服务器地址"))
        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText(uc.DEFAULT_SERVER)
        self.server_edit.returnPressed.connect(self._on_save)
        lay.addWidget(self.server_edit)
        lay.addWidget(hint(f"只填「协议://主机:端口」，例如 {uc.DEFAULT_SERVER}（没写 http:// 会自动补上）。"
                           "更新服务器换了 IP 时改这里。"))

        self.adv_btn = button("高级：链接路径", "Link", "chevron-right", theme.PRIMARY)
        self.adv_btn.clicked.connect(self._toggle_advanced)
        lay.addWidget(self.adv_btn, 0, Qt.AlignLeft)
        self.adv_box = QWidget()
        adv = QVBoxLayout(self.adv_box)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setSpacing(6)
        self.channel_edit = QLineEdit()
        self.channel_edit.setPlaceholderText(uc.DEFAULT_CHANNEL)
        adv.addWidget(self.channel_edit)
        adv.addWidget(hint("本软件更新清单在服务器上的路径，一般不用改。以 / 结尾表示目录（清单是其中的 update.json）。"))
        self.adv_box.hide()
        lay.addWidget(self.adv_box)

        self.test_result = hint("")
        lay.addWidget(self.test_result)
        lay.addStretch(1)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        reset = button("恢复默认", "Ghost")
        reset.clicked.connect(self._on_reset)
        btns.addWidget(reset)
        btns.addStretch()
        back = button("返回", "Ghost")
        back.clicked.connect(self._close_settings)
        btns.addWidget(back)
        self.test_btn = button("测试连接", "Ghost", "activity")
        self.test_btn.clicked.connect(self._on_test)
        btns.addWidget(self.test_btn)
        save = button("保存", "Primary", "check")
        save.clicked.connect(self._on_save)
        btns.addWidget(save)
        lay.addLayout(btns)
        return page

    # ---- 检查 ----
    def start_check(self):
        self.stack.setCurrentIndex(0)
        self.pill.set("检查中", "info")
        self.title.setText("检查更新")
        self.subtitle.setText("正在连接更新服务器…")
        self.versions.setText(f"当前版本 v{uc.local_version()}")
        self.notes.clear()
        self.status.setText("")
        self.server_line.setText(f"更新服务器：{_effective_source()}")
        self.retry_btn.hide()
        self.update_btn.hide()
        self.fix_btn.hide()
        self.settings_btn.show()
        self.progress.hide()
        if not uc.is_configured():
            self._show_error("更新地址配置不正确。")
            return
        w = CheckWorker()
        w.done.connect(self._on_checked)
        w.failed.connect(self._show_error)
        self._track(w)
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
        self.stack.setCurrentIndex(0)
        self.pill.set("出错", "danger")
        self.title.setText("更新失败")
        self.subtitle.setText("请检查网络后重试")
        self.status.setText(f"{msg}\n可能是更新服务器地址已变更，可以点「修改服务器地址」填入新地址。")
        self.server_line.setText(f"更新服务器：{_effective_source()}")
        self.progress.hide()
        self.update_btn.hide()
        self.retry_btn.show()
        self.fix_btn.show()
        self.settings_btn.hide()   # 错误态由右侧「修改服务器地址」承担同一入口
        self.settings_btn.setEnabled(True)
        self.later_btn.setText("关闭")
        self.later_btn.setEnabled(True)
        self._installing = False
        if (uc.app_dir() / "update.log").exists():
            self.log_btn.show()

    # ---- 更新服务器设置 ----
    def _open_settings(self):
        if self._installing:
            return
        cfg = uc.load_config()
        self.server_edit.setText(cfg["server"])
        self.channel_edit.setText(cfg["channel"])
        self.adv_box.setVisible(cfg["custom_channel"])
        self._sync_adv_icon()
        self.test_result.setText("")
        self._head_state = (self.title.text(), self.subtitle.text(), self.pill.text(), self.pill.property("kind"))
        self.title.setText("更新服务器设置")
        self.subtitle.setText("服务器换了地址时，在这里改成新地址")
        self.pill.set("设置", "muted")
        self.stack.setCurrentIndex(1)
        self.server_edit.setFocus()

    def _close_settings(self):
        self._test_seq += 1   # 丢弃还没回来的测试结果
        if self._head_state:
            t, s, p, k = self._head_state
            self.title.setText(t)
            self.subtitle.setText(s)
            self.pill.set(p, k or "muted")
        self.stack.setCurrentIndex(0)

    def _toggle_advanced(self):
        self.adv_box.setVisible(not self.adv_box.isVisible())
        self._sync_adv_icon()

    def _sync_adv_icon(self):
        name = "chevron-down" if self.adv_box.isVisible() else "chevron-right"
        self.adv_btn.setIcon(make_icon(name, theme.PRIMARY, 16))

    def _form_values(self):
        server = uc.normalize_server(self.server_edit.text())
        channel = uc.normalize_channel(self.channel_edit.text() or uc.DEFAULT_CHANNEL)
        return server, channel

    def _on_test(self):
        try:
            server, channel = self._form_values()
        except ValueError as e:
            self.test_result.setText(f"地址不正确：{e}")
            return
        self._test_seq += 1
        seq = self._test_seq
        self.test_btn.setEnabled(False)
        self.test_result.setText(f"正在连接 {server} …")
        w = CheckWorker(server, channel)
        w.done.connect(lambda info, s=seq: self._on_tested(s, True, info))
        w.failed.connect(lambda msg, s=seq: self._on_tested(s, False, msg))
        w.finished.connect(lambda: self.test_btn.setEnabled(True))
        self._track(w)
        w.start()

    def _on_tested(self, seq: int, ok: bool, payload):
        if seq != self._test_seq:
            return
        if ok:
            self.test_result.setText(f"成功：服务器上版本 v{payload['remote']}（本机 v{payload['local']}）。点「保存」后生效。")
        else:
            self.test_result.setText(f"连接失败：{payload}")

    def _on_save(self):
        try:
            server, channel = self._form_values()
            uc.save_config(server, channel)
        except ValueError as e:
            self.test_result.setText(f"没有保存：{e}")
            return
        except OSError as e:
            self.test_result.setText(f"保存失败：{e}")
            return
        self._head_state = None
        self.start_check()

    def _on_reset(self):
        try:
            cfg = uc.reset_config()
        except OSError as e:
            self.test_result.setText(f"恢复默认失败：{e}")
            return
        self.server_edit.setText(cfg["server"])
        self.channel_edit.setText(cfg["channel"])
        self.test_result.setText("已恢复默认地址。")

    # ---- 更新 ----
    def _on_update(self):
        if self._installing:
            return
        self._installing = True
        self.update_btn.hide()
        self.retry_btn.hide()
        self.fix_btn.hide()
        self.settings_btn.setEnabled(False)
        self.later_btn.setText("取消")
        self.pill.set("下载中", "info")
        self.title.setText("正在下载更新")
        self.progress.setValue(0)
        self.progress.show()
        self.status.setText("下载中…")
        w = InstallWorker(self._info)
        w.progress.connect(self._on_progress)
        w.stage.connect(self._on_stage)
        w.done.connect(self._on_installed)
        w.failed.connect(self._show_error)
        self._track(w)
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

    # ---- worker 生命周期：持有引用到 finished 为止（否则 QThread 被 GC → 原生崩溃）----
    def _track(self, w: QThread):
        self._workers.append(w)
        w.finished.connect(lambda x=w: self._drop(x))

    def _drop(self, w):
        if w in self._workers:
            self._workers.remove(w)

    def closeEvent(self, e):
        if self._installing:
            e.ignore()
            return
        super().closeEvent(e)
