"""广告清理页：扫描网盘文件夹里命中广告关键词的文件/文件夹，勾选后删除。

关键词与「自动同步」的去广告共用同一份配置（app_settings.ad_keywords）。
"""
import re
from collections import deque

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QStackedWidget,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer

from app import db
from app import theme
from app.core.transfer import DEFAULT_AD_KEYWORDS
from app.core import adfilter
from app.core.adfilter import contains_any, parse_keywords
from app.netdisk import get_client_for_account, account_display_name
from app.quark.client import display_path
from app.ui.icons import make_icon
from app.ui.netdisk_browser import NetdiskBrowser
from app.ui.widgets import (
    ComboBox,
    card, field_group, button, square_button, icon_button, input_with_button,
    PageHeader, TwoColumn, scroll_wrap, setup_table, table_frame, fmt_size,
    EmptyState, label, hint,
)


def _parse_keywords(raw: str) -> list[str]:
    return parse_keywords(raw)


class ScanWorker(QThread):
    progress = Signal(str)
    done = Signal(list)
    error = Signal(str)

    def __init__(self, account_id, folder, keywords, recursive, whitelist=None):
        super().__init__()
        self.account_id = account_id
        self.folder = folder
        self.keywords = list(keywords)
        self.whitelist = list(whitelist or [])
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
                for it in client.list_dir(cur):
                    name = it.get("server_filename", "")
                    if contains_any(name, self.whitelist):
                        continue
                    if contains_any(name, self.keywords):
                        matched.append({
                            "name": name, "path": it.get("path", ""), "size": it.get("size", 0),
                            "dir": cur, "isdir": bool(it.get("isdir")),
                        })
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
            if errno in (0, None) and res.get("taskid") and hasattr(client, "wait_task"):
                client.wait_task(res["taskid"])
            self.done.emit({
                "ok": errno in (0, None),
                "error": res.get("message", "") if errno not in (0, None) else "",
                "count": len(self.paths),
            })
        except Exception as e:  # noqa: BLE001
            self.done.emit({"ok": False, "error": str(e)})


class AdCleanPage(QWidget):
    def __init__(self):
        super().__init__()
        self._workers = []
        self._matched = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(TwoColumn(self._build_form(), self._build_right(), left_width=440))
        self.refresh_accounts()

    def _build_form(self) -> QWidget:
        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setContentsMargins(24, 20, 10, 20)
        lay.setSpacing(12)
        lay.addWidget(PageHeader("广告清理", "设置自动同步遇到广告怎么处理；也可手动扫描文件夹删除广告"))

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(12)

        # 输入停顿 0.6 秒就自动保存：以前必须点「保存」或「扫描」才生效，
        # 填完关键词直接去同步 = 用的还是旧关键词（这就是「自定义广告词没生效」）
        self._kw_timer = QTimer(self)
        self._kw_timer.setSingleShot(True)
        self._kw_timer.setInterval(600)
        self._kw_timer.timeout.connect(self._persist_keywords)

        # ---- 卡片 1（最上面）：自动同步遇到广告怎么处理 + 广告词 ----
        form = card()
        fl = QVBoxLayout(form)
        fl.setContentsMargins(18, 16, 18, 18)
        fl.setSpacing(14)

        self.action = ComboBox()
        self.action.addItem("改名：按下面的广告词规则改掉广告名字", adfilter.ACTION_REPLACE)
        self.action.addItem("跳过：不转存（网盘里已有的会被删除）", adfilter.ACTION_SKIP)
        cur = db.get_setting("ad_action", adfilter.ACTION_SKIP)
        if cur == adfilter.ACTION_RENAME:      # 3.0.5 的「整个改名」并入改名模式
            cur = adfilter.ACTION_REPLACE
        self.action.setCurrentIndex(max(0, self.action.findData(cur)))
        fl.addWidget(field_group("命中广告后（自动同步）", self.action,
                                 "改设置后，下一次同步会把网盘里已有的广告文件/文件夹按新规则处理。"
                                 "仅对分享链接任务生效，好友 / 群任务仍按跳过处理。"))

        self.action_text = QLineEdit(db.get_setting("ad_action_text", ""))
        self.action_text.setPlaceholderText("如：资料（不填 = 只删掉命中的广告词）")
        self.fallback_group = field_group(
            "兜底名字", self.action_text,
            "广告词没写「=替换内容」时，命中后整个名字改成它（文件保留扩展名，重名自动加 (2)）。",
        )
        fl.addWidget(self.fallback_group)

        self.kw_input = QPlainTextEdit()
        self.kw_input.setPlainText(db.get_setting("ad_keywords", DEFAULT_AD_KEYWORDS))
        self.kw_input.setFixedHeight(130)
        fl.addWidget(field_group(
            "广告关键词", self.kw_input,
            "一行一个。写成「广告词=替换内容」只换掉这几个字（如 家瘦猴=资料；「家瘦猴=」表示删掉）；"
            "只写广告词就走上面的兜底名字。手动扫描清理也用这份词表。",
        ))

        self.wl_input = QPlainTextEdit()
        self.wl_input.setPlainText(db.get_setting("ad_whitelist", ""))
        self.wl_input.setFixedHeight(64)
        self.wl_input.setPlaceholderText("如：我的公众号名、你的推广品牌…")
        fl.addWidget(field_group("白名单关键词", self.wl_input,
                                 "命中白名单的文件绝不处理，用来保护你自己插入的广告。"))

        kwrow = QHBoxLayout()
        self.save_state = hint("")
        kwrow.addWidget(self.save_state, 1)
        save_kw = button("保存", "Ghost", "check")
        save_kw.clicked.connect(self.save_keywords)
        kwrow.addWidget(save_kw)
        fl.addLayout(kwrow)

        self.kw_input.textChanged.connect(self._kw_timer.start)
        self.wl_input.textChanged.connect(self._kw_timer.start)
        self.action_text.textChanged.connect(self._kw_timer.start)
        self.action.currentIndexChanged.connect(self._on_action_changed)
        self._on_action_changed(persist=False)
        self._show_save_state(saved=db.get_setting("ad_keywords", None) is not None)
        bl.addWidget(form)

        # ---- 卡片 2：手动扫描清理 ----
        scan_card = card()
        sl = QVBoxLayout(scan_card)
        sl.setContentsMargins(18, 16, 18, 18)
        sl.setSpacing(14)
        sl.addWidget(label("手动扫描清理", "SectionTitle"))

        self.account = ComboBox()
        sl.addWidget(field_group("账号", self.account))

        self.folder_edit = QLineEdit("/")
        pick = square_button("folder", "浏览网盘选择文件夹")
        pick.clicked.connect(self.pick_folder)
        sl.addWidget(field_group("要清理的文件夹", input_with_button(self.folder_edit, pick)))

        self.recursive = QCheckBox("包括子文件夹（递归扫描，最多 1000 个目录）")
        self.recursive.setChecked(True)
        sl.addWidget(self.recursive)
        bl.addWidget(scan_card)
        bl.addStretch()
        lay.addWidget(scroll_wrap(body), 1)

        self.scan_btn = button("扫描广告文件", "PrimaryLarge", "search")
        self.scan_btn.clicked.connect(self.scan)
        lay.addWidget(self.scan_btn)
        return left

    def _build_right(self) -> QWidget:
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self._build_result_page())
        self.right_stack.addWidget(self._build_folder_page())
        return self.right_stack

    def _build_result_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(10, 20, 24, 20)
        rl.setSpacing(12)
        self.header = PageHeader("命中的广告文件", "先选文件夹，点「扫描广告文件」")
        rl.addWidget(self.header)

        self.result_stack = QStackedWidget()
        self.empty = EmptyState("eraser", "还没有扫描", "扫描结果会列在这里，默认全选，取消勾选可保留")
        self.result_stack.addWidget(self.empty)

        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(8)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["文件 / 文件夹", "大小", "所在目录"])
        setup_table(self.table, row_height=38)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 90)
        cl.addWidget(self.table, 1)
        foot = QHBoxLayout()
        foot.setSpacing(8)
        sel = button("全选", "Ghost")
        sel.clicked.connect(lambda: self._check_all(True))
        clr = button("全不选", "Ghost")
        clr.clicked.connect(lambda: self._check_all(False))
        foot.addWidget(sel)
        foot.addWidget(clr)
        self.status = label("", "Hint")
        foot.addWidget(self.status, 1)
        self.del_btn = button("删除选中", "Danger", "trash")
        self.del_btn.clicked.connect(self.delete_selected)
        foot.addWidget(self.del_btn)
        cl.addLayout(foot)
        self.result_stack.addWidget(c)
        rl.addWidget(self.result_stack, 1)
        return page

    def _build_folder_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(10, 20, 24, 20)
        rl.setSpacing(12)
        head = PageHeader("选择文件夹", "双击进入文件夹，选好后点「使用此文件夹」")
        close = icon_button("x", theme.TEXT_2, "返回")
        close.clicked.connect(lambda: self.right_stack.setCurrentIndex(0))
        head.add_action(close)
        rl.addWidget(head)
        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(10)
        self.browser = NetdiskBrowser()
        cl.addWidget(self.browser, 1)
        row = QHBoxLayout()
        row.addStretch()
        use = button("使用此文件夹", "Primary", "check")
        use.clicked.connect(self._use_folder)
        row.addWidget(use)
        cl.addLayout(row)
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

    def _persist_keywords(self):
        db.set_setting("ad_keywords", self.kw_input.toPlainText().strip())
        db.set_setting("ad_whitelist", self.wl_input.toPlainText().strip())
        db.set_setting("ad_action", self.action.currentData())
        db.set_setting("ad_action_text", self.action_text.text().strip())
        self._show_save_state(saved=True)

    def _on_action_changed(self, *_a, persist: bool = True):
        self.fallback_group.setVisible(self.action.currentData() != adfilter.ACTION_SKIP)
        if persist:
            self._kw_timer.start()

    def _show_save_state(self, saved: bool):
        n = len(parse_keywords(self.kw_input.toPlainText()))
        if saved:
            self.save_state.setText(f"已自动保存：{n} 个关键词，自动同步立即按此生效")
        else:
            self.save_state.setText("当前显示的是默认词表（还没保存过）。改动任意内容会自动保存")

    def hideEvent(self, e):
        # 切走页面时把还没来得及自动保存的内容落盘
        if self._kw_timer.isActive():
            self._kw_timer.stop()
            self._persist_keywords()
        super().hideEvent(e)

    def save_keywords(self):
        self._persist_keywords()
        QMessageBox.information(self, "已保存", "广告关键词与白名单已更新，自动同步的去广告也会使用。")

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
        self.header.set_subtitle("扫描中…")
        w = ScanWorker(acc_id, self.folder_edit.text().strip() or "/", kws, self.recursive.isChecked(), wl)
        w.progress.connect(self.header.set_subtitle)
        w.done.connect(self._on_scanned)
        w.error.connect(self._on_scan_error)
        w.finished.connect(lambda x=w: self._drop(x))
        self._workers.append(w)
        w.start()

    def _on_scanned(self, matched: list):
        self.scan_btn.setEnabled(True)
        self._matched = matched
        self.table.setRowCount(0)
        self.table.setRowCount(len(matched))
        folder_icon = make_icon("folder", "#F0A93B", 16)
        file_icon = make_icon("file", theme.MUTED_2, 16)
        for r, f in enumerate(matched):
            it = QTableWidgetItem(f["name"])
            it.setIcon(folder_icon if f.get("isdir") else file_icon)
            it.setToolTip(f["name"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, f)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem("文件夹" if f.get("isdir") else fmt_size(f.get("size", 0))))
            d = QTableWidgetItem(display_path(f.get("dir", "")))
            d.setToolTip(display_path(f.get("dir", "")))
            self.table.setItem(r, 2, d)
        self.result_stack.setCurrentIndex(1)
        self.header.set_subtitle(f"命中 {len(matched)} 个广告文件 / 文件夹")
        self.status.setText("默认全选，取消勾选可保留" if matched else "")
        if not matched:
            QMessageBox.information(self, "扫描完成", "没有命中广告关键词的文件或文件夹。")

    def _on_scan_error(self, msg: str):
        self.scan_btn.setEnabled(True)
        self.header.set_subtitle(f"扫描失败：{msg}")
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
        if QMessageBox.question(self, "确认删除", f"将删除选中的 {len(paths)} 项（进入网盘回收站），确定？") != QMessageBox.Yes:
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
            db.add_log("info", f"广告清理：已删除 {result.get('count', 0)} 项")
            QMessageBox.information(self, "完成", f"已删除 {result.get('count', 0)} 项。")
            self.scan()
        else:
            self.status.setText("")
            QMessageBox.warning(self, "删除失败", result.get("error") or "未知错误")

    def _drop(self, w):
        if w in self._workers:
            self._workers.remove(w)
