"""主窗口：无边框 + 品牌色标题栏 + 左侧导航 + 内容区 + 状态栏。"""
import sys
import os as _os

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
    QSystemTrayIcon,
    QMenu,
    QCheckBox,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QPoint, QSize, QEvent, QThread, Signal
from PySide6.QtGui import QMouseEvent, QIcon, QAction

from app.config import APP_TITLE, APP_VERSION, APP_NAME
from app import db
from app import update_client
from app import theme
from app.netdisk import provider_label
from app.core.scheduler import Scheduler
from app.ui.icons import make_icon, make_pixmap
from app.ui.widgets import ElidedLabel
from app.ui.pages.home import HomePage
from app.ui.pages.auto_sync import AutoSyncPage
from app.ui.pages.batch_rename import BatchRenamePage
from app.ui.pages.ad_insert import AdInsertPage
from app.ui.pages.ad_clean import AdCleanPage
from app.ui.pages.settings import SettingsPage
from app.ui.pages.logs import LogsPage
from app.ui.pages.friend_message import FriendMessagePage

if getattr(sys, "frozen", False):
    # PyInstaller onedir：资源在 _internal 下（_MEIPASS），不是 exe 同级目录
    _base = getattr(sys, "_MEIPASS", _os.path.dirname(sys.executable))
    _ICON_PATH = _os.path.join(_base, "app", "ui", "assets", "app.ico")
else:
    _ICON_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "assets", "app.ico")

# (key, 文字, 图标, 分组)
NAV = [
    ("home", "概览", "home", "总览"),
    ("auto", "自动同步", "sync", "同步"),
    ("friends", "好友 / 群文件", "users", "同步"),
    ("rename", "批量重命名", "edit", "整理"),
    ("adclean", "广告清理", "eraser", "整理"),
    ("ad", "广告插入", "target", "整理"),
    ("logs", "运行记录", "logs", "系统"),
    ("settings", "设置", "settings", "系统"),
]


class TitleBar(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.window_ref = window
        self.setObjectName("TitleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(38)
        self._drag_pos: QPoint | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 0, 0)
        lay.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(make_pixmap("cloud", "#ffffff", 16, width=2.2))
        lay.addWidget(logo)
        title = QLabel(APP_NAME)
        title.setObjectName("TitleText")
        lay.addWidget(title)
        sub = QLabel("网盘自动转存 · 定时同步")
        sub.setObjectName("TitleSub")
        lay.addWidget(sub)
        lay.addStretch()

        self.min_btn = self._win_btn("minus", "最小化", window.showMinimized)
        self.max_btn = self._win_btn("square", "最大化", self._toggle_max_restore)
        self.close_btn = self._win_btn("x", "关闭", window.close, close=True)
        lay.addWidget(self.min_btn)
        lay.addWidget(self.max_btn)
        lay.addWidget(self.close_btn)

    @staticmethod
    def _win_btn(icon: str, tip: str, slot, close: bool = False) -> QPushButton:
        b = QPushButton()
        b.setObjectName("WinBtnClose" if close else "WinBtn")
        b.setIcon(make_icon(icon, "#ffffff", 14, width=2.2))
        b.setIconSize(QSize(14, 14))
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._drag_pos = (
                e.globalPosition().toPoint() - self.window_ref.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._drag_pos and e.buttons() & Qt.LeftButton and not self.window_ref.isMaximized():
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
        self.max_btn.setIcon(make_icon("restore" if maximized else "square", "#ffffff", 14, width=2.2))
        self.max_btn.setToolTip("还原" if maximized else "最大化")


class NavButton(QPushButton):
    def __init__(self, icon_name: str, text: str):
        super().__init__("  " + text)
        self.icon_name = icon_name
        self.setObjectName("NavItem")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(18, 18))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._update_icon(False)
        self.toggled.connect(self._update_icon)

    def _update_icon(self, checked: bool):
        self.setIcon(make_icon(self.icon_name, theme.PRIMARY if checked else theme.TEXT_2, 18))


class AccountCard(QFrame):
    def __init__(self, on_click):
        super().__init__()
        self.setObjectName("AccountCard")
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = on_click
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(9)
        self.avatar = QLabel()
        self.avatar.setFixedSize(30, 30)
        self.avatar.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.avatar)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.name = ElidedLabel("未登录", "AccountName")
        self.sub = ElidedLabel("点击添加账号", "AccountSub")
        col.addWidget(self.name)
        col.addWidget(self.sub)
        lay.addLayout(col, 1)
        self._set_avatar(False)

    def _set_avatar(self, active: bool):
        self.avatar.setStyleSheet(
            f"background:{theme.PRIMARY_SOFT if active else '#EEF0F4'}; border-radius:15px;"
        )
        self.avatar.setPixmap(make_pixmap("user", theme.PRIMARY if active else theme.MUTED_2, 16))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._on_click()

    def refresh(self):
        acc = db.get_active_account()
        n = db.account_count()
        if acc and acc.get("username"):
            self.name.setText(acc["username"])
            extra = f" · 共 {n} 个账号" if n > 1 else ""
            self.sub.setText(f"{provider_label(acc.get('provider'))}{extra}")
            self._set_avatar(True)
        else:
            self.name.setText("未登录")
            self.sub.setText("点击添加账号")
            self._set_avatar(False)


class Sidebar(QWidget):
    def __init__(self, on_nav):
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(212)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        brand = QWidget()
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(18, 16, 14, 12)
        bl.setSpacing(9)
        logo = QLabel()
        logo.setFixedSize(30, 30)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(f"background:{theme.PRIMARY}; border-radius:8px;")
        logo.setPixmap(make_pixmap("cloud", "#ffffff", 17, width=2.2))
        bl.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel(APP_NAME)
        name.setObjectName("Brand")
        col.addWidget(name)
        ver = QLabel(f"版本 {APP_VERSION}")
        ver.setObjectName("BrandSub")
        col.addWidget(ver)
        bl.addLayout(col)
        bl.addStretch()
        lay.addWidget(brand)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        last_section = None
        for key, text, icon, section in NAV:
            if section != last_section:
                sec = QLabel(section)
                sec.setObjectName("NavSection")
                lay.addWidget(sec)
                last_section = section
            btn = NavButton(icon, text)
            btn.clicked.connect(lambda _=False, k=key: on_nav(k))
            self.group.addButton(btn)
            self.buttons[key] = btn
            lay.addWidget(btn)

        lay.addStretch()

        box = QWidget()
        blay = QVBoxLayout(box)
        blay.setContentsMargins(12, 8, 12, 14)
        self.card = AccountCard(lambda: on_nav("settings"))
        blay.addWidget(self.card)
        lay.addWidget(box)

    def refresh_account(self):
        self.card.refresh()


class UpdateCheckWorker(QThread):
    """启动时静默查一次清单，只用来在状态栏提示「有新版本」；真正更新走 update.exe。"""

    done = Signal(dict)

    def run(self):
        try:
            self.done.emit(update_client.check())
        except Exception:  # noqa: BLE001  静默失败，不打扰用户
            self.done.emit({})


class StatusBar(QWidget):
    def __init__(self, on_check_update):
        super().__init__()
        self.setObjectName("StatusBar")
        self.setFixedHeight(32)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 12, 0)
        lay.setSpacing(8)
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background:{theme.SUCCESS}; border-radius:4px;")
        lay.addWidget(dot)
        self.text = QLabel("后台调度器运行中 · 请遵守网盘服务条款，注意转存节流")
        self.text.setObjectName("StatusText")
        lay.addWidget(self.text, 1)
        self.update_hint = QLabel("")
        self.update_hint.setObjectName("Pill")
        self.update_hint.setProperty("kind", "warning")
        self.update_hint.hide()
        lay.addWidget(self.update_hint)
        self.update_btn = QPushButton("检查更新")
        self.update_btn.setObjectName("StatusAction")
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(on_check_update)
        lay.addWidget(self.update_btn)
        ver = QLabel(f"{APP_VERSION}")
        ver.setObjectName("VersionBadge")
        lay.addWidget(ver)

    def set_text(self, text: str):
        self.text.setText(text)

    def show_update_available(self, version: str):
        self.update_hint.setText(f"有新版本 v{version}")
        self.update_hint.show()
        self.update_btn.setText("立即更新")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Root")
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.resize(1220, 780)
        self.setMinimumSize(1080, 680)
        self._app_icon = QIcon(_ICON_PATH) if _os.path.exists(_ICON_PATH) else QIcon()
        if not self._app_icon.isNull():
            self.setWindowIcon(self._app_icon)
            _app = QApplication.instance()
            if _app:
                _app.setWindowIcon(self._app_icon)  # 任务栏/托盘统一用自定义图标
        self._update_workers = []
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
        self.stack.setObjectName("Content")
        mid.addWidget(self.stack, 1)

        self.statusbar = StatusBar(self.check_for_updates_manual)
        outer.addWidget(self.statusbar)

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
        self.friends.tasks_changed.connect(self.auto.reload_tasks)
        self.auto.tasks_changed.connect(self.friends.reload_sync_tasks)

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
        self.scheduler.task_started.connect(self._on_scheduled_task_started)
        self.scheduler.task_ran.connect(self._on_scheduled_task_ran)
        self.scheduler.swept.connect(self._on_scheduler_swept)
        self.scheduler.start()
        self.auto.scheduler = self.scheduler
        self._setup_tray()

    def _on_scheduled_task_started(self, task_id: int):
        self.statusbar.set_text("正在执行定时同步…")
        if self.stack.currentWidget() is self.auto:
            self.auto.reload_tasks()

    # ---- 系统托盘 ----
    def _setup_tray(self):
        if hasattr(self, "tray"):
            return
        self.tray = QSystemTrayIcon(self)
        if not self._app_icon.isNull():
            self.tray.setIcon(self._app_icon)
        self.tray.setToolTip(APP_TITLE)
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

    def on_ipc_command(self, cmd: str):
        """来自另一份启动 / 更新器的命令：show = 唤到前台；quit = 正常退出（收托盘、停调度器）。"""
        if cmd == "show":
            self._show_window()
        elif cmd == "quit":
            self._quit_from_tray()

    def _notify_tray_once(self):
        if self._tray_notified or not hasattr(self, "tray"):
            return
        self._tray_notified = True
        try:
            self.tray.showMessage(
                APP_NAME,
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
        self.statusbar.set_text("后台调度器运行中 · 请遵守网盘服务条款，注意转存节流")
        if self.stack.currentWidget() is self.auto:
            self.auto.reload_tasks()
        if self.stack.currentWidget() is self.logs:
            self.logs.reload()
        if self.stack.currentWidget() is self.home:
            self.home.refresh()

    def _on_scheduler_swept(self):
        if self.stack.currentWidget() is self.logs:
            self.logs.reload()
        if self.stack.currentWidget() is self.auto:
            self.auto.reload_tasks()

    def closeEvent(self, e):
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
            e.ignore()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange and hasattr(self, "titlebar"):
            self.titlebar.refresh_state()

    # ---- 更新（OpenList 方案：主程序只负责拉起 update.exe）----
    def check_updates_on_startup(self):
        """启动后静默查一次；有新版本只在状态栏提示，不弹窗。"""
        if _os.environ.get("PAN_AUTO_DISABLE_UPDATE") or not update_client.is_configured():
            return
        if any(isinstance(w, UpdateCheckWorker) for w in self._update_workers):
            return
        worker = UpdateCheckWorker()
        worker.done.connect(self._on_startup_checked)
        worker.finished.connect(lambda w=worker: self._update_workers.remove(w))
        self._update_workers.append(worker)
        worker.start()

    def _on_startup_checked(self, info: dict):
        if info.get("has_update"):
            self.statusbar.show_update_available(info.get("remote", ""))

    def check_for_updates_manual(self):
        """「检查更新」按钮：启动旁边的 update.exe（源码版启动 updater_main.py）。"""
        ok, msg = update_client.launch_updater()
        if not ok:
            QMessageBox.warning(self, "无法启动更新器", msg)

    # ---- 导航 ----
    def navigate(self, key: str):
        if key not in self.pages:
            return
        self.stack.setCurrentWidget(self.pages[key])
        if key in self.sidebar.buttons:
            self.sidebar.buttons[key].setChecked(True)
        page = self.pages[key]
        if hasattr(page, "on_shown"):
            page.on_shown()

    def on_account_changed(self):
        self.sidebar.refresh_account()
        for p in (self.auto, self.rename, self.adclean, self.ad_insert, self.friends):
            p.refresh_accounts()
        self.home.refresh()

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

        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            GWL_STYLE = -16
            WS_THICKFRAME = 0x00040000
            WS_CAPTION = 0x00C00000
            WS_MAXIMIZEBOX = 0x00010000
            WS_MINIMIZEBOX = 0x00020000
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            user32.SetWindowLongW(
                hwnd, GWL_STYLE,
                (style & ~WS_CAPTION) | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX,
            )
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
        except Exception:  # noqa: BLE001  离屏/非原生平台忽略
            pass

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
