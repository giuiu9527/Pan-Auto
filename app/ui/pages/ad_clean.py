"""广告清理页：扫描网盘文件夹里命中广告关键词的文件/文件夹，勾选后删除。

关键词与「自动同步」的去广告共用同一份配置（app_settings.ad_keywords）。
"""
from collections import deque

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QLabel,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QStackedWidget,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor

from app.ui.widgets import card, field_group, field_label, label
from app.ui.icons import make_icon
from app.ui.netdisk_browser import NetdiskBrowser
from app.netdisk import get_client_for_account, account_display_name
from app.core.transfer import DEFAULT_AD_KEYWORDS
from app import db


def _fmt_size(n: int) -> str:
    if not n:
        return ""
    x = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024:
            return f"{x:.0f}{unit}" if unit == "B" else f"{x:.1f}{unit}"
        x /= 1024
    return f"{x:.1f}PB"


def _parse_keywords(raw: str) -> list[str]:
    import re

    return [k.strip() for k in re.split(r"[\n,，]", raw or "") if k.strip()]


class ScanWorker(QThread):
    progress = Signal(str)
    done = Signal(list)
    error = Signal(str)

    def __init__(self, account_id, folder, keywords, recursive, whitelist=None):
        super().__init__()
        self.account_id = account_id
        self.folder = folder
        self.keywords = [k.lower() for k in keywords]
        self.whitelist = [w.lower() for w in (whitelist or [])]
        self.recursive = recursive

    def run(self):
        client = get_client_for_account(self.account_id)
        if client is None:
            self.error.emit("账号不可用")
            return
        matched = []
        q = deque([self.folder])
        scanned = 0
        try:
            while q and scanned < 1000:
                cur = q.popleft()
                scanned += 1
                self.progress.emit(f"扫描中… 已查 {scanned} 个目录，命中 {len(matched)}")
                items = client.list_dir(cur)
                for it in items:
                    name = it.get("server_filename", "")
                    low = name.lower()
                    if any(w in low for w in self.whitelist):
                        continue  # 白名单：保留，不清理
                    if any(k in low for k in self.keywords):
                        matched.append(
                            {
                                "name": name,
                                "path": it.get("path", ""),
                                "size": it.get("size", 0),
                                "dir": cur,
                                "isdir": bool(it.get("isdir")),
                            }
                        )
                        # 命中文件夹时删整个子树，无需继续扫描里面的项。
                        continue
                    if it.get("isdir") and self.recursive and it.get("path"):
                        q.append(it["path"])
            self.done.emit(matched)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class DeleteWorker(QThread):
    done = Signal(dict)

    def __init__(self, account_id, paths):
        super().__init__()
        self.account_id = account_id
        self.paths = paths

    def run(self):
        client = get_client_for_account(self.account_id)
        if client is None:
            self.done.emit({"ok": False, "error": "账号不可用"})
            return
        try:
            res = client.delete_files(self.paths)
            errno = res.get("errno")
            self.done.emit(
                {
                    "ok": errno in (0, None),
                    "error": res.get("message", "") if errno not in (0, None) else "",
                    "count": len(self.paths),
                }
            )
        except Exception as e:  # noqa: BLE001
            self.done.emit({"ok": False, "error": str(e)})


class AdCleanPage(QWidget):
    def __init__(self):
        super().__init__()
        self.folder = "/"
        self._workers = []

        columns = QHBoxLayout(self)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(0)

        # ===== 左：表单 =====
        left = QWidget()
        left.setFixedWidth(438)
        columns.addWidget(left)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(22, 14, 16, 16)
        left_lay.setSpacing(11)

        title = QLabel("广告清理")
        title.setObjectName("PageTitle")
        left_lay.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_lay.addWidget(scroll, 1)
        body = QWidget()
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(11)

        form = card()
        fl = QVBoxLayout(form)
        fl.setContentsMargins(18, 16, 18, 16)
        fl.setSpacing(12)

        self.account = QComboBox()
        fl.addWidget(field_group("账号 *", self.account))

        dir_widget = QWidget()
        dr = QHBoxLayout(dir_widget)
        dr.setContentsMargins(0, 0, 0, 0)
        dr.setSpacing(8)
        self.folder_edit = QLineEdit("/")
        dr.addWidget(self.folder_edit, 1)
        pick = QPushButton()
        pick.setObjectName("Ghost")
        pick.setIcon(make_icon("folder", "#4a5365", 16))
        pick.setFixedSize(42, 40)
        pick.setToolTip("浏览网盘选择文件夹")
        pick.clicked.connect(self.pick_folder)
        dr.addWidget(pick)
        fl.addWidget(field_group("要清理的文件夹 *", dir_widget))

        self.recursive = QCheckBox("包括子文件夹（递归扫描）")
        self.recursive.setChecked(True)
        fl.addWidget(self.recursive)

        fl.addWidget(field_label("广告关键词（命中即视为广告文件/文件夹）"))
        fl.addWidget(label("一行一个或用逗号分隔；与「自动同步」的去广告共用。", "Muted"))
        self.kw_input = QPlainTextEdit()
        self.kw_input.setPlainText(db.get_setting("ad_keywords", DEFAULT_AD_KEYWORDS))
        self.kw_input.setMaximumHeight(110)
        fl.addWidget(self.kw_input)

        fl.addWidget(field_label("白名单关键词（命中则保留，绝不清理）"))
        fl.addWidget(label("保护你自己插入的广告：文件名含这些词就不删、不跳过。", "Muted"))
        self.wl_input = QPlainTextEdit()
        self.wl_input.setPlainText(db.get_setting("ad_whitelist", ""))
        self.wl_input.setMaximumHeight(80)
        self.wl_input.setPlaceholderText("如：我的公众号名、你的推广品牌…")
        fl.addWidget(self.wl_input)

        save_kw = QPushButton("保存关键词/白名单")
        save_kw.setObjectName("Ghost")
        save_kw.clicked.connect(self.save_keywords)
        kwrow = QHBoxLayout()
        kwrow.addStretch()
        kwrow.addWidget(save_kw)
        fl.addLayout(kwrow)
        fl.addStretch()
        root.addWidget(form)

        self.scan_btn = QPushButton("  扫描广告文件")
        self.scan_btn.setObjectName("Primary")
        self.scan_btn.setMinimumHeight(44)
        self.scan_btn.setCursor(Qt.PointingHandCursor)
        self.scan_btn.setIcon(make_icon("search", "#ffffff", 16))
        self.scan_btn.clicked.connect(self.scan)
        left_lay.addWidget(self.scan_btn)

        # ===== 右：结果 / 目录选择 =====
        self.right_stack = QStackedWidget()
        columns.addWidget(self.right_stack, 1)
        self.right_stack.addWidget(self._build_result_page())
        self.right_stack.addWidget(self._build_folder_page())

        self.refresh_accounts()

    def _build_result_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(6, 14, 20, 16)
        rl.setSpacing(10)
        head = QHBoxLayout()
        t = QLabel("命中的广告文件/文件夹")
        t.setObjectName("PageTitle")
        head.addWidget(t)
        head.addStretch()
        self.status = QLabel("先选文件夹，点「扫描广告文件」")
        self.status.setObjectName("Muted")
        head.addWidget(self.status)
        rl.addLayout(head)

        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(6, 6, 6, 6)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["文件/文件夹名", "大小", "所在目录"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        cl.addWidget(self.table)
        rl.addWidget(c, 1)

        foot = QHBoxLayout()
        sel = QPushButton("全选")
        sel.setObjectName("Ghost")
        sel.clicked.connect(lambda: self._check_all(True))
        clr = QPushButton("全不选")
        clr.setObjectName("Ghost")
        clr.clicked.connect(lambda: self._check_all(False))
        foot.addWidget(sel)
        foot.addWidget(clr)
        foot.addStretch()
        self.del_btn = QPushButton("  删除选中")
        self.del_btn.setObjectName("Danger")
        self.del_btn.setIcon(make_icon("trash", "#e5484d", 16))
        self.del_btn.clicked.connect(self.delete_selected)
        foot.addWidget(self.del_btn)
        rl.addLayout(foot)
        return page

    def _build_folder_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(6, 14, 20, 16)
        rl.setSpacing(10)
        head = QHBoxLayout()
        t = QLabel("选择文件夹")
        t.setObjectName("PageTitle")
        head.addWidget(t)
        head.addStretch()
        close = QPushButton("✕")
        close.setObjectName("IconBtn")
        close.setFixedSize(30, 28)
        close.clicked.connect(lambda: self.right_stack.setCurrentIndex(0))
        head.addWidget(close)
        rl.addLayout(head)
        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(8)
        self.browser = NetdiskBrowser()
        cl.addWidget(self.browser)
        use = QPushButton("  使用此文件夹")
        use.setObjectName("Primary")
        use.setIcon(make_icon("check", "#ffffff", 16))
        use.clicked.connect(self._use_folder)
        cl.addWidget(use)
        rl.addWidget(c, 1)
        return page

    # ---- 账号 ----
    def on_shown(self):
        self.refresh_accounts()

    def refresh_accounts(self):
        prev = self.account.currentData()
        self.account.blockSignals(True)
        self.account.clear()
        for acc in db.list_accounts():
            self.account.addItem(account_display_name(acc), acc["id"])
        idx = self.account.findData(prev)
        if idx >= 0:
            self.account.setCurrentIndex(idx)
        self.account.blockSignals(False)

    def save_keywords(self):
        db.set_setting("ad_keywords", self.kw_input.toPlainText().strip())
        db.set_setting("ad_whitelist", self.wl_input.toPlainText().strip())
        QMessageBox.information(
            self, "已保存", "广告关键词与白名单已更新（自动同步的去广告也会用）。"
        )

    # ---- 目录选择 ----
    def pick_folder(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先选择账号")
            return
        self.right_stack.setCurrentIndex(1)
        self.browser.account_id = acc_id
        self.browser.load(self.folder_edit.text().strip() or "/")

    def _use_folder(self):
        self.folder_edit.setText(self.browser.current_dir())
        self.right_stack.setCurrentIndex(0)

    # ---- 扫描 ----
    def scan(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先选择账号")
            return
        kws = _parse_keywords(self.kw_input.toPlainText())
        if not kws:
            QMessageBox.warning(self, "提示", "请先填写广告关键词")
            return
        db.set_setting("ad_keywords", self.kw_input.toPlainText().strip())
        db.set_setting("ad_whitelist", self.wl_input.toPlainText().strip())
        wl = _parse_keywords(self.wl_input.toPlainText())
        self.right_stack.setCurrentIndex(0)
        self.table.setRowCount(0)
        self.scan_btn.setEnabled(False)
        self.status.setText("扫描中…")
        w = ScanWorker(acc_id, self.folder_edit.text().strip() or "/", kws, self.recursive.isChecked(), wl)
        w.progress.connect(self.status.setText)
        w.done.connect(self._on_scanned)
        w.error.connect(self._on_scan_error)
        w.finished.connect(lambda x=w: self._drop(x))
        self._workers.append(w)
        w.start()

    def _on_scanned(self, matched: list):
        self.scan_btn.setEnabled(True)
        self._matched = matched
        self.table.setRowCount(0)
        for f in matched:
            r = self.table.rowCount()
            self.table.insertRow(r)
            it = QTableWidgetItem(f["name"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, f)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem(_fmt_size(f.get("size", 0))))
            from app.quark.client import display_path
            self.table.setItem(r, 2, QTableWidgetItem(display_path(f.get("dir", ""))))
        self.status.setText(f"命中 {len(matched)} 个广告文件/文件夹（默认全选，可取消不删的）")
        if not matched:
            QMessageBox.information(self, "扫描完成", "没有命中广告关键词的文件或文件夹。")

    def _on_scan_error(self, msg: str):
        self.scan_btn.setEnabled(True)
        self.status.setText(f"扫描失败：{msg}")
        QMessageBox.warning(self, "扫描失败", msg)

    def _check_all(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(state)

    def delete_selected(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            return
        paths = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it.checkState() == Qt.Checked:
                f = it.data(Qt.UserRole)
                if f.get("path"):
                    paths.append(f["path"])
        if not paths:
            QMessageBox.warning(self, "提示", "请先勾选要删除的文件")
            return
        if QMessageBox.question(
            self, "确认删除", f"将永久删除选中的 {len(paths)} 个文件，确定？"
        ) != QMessageBox.Yes:
            return
        self.del_btn.setEnabled(False)
        self.status.setText("删除中…")
        w = DeleteWorker(acc_id, paths)
        w.done.connect(self._on_deleted)
        w.finished.connect(lambda x=w: self._drop(x))
        self._workers.append(w)
        w.start()

    def _on_deleted(self, result: dict):
        self.del_btn.setEnabled(True)
        if result.get("ok"):
            QMessageBox.information(self, "完成", f"已删除 {result.get('count', 0)} 个广告文件。")
            self.scan()  # 重新扫描刷新
        else:
            QMessageBox.warning(self, "删除失败", result.get("error") or "未知错误")

    def _drop(self, w):
        if w in self._workers:
            self._workers.remove(w)
