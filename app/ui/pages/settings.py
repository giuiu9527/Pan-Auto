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
)
from PySide6.QtCore import Qt, Signal

from app.ui.widgets import card, field_label, label
from app.ui.icons import make_icon, make_pixmap
from app.ui.login_dialog import LoginDialog
from app.baidu.client import BaiduPanClient
from app import db


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
        name = QLabel(acc["username"] or "百度用户")
        name.setStyleSheet("font-weight:600; font-size:14px;")
        col.addWidget(name)
        sub = QLabel("✓ 当前使用中" if acc["is_active"] else "未启用")
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
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(12)

        title = QLabel("账号管理")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        root.addWidget(
            label("可添加多个百度账号；每个转存任务可分别绑定到不同账号。", "Muted")
        )

        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body)

        # 左：账号列表
        list_card = card()
        lc = QVBoxLayout(list_card)
        lc.setContentsMargins(16, 14, 16, 14)
        lc.setSpacing(8)
        head = QHBoxLayout()
        h = QLabel("已登录账号")
        h.setObjectName("FieldLabel")
        head.addWidget(h)
        head.addStretch()
        add = QPushButton("  添加账号")
        add.setObjectName("Primary")
        add.setIcon(make_icon("plus", "#ffffff", 16))
        add.clicked.connect(self.add_account_browser)
        head.addWidget(add)
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
        cl.addWidget(field_label("Cookie 添加（兜底）"))
        cl.addWidget(
            label("浏览器登录失败时，从浏览器复制百度网盘 Cookie 粘贴添加。", "Muted")
        )
        self.cookie_input = QPlainTextEdit()
        self.cookie_input.setPlaceholderText("BDUSS=xxx; STOKEN=xxx; ...")
        self.cookie_input.setMaximumHeight(120)
        cl.addWidget(self.cookie_input)
        ck_btn = QPushButton("用 Cookie 添加")
        ck_btn.setObjectName("Ghost")
        ck_btn.clicked.connect(self.add_account_cookie)
        cl.addWidget(ck_btn, alignment=Qt.AlignLeft)
        cl.addStretch()
        body.addWidget(ck_card, 2)

        self.refresh_accounts()

    # ---- 列表 ----
    def refresh_accounts(self):
        while self.list_lay.count() > 1:
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        accounts = db.list_accounts()
        if not accounts:
            empty = label("还没有账号，点右上「添加账号」开始。", "Muted")
            empty.setAlignment(Qt.AlignCenter)
            self.list_lay.insertWidget(0, empty)
            return
        for i, acc in enumerate(accounts):
            self.list_lay.insertWidget(i, AccountRow(acc, self))

    def set_active(self, account_id: int):
        db.set_active_account(account_id)
        self.refresh_accounts()
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
            self.account_changed.emit()

    # ---- 添加：浏览器 ----
    def add_account_browser(self):
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
            db.add_account(info["username"], cookies, info.get("bdstoken", ""))
            self.refresh_accounts()
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
        cookies = {}
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
        if "BDUSS" not in cookies:
            QMessageBox.warning(self, "提示", "Cookie 中缺少 BDUSS")
            return
        try:
            client = BaiduPanClient(cookies)
            info = client.get_user_info()
            if not info.get("username"):
                QMessageBox.warning(self, "失败", "Cookie 无效或已过期")
                return
            db.add_account(info["username"], cookies, info.get("bdstoken", ""))
            self.cookie_input.clear()
            self.refresh_accounts()
            self.account_changed.emit()
            QMessageBox.information(self, "成功", f"已添加账号：{info['username']}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "错误", f"添加失败：{e}")
