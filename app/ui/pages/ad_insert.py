"""广告插入页：选择网盘广告文件，扫描目标文件夹并复制插入。"""
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
from PySide6.QtGui import QColor

from app import db
from app.baidu.client import get_client_for_account
from app.ui.icons import make_icon, make_pixmap
from app.ui.netdisk_browser import NetdiskBrowser
from app.ui.widgets import card, field_group, field_label, label, hline_spacer


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
            time.sleep(0.25)
        self.done.emit({"ok": ok, "failed": failed, "error": "; ".join(errors[:3])})


class PickRow(QFrame):
    def __init__(self, icon: str, text: str, button_tip: str, on_click):
        super().__init__()
        self.setObjectName("PickRow")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 10, 8)
        lay.setSpacing(9)

        self.icon = QLabel()
        self.icon.setPixmap(make_pixmap(icon, "#6b7a90", 18))
        lay.addWidget(self.icon)

        self.text = QLabel(text)
        self.text.setObjectName("PickText")
        lay.addWidget(self.text, 1)

        self.badge = QLabel("0")
        self.badge.setObjectName("MemberBadge")
        lay.addWidget(self.badge)

        self.btn = QPushButton()
        self.btn.setObjectName("IconBtn")
        self.btn.setIcon(make_icon("search", "#2f6bff", 17))
        self.btn.setIconSize(QSize(17, 17))
        self.btn.setFixedSize(34, 30)
        self.btn.setToolTip(button_tip)
        self.btn.clicked.connect(on_click)
        lay.addWidget(self.btn)

    def set_value(self, text: str, count: int):
        self.text.setText(text)
        self.badge.setText(str(count))


class AdInsertPage(QWidget):
    def __init__(self):
        super().__init__()
        self.mode = "random"
        self.ad_files: list[dict] = []
        self.target_dir = "/"
        self.targets: list[str] = []
        self._workers = []

        columns = QHBoxLayout(self)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(0)

        left = QWidget()
        left.setFixedWidth(438)
        columns.addWidget(left)
        root = QVBoxLayout(left)
        root.setContentsMargins(22, 14, 16, 16)
        root.setSpacing(11)

        title_row = QHBoxLayout()
        title = QLabel("广告插入")
        title.setObjectName("PageTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        help_btn = QPushButton("教程")
        help_btn.setObjectName("Ghost")
        help_btn.setIcon(make_icon("check", "#2f6bff", 15))
        help_btn.clicked.connect(self._show_help)
        title_row.addWidget(help_btn)
        root.addLayout(title_row)

        form = card()
        fl = QVBoxLayout(form)
        fl.setContentsMargins(18, 16, 18, 16)
        fl.setSpacing(12)

        self.account = QComboBox()
        fl.addWidget(field_group("执行账号 *", self.account))

        mode_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.random_btn = QPushButton("随机插入")
        self.random_btn.setObjectName("Tab")
        self.random_btn.setCheckable(True)
        self.random_btn.setChecked(True)
        self.random_btn.setIcon(make_icon("shuffle", "#ffffff", 15))
        self.target_btn = QPushButton("指定插入")
        self.target_btn.setObjectName("Tab")
        self.target_btn.setCheckable(True)
        self.target_btn.setIcon(make_icon("target", "#5b6473", 15))
        self.mode_group.addButton(self.random_btn)
        self.mode_group.addButton(self.target_btn)
        self.mode_group.setExclusive(True)
        self.random_btn.clicked.connect(lambda: self._set_mode("random"))
        self.target_btn.clicked.connect(lambda: self._set_mode("fixed"))
        mode_row.addWidget(self.random_btn)
        mode_row.addWidget(self.target_btn)
        fl.addLayout(mode_row)

        fl.addWidget(field_label("广告文件 *"))
        self.ad_row = PickRow("file", "点击选择广告文件", "选择网盘里的广告文件", self.pick_ad_files)
        fl.addWidget(self.ad_row)

        fl.addWidget(hline_spacer())

        fl.addWidget(field_label("目标文件夹 *"))
        self.target_row = PickRow("folder", "点击选择目标文件夹", "选择要扫描的网盘文件夹", self.pick_target_folder)
        fl.addWidget(self.target_row)

        hint = label("随机插入：每个目标文件夹随机复制 1 个广告文件；指定插入：复制全部已选广告文件。", "Muted")
        hint.setWordWrap(True)
        fl.addWidget(hint)
        root.addWidget(form, 1)

        self.scan_btn = QPushButton("  扫描文件夹")
        self.scan_btn.setObjectName("Primary")
        self.scan_btn.setIcon(make_icon("search", "#ffffff", 16))
        self.scan_btn.clicked.connect(self.scan_folders)
        root.addWidget(self.scan_btn)

        self.right_stack = QStackedWidget()
        columns.addWidget(self.right_stack, 1)
        self.right_stack.addWidget(self._build_task_page())
        self.right_stack.addWidget(self._build_ad_picker())
        self.right_stack.addWidget(self._build_folder_picker())

        self.refresh_accounts()
        self._show_empty()

    def _build_task_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(6, 14, 20, 16)
        rl.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("插入任务")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        head.addStretch()
        clear = QPushButton("清空")
        clear.setObjectName("Ghost")
        clear.clicked.connect(self.clear_targets)
        head.addWidget(clear)
        self.insert_btn = QPushButton("  开始插入")
        self.insert_btn.setObjectName("Primary")
        self.insert_btn.setIcon(make_icon("play", "#ffffff", 16))
        self.insert_btn.clicked.connect(self.start_insert)
        head.addWidget(self.insert_btn)
        rl.addLayout(head)

        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(6, 6, 6, 6)
        self.result_stack = QStackedWidget()
        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.addStretch()
        icon = QLabel()
        icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(make_pixmap("inbox", "#b7c1d1", 58))
        el.addWidget(icon)
        txt = QLabel("暂无插入任务")
        txt.setObjectName("Muted")
        txt.setAlignment(Qt.AlignCenter)
        txt.setStyleSheet("font-size:15px; font-weight:600;")
        el.addWidget(txt)
        el.addStretch()
        self.result_stack.addWidget(self.empty)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["目标文件夹", "广告文件", "状态"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.result_stack.addWidget(self.table)

        cl.addWidget(self.result_stack)
        rl.addWidget(c, 1)

        self.summary = QLabel("")
        self.summary.setObjectName("Muted")
        rl.addWidget(self.summary)
        return page

    def _build_ad_picker(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(6, 14, 20, 16)
        rl.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel("选择广告文件")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        head.addStretch()
        close = QPushButton("×")
        close.setObjectName("IconBtn")
        close.setFixedSize(30, 28)
        close.clicked.connect(lambda: self.right_stack.setCurrentIndex(0))
        head.addWidget(close)
        rl.addLayout(head)

        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(8)
        self.ad_browser = NetdiskBrowser()
        cl.addWidget(self.ad_browser, 1)
        use = QPushButton("  使用选中文件")
        use.setObjectName("Primary")
        use.setIcon(make_icon("check", "#ffffff", 16))
        use.clicked.connect(self._use_ad_files)
        cl.addWidget(use)
        rl.addWidget(c, 1)
        return page

    def _build_folder_picker(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(6, 14, 20, 16)
        rl.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel("选择目标文件夹")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        head.addStretch()
        close = QPushButton("×")
        close.setObjectName("IconBtn")
        close.setFixedSize(30, 28)
        close.clicked.connect(lambda: self.right_stack.setCurrentIndex(0))
        head.addWidget(close)
        rl.addLayout(head)

        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(8)
        self.folder_browser = NetdiskBrowser()
        cl.addWidget(self.folder_browser, 1)
        use = QPushButton("  使用此文件夹")
        use.setObjectName("Primary")
        use.setIcon(make_icon("check", "#ffffff", 16))
        use.clicked.connect(self._use_target_folder)
        cl.addWidget(use)
        rl.addWidget(c, 1)
        return page

    def on_shown(self):
        self.refresh_accounts()

    def refresh_accounts(self):
        prev = self.account.currentData()
        self.account.blockSignals(True)
        self.account.clear()
        for acc in db.list_accounts():
            self.account.addItem(acc["username"] or "百度用户", acc["id"])
        idx = self.account.findData(prev)
        if idx >= 0:
            self.account.setCurrentIndex(idx)
        self.account.blockSignals(False)

    def _set_mode(self, mode: str):
        self.mode = mode
        self.random_btn.setIcon(make_icon("shuffle", "#ffffff" if mode == "random" else "#5b6473", 15))
        self.target_btn.setIcon(make_icon("target", "#ffffff" if mode == "fixed" else "#5b6473", 15))
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
            QMessageBox.warning(self, "提示", "请至少选中一个广告文件")
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
        self.target_row.set_value(self.target_dir, 1)
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
        self.scan_btn.setText("  扫描中")
        self.summary.setText("正在扫描目标文件夹...")
        worker = ScanWorker(self.account.currentData(), self.target_dir)
        worker.done.connect(self._on_scan_done)
        worker.error.connect(self._on_scan_error)
        worker.finished.connect(lambda w=worker: self._workers.remove(w))
        self._workers.append(worker)
        worker.start()

    def _on_scan_done(self, folders: list[str]):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("  扫描文件夹")
        self.targets = folders
        self.table.setRowCount(0)
        for folder in folders:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(folder))
            self.table.setItem(row, 1, QTableWidgetItem(self._ad_desc()))
            status = QTableWidgetItem("待插入")
            status.setForeground(QColor("#8b95a7"))
            self.table.setItem(row, 2, status)
        self._show_table()
        self.summary.setText(f"已扫描 {len(folders)} 个目标文件夹")
        db.add_log("info", f"广告插入扫描：{self.target_dir}，目标 {len(folders)} 个")

    def _on_scan_error(self, msg: str):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("  扫描文件夹")
        self.summary.setText(f"扫描失败：{msg}")
        QMessageBox.warning(self, "扫描失败", msg)

    def start_insert(self):
        if not self.targets:
            QMessageBox.warning(self, "提示", "请先扫描目标文件夹")
            return
        paths = [x.get("path", "") for x in self.ad_files if x.get("path")]
        if not paths:
            QMessageBox.warning(self, "提示", "广告文件路径无效，请重新选择")
            return
        self.insert_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.summary.setText("正在插入广告文件...")
        worker = InsertWorker(self.account.currentData(), paths, self.targets, self.mode)
        worker.progress.connect(self._on_insert_progress)
        worker.done.connect(self._on_insert_done)
        worker.finished.connect(lambda w=worker: self._workers.remove(w))
        self._workers.append(worker)
        worker.start()

    def _on_insert_progress(self, row: int, status: str):
        item = QTableWidgetItem(status)
        item.setForeground(QColor("#16a34a") if status.startswith("已") else QColor("#dc2626"))
        self.table.setItem(row, 2, item)

    def _on_insert_done(self, result: dict):
        self.insert_btn.setEnabled(True)
        self.scan_btn.setEnabled(True)
        msg = f"完成：成功 {result['ok']} 个目标，失败 {result['failed']} 个"
        self.summary.setText(msg)
        db.add_log("info", f"广告插入{msg}")
        if result.get("failed"):
            QMessageBox.warning(self, "插入完成（含失败）", msg + ("\n" + result.get("error", "") if result.get("error") else ""))
        else:
            QMessageBox.information(self, "插入完成", msg)

    def clear_targets(self):
        self.targets = []
        self.table.setRowCount(0)
        self.summary.setText("")
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
        self.result_stack.setCurrentWidget(self.empty)
        self.insert_btn.setEnabled(False)

    def _show_table(self):
        self.result_stack.setCurrentWidget(self.table)
        self.insert_btn.setEnabled(True)

    def _show_help(self):
        QMessageBox.information(
            self,
            "广告插入说明",
            "先选择一个或多个网盘广告文件，再选择目标文件夹。\n"
            "扫描后会把目标文件夹及其下一级子文件夹列为插入目标。\n"
            "随机插入会给每个目标随机复制 1 个广告文件，指定插入会复制全部广告文件。",
        )


def _join(parent: str, name: str) -> str:
    if parent.endswith("/"):
        return parent + name
    return parent + "/" + name
