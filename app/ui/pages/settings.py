"""设置页：多账号管理（添加 / 切换当前 / 删除）。"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QMessageBox,
    QFrame,
    QScrollArea,
    QButtonGroup,
    QCheckBox,
    QComboBox,
)
from PySide6.QtCore import Qt, Signal

from app.ui.widgets import card, field_label, label
from app.ui.icons import make_icon, make_pixmap
from app.ui.login_dialog import LoginDialog
from app.ui.netdisk_browser import NetdiskBrowser
from app.baidu.client import BaiduPanClient
from app.quark.client import QuarkPanClient, parse_quark_cookie
from app.netdisk import provider_label
from app import db
from app.autostart import is_autostart_enabled, set_autostart


class AccountRow(QFrame):
    def __init__(self, acc: dict, page: "SettingsPage"):
        super().__init__()
        self.setObjectName("Card")
        self.acc = acc
        self.page = page
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)

        av = QLabel()
        color = "#2f6bff" if acc["is_active"] else "#9aa4b5"
        av.setPixmap(make_pixmap("user", color, 22))
        lay.addWidget(av)

        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(acc["username"] or provider_label(acc.get("provider")))
        name.setStyleSheet("font-weight:600; font-size:14px;")
        col.addWidget(name)
        prefix = provider_label(acc.get("provider"))
        sub = QLabel(f"✓ {prefix} · 当前使用中" if acc["is_active"] else f"{prefix} · 未启用")
        sub.setObjectName("Muted")
        sub.setStyleSheet(
            "color:#18a957; font-size:12px;" if acc["is_active"]
            else "color:#8b95a7; font-size:12px;"
        )
        col.addWidget(sub)
        lay.addLayout(col)
        lay.addStretch()

        if not acc["is_active"]:
            use = QPushButton("设为当前")
            use.setObjectName("Ghost")
            use.clicked.connect(lambda: page.set_active(acc["id"]))
            lay.addWidget(use)
        rm = QPushButton("退出")
        rm.setObjectName("Danger")
        rm.clicked.connect(lambda: page.remove(acc["id"], acc["username"]))
        lay.addWidget(rm)


class SettingsPage(QWidget):
    account_changed = Signal()

    def __init__(self):
        super().__init__()
        self.provider = "baidu"
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        title = QLabel("账号管理")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        root.addWidget(
            label("可添加多个网盘账号；后续任务可分别绑定到不同账号。", "Muted")
        )

        # 开机自启
        self.autostart_cb = QCheckBox("开机自动启动")
        self.autostart_cb.setStyleSheet("font-size:13px; padding:2px 0;")
        self.autostart_cb.setChecked(is_autostart_enabled())
        self.autostart_cb.toggled.connect(self._on_autostart_toggled)
        root.addWidget(self.autostart_cb)

        # 关闭按钮行为
        close_row = QHBoxLayout()
        close_row.setSpacing(8)
        close_lbl = QLabel("点关闭按钮时：")
        close_lbl.setStyleSheet("font-size:13px;")
        close_row.addWidget(close_lbl)
        self.close_action = QComboBox()
        self.close_action.addItem("每次询问", "ask")
        self.close_action.addItem("最小化到托盘", "minimize")
        self.close_action.addItem("退出程序", "quit")
        cur = db.get_setting("close_action", "ask")
        idx = self.close_action.findData(cur)
        self.close_action.setCurrentIndex(idx if idx >= 0 else 0)
        self.close_action.currentIndexChanged.connect(self._on_close_action_changed)
        self.close_action.setFixedWidth(160)
        close_row.addWidget(self.close_action)
        close_row.addStretch()
        root.addLayout(close_row)

        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body)

        # 左：账号列表
        list_card = card()
        lc = QVBoxLayout(list_card)
        lc.setContentsMargins(16, 14, 16, 14)
        lc.setSpacing(8)
        head = QHBoxLayout()
        self.list_title = QLabel("已登录账号")
        self.list_title.setObjectName("FieldLabel")
        head.addWidget(self.list_title)
        head.addStretch()
        self.provider_group = QButtonGroup(self)
        self.baidu_tab = QPushButton("百度")
        self.baidu_tab.setObjectName("Tab")
        self.baidu_tab.setCheckable(True)
        self.baidu_tab.setChecked(True)
        self.quark_tab = QPushButton("夸克")
        self.quark_tab.setObjectName("Tab")
        self.quark_tab.setCheckable(True)
        self.provider_group.addButton(self.baidu_tab)
        self.provider_group.addButton(self.quark_tab)
        self.provider_group.setExclusive(True)
        self.baidu_tab.clicked.connect(lambda: self.set_provider("baidu"))
        self.quark_tab.clicked.connect(lambda: self.set_provider("quark"))
        head.addWidget(self.baidu_tab)
        head.addWidget(self.quark_tab)
        lc.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch()
        self.scroll.setWidget(self.list_host)
        lc.addWidget(self.scroll, 1)
        body.addWidget(list_card, 3)

        # 右：Cookie 兜底添加
        ck_card = card()
        cl = QVBoxLayout(ck_card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(7)
        self.cookie_title = field_label("Cookie 添加（兜底）")
        cl.addWidget(self.cookie_title)
        self.cookie_hint = label("", "Muted")
        self.cookie_hint.setWordWrap(True)
        cl.addWidget(self.cookie_hint)
        self.cookie_input = QPlainTextEdit()
        self.cookie_input.setMaximumHeight(120)
        cl.addWidget(self.cookie_input)
        btns = QHBoxLayout()
        self.browser_btn = QPushButton("  扫码添加")
        self.browser_btn.setObjectName("Primary")
        self.browser_btn.setIcon(make_icon("plus", "#ffffff", 16))
        self.browser_btn.clicked.connect(self.add_account_browser)
        btns.addWidget(self.browser_btn)
        self.ck_btn = QPushButton("用 Cookie 添加")
        self.ck_btn.setObjectName("Ghost")
        self.ck_btn.clicked.connect(self.add_account_cookie)
        btns.addWidget(self.ck_btn)
        btns.addStretch()
        cl.addLayout(btns)
        cl.addWidget(field_label("目录浏览"))
        self.browser_hint = label("", "Muted")
        cl.addWidget(self.browser_hint)
        self.browser = NetdiskBrowser()
        cl.addWidget(self.browser, 1)
        body.addWidget(ck_card, 2)

        self._refresh_provider_text()
        self.refresh_accounts()
        self.refresh_browser()

    def set_provider(self, provider: str):
        self.provider = provider
        self._refresh_provider_text()
        self.refresh_accounts()
        self.refresh_browser()

    def _refresh_provider_text(self):
        name = provider_label(self.provider)
        self.list_title.setText(f"{name}账号")
        self.cookie_title.setText(f"{name} Cookie 添加")
        if self.provider == "quark":
            self.cookie_hint.setText(
                "在浏览器登录 pan.quark.cn 后，复制请求 Cookie 粘贴到这里。"
                "已支持夸克账号校验、目录浏览与分享转存（扫码登录后续接入）。"
            )
            self.cookie_input.setPlaceholderText("__puus=xxx; kps=xxx; ...")
            self.browser_btn.setEnabled(False)
            self.browser_btn.setToolTip("夸克扫码登录后续接入；当前请用 Cookie 添加")
        else:
            self.cookie_hint.setText(
                "浏览器登录失败时，从浏览器复制百度网盘 Cookie 粘贴添加。"
            )
            self.cookie_input.setPlaceholderText("BDUSS=xxx; STOKEN=xxx; ...")
            self.browser_btn.setEnabled(True)
            self.browser_btn.setToolTip("")
        self.browser_hint.setText(f"用于验证当前{provider_label(self.provider)}账号是否可读取目录。")

    # ---- 列表 ----
    def refresh_accounts(self):
        while self.list_lay.count() > 1:
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        accounts = db.list_accounts(self.provider)
        if not accounts:
            empty = label(f"还没有{provider_label(self.provider)}账号。", "Muted")
            empty.setAlignment(Qt.AlignCenter)
            self.list_lay.insertWidget(0, empty)
            return
        for i, acc in enumerate(accounts):
            self.list_lay.insertWidget(i, AccountRow(acc, self))
        self.refresh_browser()

    def refresh_browser(self):
        accounts = db.list_accounts(self.provider)
        if not accounts:
            self.browser.status.setText(f"暂无{provider_label(self.provider)}账号")
            self.browser.list.clear()
            self.browser.path_label.setText("/")
            return
        account = next((x for x in accounts if x.get("is_active")), accounts[0])
        self.browser.set_account(account["id"])

    def set_active(self, account_id: int):
        db.set_active_account(account_id)
        self.refresh_accounts()
        self.refresh_browser()
        self.account_changed.emit()

    def remove(self, account_id: int, username: str):
        if (
            QMessageBox.question(
                self, "退出账号", f"确定退出账号「{username}」？"
            )
            == QMessageBox.Yes
        ):
            db.delete_account(account_id)
            self.refresh_accounts()
            self.refresh_browser()
            self.account_changed.emit()

    # ---- 添加：浏览器 ----
    def add_account_browser(self):
        if self.provider != "baidu":
            QMessageBox.information(self, "提示", "夸克暂时请使用 Cookie 添加。")
            return
        dlg = LoginDialog(self)
        dlg.logged_in.connect(self._save_from_cookies)
        dlg.exec()

    def _save_from_cookies(self, cookies: dict):
        try:
            client = BaiduPanClient(cookies)
            info = client.get_user_info()
            if not info.get("username"):
                QMessageBox.warning(self, "失败", "未能确认账号，请重试")
                return
            db.add_account(
                info["username"], cookies, info.get("bdstoken", ""), provider="baidu"
            )
            self.refresh_accounts()
            self.refresh_browser()
            self.account_changed.emit()
            QMessageBox.information(self, "成功", f"已添加账号：{info['username']}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "错误", f"登录校验失败：{e}")

    # ---- 添加：Cookie ----
    def add_account_cookie(self):
        raw = self.cookie_input.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "请粘贴 Cookie")
            return
        cookies = parse_quark_cookie(raw)
        if self.provider == "baidu" and "BDUSS" not in cookies:
            QMessageBox.warning(self, "提示", "百度 Cookie 中缺少 BDUSS")
            return
        if self.provider == "quark" and not cookies:
            QMessageBox.warning(self, "提示", "请粘贴夸克 Cookie")
            return
        try:
            client = QuarkPanClient(cookies) if self.provider == "quark" else BaiduPanClient(cookies)
            info = client.get_user_info()
            if not info.get("username"):
                QMessageBox.warning(self, "失败", "Cookie 无效或已过期")
                return
            db.add_account(
                info["username"],
                cookies,
                info.get("bdstoken", ""),
                provider=self.provider,
            )
            self.cookie_input.clear()
            self.refresh_accounts()
            self.refresh_browser()
            self.account_changed.emit()
            QMessageBox.information(
                self,
                "成功",
                f"已添加{provider_label(self.provider)}账号：{info['username']}",
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "错误", f"添加失败：{e}")

    # ---- 开机自启 ----
    def _on_autostart_toggled(self, checked: bool):
        set_autostart(checked)

    # ---- 关闭按钮行为 ----
    def _on_close_action_changed(self, _idx: int):
        db.set_setting("close_action", self.close_action.currentData())
