"""主窗口：无边框 + 蓝色标题栏 + 左侧导航（矢量图标）+ 内容区 + 状态栏。"""
import sys

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QButtonGroup,
    QFrame,
    QMessageBox,
    QProgressDialog,
    QSystemTrayIcon,
    QMenu,
    QCheckBox,
)
from PySide6.QtCore import Qt, QPoint, QSize, QEvent, QThread, Signal
from PySide6.QtGui import QMouseEvent, QIcon, QAction

from app.config import APP_TITLE, APP_VERSION

import os as _os
import sys as _sys
if getattr(_sys, 'frozen', False):
    # PyInstaller onedir：资源在 _internal 下（_MEIPASS），不是 exe 同级目录
    _base = getattr(_sys, '_MEIPASS', _os.path.dirname(_sys.executable))
    _ICON_PATH = _os.path.join(_base, 'app', 'ui', 'assets', 'app.ico')
else:
    _ICON_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'assets', 'app.ico')
from app import db
from app import updater
from app.netdisk import provider_label
from app.core.scheduler import Scheduler
from app.ui.icons import make_icon, make_pixmap
from app.ui.pages.home import HomePage
from app.ui.pages.auto_sync import AutoSyncPage
from app.ui.pages.batch_rename import BatchRenamePage
from app.ui.pages.ad_insert import AdInsertPage
from app.ui.pages.ad_clean import AdCleanPage
from app.ui.pages.settings import SettingsPage
from app.ui.pages.logs import LogsPage
from app.ui.pages.friend_message import FriendMessagePage
from app.ui.pages.placeholder import PlaceholderPage

PRIMARY = "#2f6bff"
PRIMARY_DARK = "#1f54e0"
GRAY = "#5b6473"

NAV = [
    ("home", "主页", "home"),
    ("auto", "自动同步", "sync"),
    ("rename", "批量重命名", "edit"),
    ("adclean", "广告清理", "trash"),
    ("ad", "广告插入", "target"),
    ("friends", "好友消息", "users"),
    ("logs", "转存记录", "logs"),
    ("settings", "设置", "settings"),
]


class TitleBar(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window_ref = window
        self.setObjectName("TitleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            "QWidget#TitleBar {"
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {PRIMARY}, stop:1 {PRIMARY_DARK});"
            "}"
            "QLabel#TitleText { color: white; font-size: 13.5px; font-weight: 600; }"
            "QPushButton#WinBtn, QPushButton#WinBtnClose {"
            "background: transparent; color: rgba(255,255,255,0.92); border: none;"
            "font-size: 14px; min-width: 44px; min-height: 36px; font-weight: 600;"
            "}"
            "QPushButton#WinBtn:hover { background: rgba(255,255,255,0.20); color: white; }"
            "QPushButton#WinBtnClose:hover { background: #e5484d; color: white; }"
        )
        self.setFixedHeight(36)
        self._drag_pos: QPoint | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 0, 0)
        lay.setSpacing(7)
        logo = QLabel()
        logo.setPixmap(make_pixmap("cloud", "#ffffff", 17))
        lay.addWidget(logo)
        title = QLabel(APP_TITLE)
        title.setObjectName("TitleText")
        lay.addWidget(title)
        lay.addStretch()

        self.min_btn = QPushButton("−")
        self.min_btn.setObjectName("WinBtn")
        self.min_btn.setToolTip("最小化")
        self.min_btn.clicked.connect(window.showMinimized)
        self.max_btn = QPushButton("□")
        self.max_btn.setObjectName("WinBtn")
        self.max_btn.setToolTip("最大化")
        self.max_btn.clicked.connect(self._toggle_max_restore)
        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("WinBtnClose")
        self.close_btn.setToolTip("关闭")
        self.close_btn.clicked.connect(window.close)
        lay.addWidget(self.min_btn)
        lay.addWidget(self.max_btn)
        lay.addWidget(self.close_btn)

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._drag_pos = (
                e.globalPosition().toPoint()
                - self.window_ref.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._drag_pos and e.buttons() & Qt.LeftButton:
            self.window_ref.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e: QMouseEvent):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._toggle_max_restore()

    def _toggle_max_restore(self):
        if self.window_ref.isMaximized():
            self.window_ref.showNormal()
        else:
            self.window_ref.showMaximized()
        self.refresh_state()

    def refresh_state(self):
        maximized = self.window_ref.isMaximized()
        self.max_btn.setText("❐" if maximized else "□")
        self.max_btn.setToolTip("还原" if maximized else "最大化")


class NavButton(QPushButton):
    def __init__(self, icon_name: str, text: str):
        super().__init__("  " + text)
        self.icon_name = icon_name
        self.setObjectName("NavItem")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(19, 19))
        self._update_icon(False)
        self.toggled.connect(self._update_icon)

    def _update_icon(self, checked: bool):
        self.setIcon(make_icon(self.icon_name, PRIMARY if checked else GRAY, 19))


class AccountChip(QFrame):
    def __init__(self, on_click):
        super().__init__()
        self.setObjectName("AccountChip")
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = on_click
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 7, 9, 7)
        lay.setSpacing(8)
        self.avatar = QLabel()
        self.avatar.setPixmap(make_pixmap("user", "#9aa4b5", 18))
        lay.addWidget(self.avatar)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.name = QLabel("未登录")
        self.name.setStyleSheet("font-weight:600; font-size:13px;")
        self.sub = QLabel("点击添加账号")
        self.sub.setObjectName("Muted")
        self.sub.setStyleSheet("font-size:11.5px;")
        col.addWidget(self.name)
        col.addWidget(self.sub)
        lay.addLayout(col)
        lay.addStretch()
        self.count = QLabel("")
        self.count.setObjectName("MemberBadge")
        lay.addWidget(self.count)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._on_click()

    def refresh(self):
        acc = db.get_active_account()
        n = db.account_count()
        if acc and acc.get("username"):
            self.name.setText(acc["username"])
            self.sub.setText(f"{provider_label(acc.get('provider'))} · 点击管理")
            self.avatar.setPixmap(make_pixmap("user", "#2f6bff", 18))
        else:
            self.name.setText("未登录")
            self.sub.setText("点击添加账号")
            self.avatar.setPixmap(make_pixmap("user", "#9aa4b5", 18))
        self.count.setText(f"{n} 个账号" if n else "")
        self.count.setVisible(n > 1)


class Sidebar(QWidget):
    def __init__(self, on_nav):
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(188)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(16, 12, 14, 10)
        brand_row.setSpacing(7)
        logo = QLabel()
        logo.setPixmap(make_pixmap("cloud", PRIMARY, 22))
        brand_row.addWidget(logo)
        brand = QLabel("Pan-Auto")
        brand.setObjectName("Brand")
        brand_row.addWidget(brand)
        brand_row.addStretch()
        lay.addLayout(brand_row)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for key, text, icon in NAV:
            btn = NavButton(icon, text)
            btn.clicked.connect(lambda _=False, k=key: on_nav(k))
            self.group.addButton(btn)
            self.buttons[key] = btn
            lay.addWidget(btn)

        lay.addStretch()

        box = QWidget()
        box.setObjectName("AccountBox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(10, 9, 10, 10)
        self.chip = AccountChip(lambda: on_nav("settings"))
        bl.addWidget(self.chip)
        lay.addWidget(box)

    def refresh_account(self):
        self.chip.refresh()


class UpdateCheckWorker(QThread):
    done = Signal(dict)

    def run(self):
        self.done.emit(updater.check_for_update())


class UpdateApplyWorker(QThread):
    done = Signal(dict)
    progress = Signal(int, int)  # downloaded, total

    def run(self):
        # Release 更新时带进度回调
        if getattr(_sys, 'frozen', False) or not updater.is_git_repo():
            state = updater.check_release_update()
            if not state.get('ok') or not state.get('has_update'):
                self.done.emit(updater.apply_update())
                return
            if _sys.platform != 'win32':
                self.done.emit({'ok': False, 'code': 'unsupported_platform', 'message': '打包版自动替换目前仅支持 Windows'})
                return
            from pathlib import Path
            ok, zip_path_or_msg = updater.download_release_asset(state, progress_cb=lambda d, t: self.progress.emit(d, t))
            if not ok:
                self.done.emit({**state, 'ok': False, 'code': 'download_failed', 'message': zip_path_or_msg})
                return
            ok, msg = updater.launch_windows_replacer(Path(zip_path_or_msg))
            if not ok:
                self.done.emit({**state, 'ok': False, 'code': 'replace_failed', 'message': msg})
                return
            self.done.emit({**state, 'updated': True, 'restart_managed': True, 'downloaded_path': str(zip_path_or_msg), 'message': '更新包已下载，关闭软件后将自动替换并重启'})
        else:
            self.done.emit(updater.apply_update())


class StatusBar(QWidget):
    def __init__(self, on_check_update):
        super().__init__()
        self.setObjectName("StatusBar")
        self.setFixedHeight(30)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 12, 0)
        info = QLabel("个人使用 · 请遵守网盘服务条款，注意转存节流")
        info.setObjectName("Muted")
        lay.addWidget(info)
        lay.addStretch()
        update = QPushButton("检查更新")
        update.setObjectName("StatusAction")
        update.setCursor(Qt.PointingHandCursor)
        update.clicked.connect(on_check_update)
        lay.addWidget(update)
        ver = QLabel(f"版本 {APP_VERSION}")
        ver.setObjectName("Badge")
        lay.addWidget(ver)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Root")
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.resize(1120, 740)
        self.setMinimumSize(940, 620)
        self._app_icon = QIcon(_ICON_PATH) if _os.path.exists(_ICON_PATH) else QIcon()
        if not self._app_icon.isNull():
            self.setWindowIcon(self._app_icon)
            _app = QApplication.instance()
            if _app:
                _app.setWindowIcon(self._app_icon)  # 任务栏/托盘统一用自定义图标
        self._update_workers = []
        self._force_update_required = False
        self._really_quit = False
        self._tray_notified = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.titlebar = TitleBar(self)
        outer.addWidget(self.titlebar)

        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(0)
        outer.addLayout(mid, 1)

        self.sidebar = Sidebar(self.navigate)
        mid.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        mid.addWidget(self.stack, 1)

        outer.addWidget(StatusBar(self.check_for_updates_manual))

        self.home = HomePage()
        self.home.navigate.connect(self.navigate)
        self.auto = AutoSyncPage()
        self.rename = BatchRenamePage()
        self.adclean = AdCleanPage()
        self.ad_insert = AdInsertPage()
        self.friends = FriendMessagePage()
        self.logs = LogsPage()
        self.settings = SettingsPage()
        self.settings.account_changed.connect(self.on_account_changed)

        self.pages = {
            "home": self.home,
            "auto": self.auto,
            "rename": self.rename,
            "adclean": self.adclean,
            "ad": self.ad_insert,
            "friends": self.friends,
            "logs": self.logs,
            "settings": self.settings,
        }
        for w in self.pages.values():
            self.stack.addWidget(w)

        self.navigate("home")
        self.sidebar.refresh_account()

        # 后台定时调度器：自动跑到期的同步任务
        self.scheduler = Scheduler()
        self.scheduler.task_ran.connect(self._on_scheduled_task_ran)
        self.scheduler.swept.connect(self._on_scheduler_swept)
        self.scheduler.start()

        self._setup_tray()

    # ---- 系统托盘 ----
    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        if not self._app_icon.isNull():
            self.tray.setIcon(self._app_icon)
        self.tray.setToolTip("Pan-Auto · 网盘自动转存")
        menu = QMenu()
        act_show = QAction("显示主界面", self)
        act_show.triggered.connect(self._show_window)
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self._quit_from_tray)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._show_window()

    def _show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self):
        self._really_quit = True
        self.close()

    def _notify_tray_once(self):
        if self._tray_notified or not hasattr(self, "tray"):
            return
        self._tray_notified = True
        try:
            self.tray.showMessage(
                "Pan-Auto",
                "已最小化到托盘，后台继续定时同步。双击托盘图标可恢复。",
                QSystemTrayIcon.Information,
                3000,
            )
        except Exception:  # noqa: BLE001
            pass

    def _shutdown(self):
        try:
            if hasattr(self, "scheduler"):
                self.scheduler.stop()
                self.scheduler.wait(3000)
        except Exception:  # noqa: BLE001
            pass
        if hasattr(self, "tray"):
            self.tray.hide()

    def _on_scheduled_task_ran(self, task_id: int, result: dict):
        # 定时任务跑完，刷新任务列表与日志（若正显示）
        if self.stack.currentWidget() is self.auto:
            self.auto.reload_tasks()
        if self.stack.currentWidget() is self.logs:
            self.logs.reload()

    def _on_scheduler_swept(self):
        if self.stack.currentWidget() is self.logs:
            self.logs.reload()

    def closeEvent(self, e):
        # 从托盘「退出」或已确定退出 → 真正关闭
        if self._really_quit:
            self._shutdown()
            super().closeEvent(e)
            return

        action = db.get_setting("close_action", "ask")  # ask / minimize / quit
        if action == "quit":
            self._really_quit = True
            self._shutdown()
            super().closeEvent(e)
            return
        if action == "minimize":
            e.ignore()
            self.hide()
            self._notify_tray_once()
            return

        # ask：弹窗询问 + 记住选项
        box = QMessageBox(self)
        box.setWindowTitle("关闭 Pan-Auto")
        box.setIcon(QMessageBox.Question)
        box.setText("要最小化到托盘，还是退出程序？")
        box.setInformativeText("最小化后程序在后台继续定时同步。")
        min_btn = box.addButton("最小化到托盘", QMessageBox.AcceptRole)
        quit_btn = box.addButton("退出程序", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        remember = QCheckBox("记住我的选择（可在「设置」里更改）")
        box.setCheckBox(remember)
        box.setDefaultButton(min_btn)
        box.exec()
        clicked = box.clickedButton()

        if clicked is min_btn:
            if remember.isChecked():
                db.set_setting("close_action", "minimize")
            e.ignore()
            self.hide()
            self._notify_tray_once()
        elif clicked is quit_btn:
            if remember.isChecked():
                db.set_setting("close_action", "quit")
            self._really_quit = True
            self._shutdown()
            super().closeEvent(e)
        else:
            e.ignore()  # 取消关闭

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange and hasattr(self, "titlebar"):
            self.titlebar.refresh_state()

    def check_updates_on_startup(self):
        self._check_for_updates(manual=False)

    def check_for_updates_manual(self):
        self._check_for_updates(manual=True)

    def _check_for_updates(self, manual: bool):
        if any(isinstance(w, UpdateCheckWorker) for w in self._update_workers):
            if manual:
                QMessageBox.information(self, "更新检查", "正在检查更新，请稍等。")
            return
        worker = UpdateCheckWorker()
        worker.done.connect(lambda result, m=manual: self._on_update_checked(result, m))
        worker.finished.connect(lambda w=worker: self._update_workers.remove(w))
        self._update_workers.append(worker)
        worker.start()

    def _on_update_checked(self, result: dict, manual: bool):
        if not result.get("ok"):
            if manual and result.get("code") not in {"not_git", "disabled"}:
                QMessageBox.warning(self, "更新检查失败", result.get("message", "未知错误"))
            elif manual:
                QMessageBox.information(self, "更新检查", result.get("message", "当前版本不可在线更新"))
            return

        if not result.get("has_update"):
            if manual:
                if result.get("kind") == "release":
                    QMessageBox.information(
                        self,
                        "更新检查",
                        f"已是最新版本。\n当前版本：{result.get('current_version', '-')}\n最新版本：{result.get('latest_version', '-')}",
                    )
                    return
                QMessageBox.information(
                    self,
                    "更新检查",
                    f"已是最新版本。\n当前分支：{result.get('branch', '-')}\n当前提交：{result.get('local_sha', '-')}",
                )
            return

        if result.get("force_update"):
            self._force_update_required = True
            msg = (
                "当前版本已低于最低支持版本，必须更新后才能继续使用。\n\n"
                f"当前版本：{result.get('current_version', '-')}\n"
                f"最低支持：{result.get('force_below', '-')}\n"
                f"最新版本：{result.get('latest_version', '-')}\n\n"
                "点击确定开始更新。"
            )
            QMessageBox.warning(self, "必须更新", msg)
            self._apply_update()
            return

        if result.get("kind") == "release":
            size = result.get("asset_size", 0) or 0
            mb = size / 1024 / 1024 if size else 0
            msg = (
                "发现新的运行包。\n"
                f"当前版本：{result.get('current_version', '-')}\n"
                f"最新版本：{result.get('latest_version', '-')}\n"
                f"安装包：{result.get('asset_name', '-')}"
            )
            if mb:
                msg += f"\n大小：{mb:.1f} MB"
            msg += "\n\n现在下载并更新吗？"
            if QMessageBox.question(self, "发现新版本", msg) == QMessageBox.Yes:
                self._apply_update()
            return

        msg = (
            f"发现 {result.get('behind', 0)} 个远程更新。\n"
            f"分支：{result.get('branch', '-')}\n"
            f"本地：{result.get('local_sha', '-')}\n"
            f"远程：{result.get('remote_sha', '-')}\n\n"
            "现在更新并重启软件吗？"
        )
        if QMessageBox.question(self, "发现新版本", msg) == QMessageBox.Yes:
            self._apply_update()

    def _apply_update(self):
        if any(isinstance(w, UpdateApplyWorker) for w in self._update_workers):
            return

        # 创建进度对话框
        self._progress_dlg = QProgressDialog("正在下载更新...", "取消", 0, 100, self)
        self._progress_dlg.setWindowTitle("下载更新")
        self._progress_dlg.setWindowModality(Qt.WindowModal)
        self._progress_dlg.setMinimumWidth(380)
        self._progress_dlg.setAutoClose(False)
        self._progress_dlg.setAutoReset(False)
        self._progress_dlg.setValue(0)
        self._progress_dlg.show()

        worker = UpdateApplyWorker()
        worker.progress.connect(self._on_download_progress)
        worker.done.connect(self._on_update_applied)
        worker.finished.connect(lambda w=worker: self._update_workers.remove(w))
        self._update_workers.append(worker)
        self._progress_dlg.canceled.connect(lambda: worker.terminate())
        worker.start()

    def _on_download_progress(self, downloaded: int, total: int):
        dlg = getattr(self, '_progress_dlg', None)
        if not dlg:
            return
        if total > 0:
            pct = int(downloaded * 100 / total)
            dlg.setValue(pct)
            mb_down = downloaded / 1024 / 1024
            mb_total = total / 1024 / 1024
            dlg.setLabelText(f"正在下载更新... {mb_down:.1f} / {mb_total:.1f} MB")
        else:
            mb_down = downloaded / 1024 / 1024
            dlg.setLabelText(f"正在下载更新... {mb_down:.1f} MB")

    def _on_update_applied(self, result: dict):
        dlg = getattr(self, '_progress_dlg', None)
        if dlg:
            dlg.close()
            self._progress_dlg = None

        if not result.get("ok"):
            QMessageBox.warning(self, "更新失败", result.get("message", "未知错误"))
            if self._force_update_required:
                QApplication.quit()
            return
        if not result.get("updated"):
            QMessageBox.information(self, "更新检查", result.get("message", "已是最新版本"))
            return
        if result.get("restart_managed"):
            QMessageBox.information(
                self,
                "更新已准备好",
                "更新包已下载。点击确定后软件会关闭，外部更新器会替换文件并自动重启。",
            )
            QApplication.quit()
            return
        if (
            QMessageBox.information(
                self,
                "更新完成",
                "更新已完成，软件将重启以加载新版本。",
            )
            == QMessageBox.Ok
        ):
            ok, msg = updater.restart_app()
            if ok:
                QApplication.quit()
            else:
                QMessageBox.warning(self, "重启失败", msg)

    def navigate(self, key: str):
        if key not in self.pages:
            return
        self.stack.setCurrentWidget(self.pages[key])
        if key in self.sidebar.buttons:
            self.sidebar.buttons[key].setChecked(True)
        if key == "logs":
            self.logs.reload()
        if key == "auto":
            self.auto.on_shown()
        if key == "rename":
            self.rename.on_shown()
        if key == "adclean":
            self.adclean.on_shown()
        if key == "ad":
            self.ad_insert.on_shown()
        if key == "friends":
            self.friends.on_shown()
        if key == "settings":
            self.settings.refresh_accounts()

    def on_account_changed(self):
        self.sidebar.refresh_account()
        self.auto.refresh_accounts()
        self.rename.refresh_accounts()
        self.adclean.refresh_accounts()
        self.ad_insert.refresh_accounts()
        self.friends.refresh_accounts()

    # ---- 无边框窗口的原生边缘缩放（Windows）----
    RESIZE_MARGIN = 7

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_resize_enabled", False):
            self._resize_enabled = True
            self._enable_win_resize()

    def _enable_win_resize(self):
        """把可缩放边框样式加回无边框窗口（标准 Windows 方案）。"""
        if sys.platform != "win32":
            return
        import ctypes

        hwnd = int(self.winId())
        user32 = ctypes.windll.user32
        GWL_STYLE = -16
        WS_THICKFRAME = 0x00040000
        WS_CAPTION = 0x00C00000
        WS_MAXIMIZEBOX = 0x00010000
        WS_MINIMIZEBOX = 0x00020000
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        user32.SetWindowLongW(
            hwnd,
            GWL_STYLE,
            (style & ~WS_CAPTION) | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX,
        )
        # 触发边框重算
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32" and eventType == b"windows_generic_MSG":
            import ctypes
            from ctypes import wintypes

            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0083:  # WM_NCCALCSIZE：去掉非客户区，内容铺满
                if msg.wParam:
                    return True, 0
            elif msg.message == 0x0084:  # WM_NCHITTEST：边缘返回缩放码
                lp = msg.lParam & 0xFFFFFFFF
                x = lp & 0xFFFF
                y = (lp >> 16) & 0xFFFF
                if x >= 0x8000:
                    x -= 0x10000
                if y >= 0x8000:
                    y -= 0x10000
                # 用物理像素的窗口矩形做命中判断，避免 DPI 缩放错位
                rect = wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(msg.hWnd, ctypes.byref(rect))
                m = max(5, int(self.RESIZE_MARGIN * self.devicePixelRatioF()))
                left = 0 <= (x - rect.left) < m
                right = 0 <= (rect.right - x) < m
                top = 0 <= (y - rect.top) < m
                bottom = 0 <= (rect.bottom - y) < m
                if top and left:
                    return True, 13
                if top and right:
                    return True, 14
                if bottom and left:
                    return True, 16
                if bottom and right:
                    return True, 17
                if left:
                    return True, 10
                if right:
                    return True, 11
                if top:
                    return True, 12
                if bottom:
                    return True, 15
                return True, 1  # HTCLIENT：其余区域正常交给控件
        return super().nativeEvent(eventType, message)
