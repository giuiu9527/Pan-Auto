"""广告插入页：选择网盘广告文件，扫描目标文件夹并复制插入（仅百度）。"""
import random
import time

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QFrame,
    QButtonGroup,
)
from PySide6.QtCore import Qt, QThread, Signal, QSize

from app import db
from app import theme
from app.baidu.client import get_client_for_account
from app.ui.icons import make_icon, make_pixmap
from app.ui.netdisk_browser import NetdiskBrowser
from app.ui.widgets import (
    card, field_group, field_label, hint, button, icon_button, PageHeader, TwoColumn,
    scroll_wrap, setup_table, table_frame, pill_cell, EmptyState, ElidedLabel, InfoBox,
)


class ScanWorker(QThread):
    done = Signal(list)
    error = Signal(str)

    def __init__(self, account_id, target_dir: str):
        super().__init__()
        self.account_id = account_id
        self.target_dir = target_dir or "/"

    def run(self):
        client = get_client_for_account(self.account_id)
        if client is None:
            self.error.emit("账号不可用，请先在「设置」登录百度网盘")
            return
        try:
            folders = [self.target_dir]
            for item in client.list_dir(self.target_dir):
                if item.get("isdir"):
                    folders.append(item.get("path") or _join(self.target_dir, item["server_filename"]))
            self.done.emit(folders)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class InsertWorker(QThread):
    progress = Signal(int, str)
    done = Signal(dict)

    def __init__(self, account_id, ad_paths: list[str], target_dirs: list[str], mode: str):
        super().__init__()
        self.account_id = account_id
        self.ad_paths = ad_paths
        self.target_dirs = target_dirs
        self.mode = mode

    def run(self):
        client = get_client_for_account(self.account_id)
        if client is None:
            self.done.emit({"ok": 0, "failed": len(self.target_dirs), "error": "账号不可用"})
            return
        ok = 0
        failed = 0
        errors = []
        for row, folder in enumerate(self.target_dirs):
            files = self.ad_paths
            if self.mode == "random" and len(files) > 1:
                files = [random.choice(files)]
            try:
                res = client.copy_files(files, folder)
                errno = res.get("errno")
                if errno not in (0, None):
                    failed += 1
                    msg = f"失败 errno={errno}"
                    errors.append(f"{folder}: {msg}")
                    self.progress.emit(row, msg)
                else:
                    ok += 1
                    self.progress.emit(row, f"已插入 {len(files)} 个文件")
            except Exception as e:  # noqa: BLE001
                failed += 1
                errors.append(f"{folder}: {e}")
                self.progress.emit(row, f"失败：{e}")
            time.sleep(0.4)
        self.done.emit({"ok": ok, "failed": failed, "error": "; ".join(errors[:3])})


class PickRow(QFrame):
    """整行可点的选择行：图标 + 文本 + 数量徽标。"""

    def __init__(self, icon: str, text: str, tip: str, on_click):
        super().__init__()
        self.setObjectName("PickRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(50)
        self.setToolTip(tip)
        self._on_click = on_click
        self._placeholder = text
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.icon.setPixmap(make_pixmap(icon, theme.MUTED, 18))
        lay.addWidget(self.icon)
        self.text = ElidedLabel(text, "PickText", mode=Qt.ElideMiddle)
        lay.addWidget(self.text, 1)
        self.badge = QLabel("0")
        self.badge.setObjectName("CountBadge")
        self.badge.hide()
        lay.addWidget(self.badge)
        arrow = QLabel()
        arrow.setPixmap(make_pixmap("chevron-right", theme.MUTED_2, 16))
        lay.addWidget(arrow)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._on_click()

    def set_value(self, text: str, count: int):
        self.text.setText(text or self._placeholder)
        if count > 0:
            self.badge.setText(str(count))
            self.badge.show()
        else:
            self.badge.hide()


class AdInsertPage(QWidget):
    def __init__(self):
        super().__init__()
        self.mode = "random"
        self.ad_files: list[dict] = []
        self.target_dir = "/"
        self.targets: list[str] = []
        self._workers = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(TwoColumn(self._build_form(), self._build_right(), left_width=440))
        self.refresh_accounts()
        self._show_empty()

    def _build_form(self) -> QWidget:
        left = QWidget()
        root = QVBoxLayout(left)
        root.setContentsMargins(24, 20, 10, 20)
        root.setSpacing(12)
        root.addWidget(PageHeader("广告插入", "把自己的广告文件复制到目标文件夹及其子文件夹（仅百度）"))

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(12)

        form = card()
        fl = QVBoxLayout(form)
        fl.setContentsMargins(18, 16, 18, 18)
        fl.setSpacing(14)

        self.account = QComboBox()
        fl.addWidget(field_group("执行账号", self.account))

        fl.addWidget(field_label("插入方式"))
        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        self.mode_group = QButtonGroup(self)
        self.random_btn = QPushButton("  随机插入")
        self.random_btn.setObjectName("ModeTab")
        self.random_btn.setCheckable(True)
        self.random_btn.setChecked(True)
        self.random_btn.setCursor(Qt.PointingHandCursor)
        self.random_btn.setIconSize(QSize(16, 16))
        self.target_btn = QPushButton("  全部插入")
        self.target_btn.setObjectName("ModeTab")
        self.target_btn.setCheckable(True)
        self.target_btn.setCursor(Qt.PointingHandCursor)
        self.target_btn.setIconSize(QSize(16, 16))
        self.mode_group.addButton(self.random_btn)
        self.mode_group.addButton(self.target_btn)
        self.mode_group.setExclusive(True)
        self.random_btn.clicked.connect(lambda: self._set_mode("random"))
        self.target_btn.clicked.connect(lambda: self._set_mode("fixed"))
        mode_row.addWidget(self.random_btn, 1)
        mode_row.addWidget(self.target_btn, 1)
        fl.addLayout(mode_row)
        fl.addWidget(hint("随机插入：每个目标文件夹随机放 1 个广告；全部插入：每个目标放全部已选广告。"))

        fl.addWidget(field_label("广告文件"))
        self.ad_row = PickRow("file", "点击选择广告文件（可多选）", "选择网盘里的广告文件", self.pick_ad_files)
        fl.addWidget(self.ad_row)

        fl.addWidget(field_label("目标文件夹"))
        self.target_row = PickRow("folder", "点击选择目标文件夹", "选择要扫描的网盘文件夹", self.pick_target_folder)
        fl.addWidget(self.target_row)
        fl.addWidget(hint("扫描后会把目标文件夹本身及其下一级子文件夹都列为插入目标。"))
        bl.addWidget(form)
        bl.addStretch()
        root.addWidget(scroll_wrap(body), 1)

        self.scan_btn = button("扫描目标文件夹", "PrimaryLarge", "search")
        self.scan_btn.clicked.connect(self.scan_folders)
        root.addWidget(self.scan_btn)
        self._set_mode("random")
        return left

    def _build_right(self) -> QWidget:
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self._build_task_page())
        self.right_stack.addWidget(self._build_picker("选择广告文件", "多选后点「使用选中文件」", "ad"))
        self.right_stack.addWidget(self._build_picker("选择目标文件夹", "双击进入文件夹，选好后点「使用此文件夹」", "folder"))
        return self.right_stack

    def _build_task_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(10, 20, 24, 20)
        rl.setSpacing(12)

        self.header = PageHeader("插入任务", "先在左侧选好广告文件和目标文件夹，再扫描")
        clear = button("清空", "Ghost", "trash")
        clear.clicked.connect(self.clear_targets)
        self.header.add_action(clear)
        self.insert_btn = button("开始插入", "Primary", "play")
        self.insert_btn.clicked.connect(self.start_insert)
        self.header.add_action(self.insert_btn)
        rl.addWidget(self.header)

        self.result_stack = QStackedWidget()
        self.empty = EmptyState("inbox", "暂无插入任务", "扫描目标文件夹后，这里会列出每个文件夹的插入进度")
        self.result_stack.addWidget(self.empty)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["目标文件夹", "广告文件", "状态"])
        setup_table(self.table, row_height=40)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 170)
        self.result_stack.addWidget(table_frame(self.table))
        rl.addWidget(self.result_stack, 1)
        return page

    def _build_picker(self, title: str, sub: str, kind: str) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(10, 20, 24, 20)
        rl.setSpacing(12)
        head = PageHeader(title, sub)
        close = icon_button("x", theme.TEXT_2, "返回")
        close.clicked.connect(lambda: self.right_stack.setCurrentIndex(0))
        head.add_action(close)
        rl.addWidget(head)
        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(10)
        browser = NetdiskBrowser()
        cl.addWidget(browser, 1)
        row = QHBoxLayout()
        row.addStretch()
        if kind == "ad":
            self.ad_browser = browser
            use = button("使用选中文件", "Primary", "check")
            use.clicked.connect(self._use_ad_files)
        else:
            self.folder_browser = browser
            use = button("使用此文件夹", "Primary", "check")
            use.clicked.connect(self._use_target_folder)
        row.addWidget(use)
        cl.addLayout(row)
        rl.addWidget(c, 1)
        return page

    def on_shown(self):
        self.refresh_accounts()

    def refresh_accounts(self):
        prev = self.account.currentData()
        self.account.blockSignals(True)
        self.account.clear()
        for acc in db.list_accounts("baidu"):
            self.account.addItem(acc["username"] or "百度用户", acc["id"])
        idx = self.account.findData(prev)
        if idx >= 0:
            self.account.setCurrentIndex(idx)
        self.account.blockSignals(False)

    def _set_mode(self, mode: str):
        self.mode = mode
        self.random_btn.setIcon(make_icon("shuffle", theme.PRIMARY if mode == "random" else theme.TEXT_2, 16))
        self.target_btn.setIcon(make_icon("target", theme.PRIMARY if mode == "fixed" else theme.TEXT_2, 16))
        self._refresh_table_descriptions()

    def pick_ad_files(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先在「设置」添加并选择账号")
            return
        self.right_stack.setCurrentIndex(1)
        self.ad_browser.account_id = acc_id
        self.ad_browser.load("/")

    def pick_target_folder(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先在「设置」添加并选择账号")
            return
        self.right_stack.setCurrentIndex(2)
        self.folder_browser.account_id = acc_id
        self.folder_browser.load(self.target_dir or "/")

    def _use_ad_files(self):
        files = self.ad_browser.selected_files()
        if not files:
            QMessageBox.warning(self, "提示", "请至少选中一个广告文件（按住 Ctrl 可多选）")
            return
        self.ad_files = files
        names = [x.get("server_filename", "") for x in files]
        text = "、".join(names[:2])
        if len(names) > 2:
            text += f" 等 {len(names)} 个"
        self.ad_row.set_value(text or "已选择广告文件", len(files))
        self.right_stack.setCurrentIndex(0)
        self._refresh_table_descriptions()

    def _use_target_folder(self):
        self.target_dir = self.folder_browser.current_dir()
        self.target_row.set_value(self.target_dir, 0)
        self.right_stack.setCurrentIndex(0)

    def scan_folders(self):
        if self.account.currentData() is None:
            QMessageBox.warning(self, "提示", "请先选择账号")
            return
        if not self.ad_files:
            QMessageBox.warning(self, "提示", "请先选择广告文件")
            return
        if not self.target_dir:
            QMessageBox.warning(self, "提示", "请先选择目标文件夹")
            return
        self.scan_btn.setEnabled(False)
        self.header.set_subtitle("正在扫描目标文件夹…")
        worker = ScanWorker(self.account.currentData(), self.target_dir)
        worker.done.connect(self._on_scan_done)
        worker.error.connect(self._on_scan_error)
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def _on_scan_done(self, folders: list[str]):
        self.scan_btn.setEnabled(True)
        self.targets = folders
        self.table.setRowCount(0)
        self.table.setRowCount(len(folders))
        for row, folder in enumerate(folders):
            it = QTableWidgetItem(folder)
            it.setToolTip(folder)
            self.table.setItem(row, 0, it)
            self.table.setItem(row, 1, QTableWidgetItem(self._ad_desc()))
            self.table.setCellWidget(row, 2, pill_cell("待插入", "muted"))
        self._show_table()
        self.header.set_subtitle(f"已扫描 {len(folders)} 个目标文件夹，点「开始插入」执行")
        db.add_log("info", f"广告插入扫描：{self.target_dir}，目标 {len(folders)} 个")

    def _on_scan_error(self, msg: str):
        self.scan_btn.setEnabled(True)
        self.header.set_subtitle(f"扫描失败：{msg}")
        QMessageBox.warning(self, "扫描失败", msg)

    def start_insert(self):
        if not self.targets:
            QMessageBox.warning(self, "提示", "请先扫描目标文件夹")
            return
        paths = [x.get("path", "") for x in self.ad_files if x.get("path")]
        if not paths:
            QMessageBox.warning(self, "提示", "广告文件路径无效，请重新选择")
            return
        if QMessageBox.question(self, "开始插入", f"将向 {len(self.targets)} 个文件夹复制广告文件，确定？") != QMessageBox.Yes:
            return
        self.insert_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.header.set_subtitle("正在插入广告文件…")
        worker = InsertWorker(self.account.currentData(), paths, self.targets, self.mode)
        worker.progress.connect(self._on_insert_progress)
        worker.done.connect(self._on_insert_done)
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def _on_insert_progress(self, row: int, status: str):
        ok = status.startswith("已")
        self.table.setCellWidget(row, 2, pill_cell(status, "success" if ok else "danger"))

    def _on_insert_done(self, result: dict):
        self.insert_btn.setEnabled(True)
        self.scan_btn.setEnabled(True)
        msg = f"完成：成功 {result['ok']} 个目标，失败 {result['failed']} 个"
        self.header.set_subtitle(msg)
        db.add_log("info", f"广告插入{msg}")
        if result.get("failed"):
            QMessageBox.warning(self, "插入完成（含失败）", msg + ("\n" + result.get("error", "") if result.get("error") else ""))
        else:
            QMessageBox.information(self, "插入完成", msg)

    def clear_targets(self):
        self.targets = []
        self.table.setRowCount(0)
        self.header.set_subtitle("先在左侧选好广告文件和目标文件夹，再扫描")
        self._show_empty()

    def _ad_desc(self) -> str:
        if self.mode == "random" and len(self.ad_files) > 1:
            return f"随机 1 / {len(self.ad_files)}"
        return f"{len(self.ad_files)} 个文件"

    def _refresh_table_descriptions(self):
        if not hasattr(self, "table"):
            return
        for row in range(self.table.rowCount()):
            self.table.setItem(row, 1, QTableWidgetItem(self._ad_desc()))

    def _show_empty(self):
        self.result_stack.setCurrentIndex(0)
        self.insert_btn.setEnabled(False)

    def _show_table(self):
        self.result_stack.setCurrentIndex(1)
        self.insert_btn.setEnabled(True)


def _join(parent: str, name: str) -> str:
    if parent.endswith("/"):
        return parent + name
    return parent + "/" + name
