"""设置页：账号管理（多账号 / 扫码 / Cookie）+ 通用设置 + 目录预览。"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QMessageBox,
    QFrame,
    QScrollArea,
    QCheckBox,
    QComboBox,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Signal

from app import db
from app import theme
from app.autostart import is_autostart_enabled, set_autostart
from app.baidu.client import BaiduPanClient
from app.netdisk import provider_label
from app.quark.client import QuarkPanClient, parse_quark_cookie
from app.ui.icons import make_pixmap
from app.ui.login_dialog import LoginDialog
from app.ui.netdisk_browser import NetdiskBrowser
from app.ui.widgets import (
    card, field_label, hint, button, PageHeader, SegmentBar, StatusPill, ElidedLabel,
    page_root, InfoBox,
)


class AccountRow(QFrame):
    def __init__(self, acc: dict, page: "SettingsPage"):
        super().__init__()
        self.setObjectName("CardFlat")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        av = QLabel()
        av.setFixedSize(34, 34)
        av.setAlignment(Qt.AlignCenter)
        active = bool(acc["is_active"])
        av.setStyleSheet(f"background:{theme.PRIMARY_SOFT if active else '#EEF0F4'}; border-radius:17px;")
        av.setPixmap(make_pixmap("user", theme.PRIMARY if active else theme.MUTED_2, 18))
        lay.addWidget(av)

        col = QVBoxLayout()
        col.setSpacing(2)
        name = ElidedLabel(acc["username"] or provider_label(acc.get("provider")))
        name.setStyleSheet("font-weight:600; font-size:13px;")
        col.addWidget(name)
        sub = QLabel(provider_label(acc.get("provider")))
        sub.setObjectName("Hint")
        col.addWidget(sub)
        lay.addLayout(col, 1)

        if active:
            lay.addWidget(StatusPill("当前使用", "success"))
        else:
            use = button("设为当前", "Ghost")
            use.clicked.connect(lambda: page.set_active(acc["id"]))
            lay.addWidget(use)
        rm = button("退出", "Danger")
        rm.clicked.connect(lambda: page.remove(acc["id"], acc["username"]))
        lay.addWidget(rm)


class SettingsPage(QWidget):
    account_changed = Signal()

    def __init__(self):
        super().__init__()
        self.provider = "baidu"
        root = page_root(self)
        root.addWidget(PageHeader("设置", "账号管理与程序行为"))

        # 内容放进纵向滚动区：窗口矮时滚动，而不是把卡片挤到互相重叠
        host = QWidget()
        body = QHBoxLayout(host)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QScrollArea.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setWidget(host)
        root.addWidget(sa, 1)

        # ===== 左列：账号列表 + 通用 =====
        left = QVBoxLayout()
        left.setSpacing(14)
        body.addLayout(left, 5)

        acc_card = card()
        al = QVBoxLayout(acc_card)
        al.setContentsMargins(16, 14, 16, 14)
        al.setSpacing(10)
        head = QHBoxLayout()
        self.list_title = QLabel("已登录账号")
        self.list_title.setObjectName("SectionTitle")
        head.addWidget(self.list_title, 1)
        self.seg = SegmentBar([("baidu", "百度网盘"), ("quark", "夸克网盘")], "baidu")
        self.seg.setMaximumWidth(220)
        self.seg.changed.connect(self.set_provider)
        head.addWidget(self.seg)
        al.addLayout(head)
        al.addWidget(hint("可添加多个账号；每个同步任务可分别绑定不同账号。「当前使用」账号用于概览与新建任务的默认选择。"))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(8)
        self.list_lay.addStretch()
        self.scroll.setWidget(self.list_host)
        self.scroll.setMinimumHeight(200)
        al.addWidget(self.scroll, 1)
        left.addWidget(acc_card, 3)

        gen_card = card()
        gl = QVBoxLayout(gen_card)
        gl.setContentsMargins(16, 14, 16, 14)
        gl.setSpacing(10)
        gt = QLabel("通用")
        gt.setObjectName("SectionTitle")
        gl.addWidget(gt)
        self.autostart_cb = QCheckBox("开机自动启动（后台按计划同步）")
        self.autostart_cb.setChecked(is_autostart_enabled())
        self.autostart_cb.toggled.connect(self._on_autostart_toggled)
        gl.addWidget(self.autostart_cb)
        close_row = QHBoxLayout()
        close_row.setSpacing(10)
        close_row.addWidget(field_label("点关闭按钮时"))
        self.close_action = QComboBox()
        self.close_action.addItem("每次询问", "ask")
        self.close_action.addItem("最小化到托盘", "minimize")
        self.close_action.addItem("退出程序", "quit")
        cur = db.get_setting("close_action", "ask")
        idx = self.close_action.findData(cur)
        self.close_action.setCurrentIndex(idx if idx >= 0 else 0)
        self.close_action.currentIndexChanged.connect(self._on_close_action_changed)
        self.close_action.setFixedWidth(170)
        close_row.addWidget(self.close_action)
        close_row.addStretch()
        gl.addLayout(close_row)
        left.addWidget(gen_card, 0)

        # ===== 右列：添加账号 + 目录预览 =====
        right = QVBoxLayout()
        right.setSpacing(14)
        body.addLayout(right, 4)

        add_card = card()
        cl = QVBoxLayout(add_card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(10)
        self.add_title = QLabel("添加账号")
        self.add_title.setObjectName("SectionTitle")
        cl.addWidget(self.add_title)
        self.browser_btn = button("浏览器登录（推荐）", "Primary", "qr")
        self.browser_btn.clicked.connect(self.add_account_browser)
        cl.addWidget(self.browser_btn)
        self.cookie_hint = hint("")
        cl.addWidget(self.cookie_hint)
        self.cookie_input = QPlainTextEdit()
        self.cookie_input.setFixedHeight(84)
        cl.addWidget(self.cookie_input)
        row = QHBoxLayout()
        row.addStretch()
        self.ck_btn = button("用 Cookie 添加", "Ghost", "key")
        self.ck_btn.clicked.connect(self.add_account_cookie)
        row.addWidget(self.ck_btn)
        cl.addLayout(row)
        right.addWidget(add_card, 0)

        br_card = card()
        bl = QVBoxLayout(br_card)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(10)
        bt = QLabel("目录预览")
        bt.setObjectName("SectionTitle")
        bl.addWidget(bt)
        self.browser_hint = hint("")
        bl.addWidget(self.browser_hint)
        self.browser = NetdiskBrowser()
        self.browser.setMinimumHeight(220)
        bl.addWidget(self.browser, 1)
        right.addWidget(br_card, 1)

        self._refresh_provider_text()
        self.refresh_accounts()
        self.refresh_browser()

    def on_shown(self):
        self.refresh_accounts()

    def set_provider(self, provider: str):
        self.provider = provider
        self._refresh_provider_text()
        self.refresh_accounts()
        self.refresh_browser()

    def _refresh_provider_text(self):
        name = provider_label(self.provider)
        self.list_title.setText(f"{name}账号")
        self.add_title.setText(f"添加{name}账号")
        if self.provider == "quark":
            self.cookie_hint.setText("夸克暂只支持 Cookie 登录：在浏览器登录 pan.quark.cn 后，复制请求头里的 Cookie 粘贴到这里。")
            self.cookie_input.setPlaceholderText("__puus=xxx; kps=xxx; ...")
            self.browser_btn.setEnabled(False)
            self.browser_btn.setToolTip("夸克扫码登录后续接入；当前请用 Cookie 添加")
        else:
            self.cookie_hint.setText("浏览器登录失败时，可从浏览器复制百度网盘 Cookie（含 BDUSS）粘贴添加。")
            self.cookie_input.setPlaceholderText("BDUSS=xxx; STOKEN=xxx; ...")
            self.browser_btn.setEnabled(True)
            self.browser_btn.setToolTip("")
        self.browser_hint.setText(f"用当前{name}账号读取目录，验证登录态是否有效。")

    # ---- 列表 ----
    def refresh_accounts(self):
        while self.list_lay.count() > 1:
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        accounts = db.list_accounts(self.provider)
        if not accounts:
            empty = hint(f"还没有{provider_label(self.provider)}账号，在右侧添加。")
            empty.setAlignment(Qt.AlignCenter)
            self.list_lay.insertWidget(0, empty)
            return
        for i, acc in enumerate(accounts):
            self.list_lay.insertWidget(i, AccountRow(acc, self))

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
        if QMessageBox.question(self, "退出账号", f"确定退出账号「{username}」？绑定该账号的任务将无法运行。") == QMessageBox.Yes:
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
            db.add_account(info["username"], cookies, info.get("bdstoken", ""), provider="baidu")
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
            db.add_account(info["username"], cookies, info.get("bdstoken", ""), provider=self.provider)
            self.cookie_input.clear()
            self.refresh_accounts()
            self.refresh_browser()
            self.account_changed.emit()
            QMessageBox.information(self, "成功", f"已添加{provider_label(self.provider)}账号：{info['username']}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "错误", f"添加失败：{e}")

    # ---- 通用 ----
    def _on_autostart_toggled(self, checked: bool):
        try:
            set_autostart(checked)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "设置失败", str(e))

    def _on_close_action_changed(self, _idx: int):
        db.set_setting("close_action", self.close_action.currentData())
