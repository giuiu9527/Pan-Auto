"""批量重命名页：选账号 + 文件夹 + 关键字规则 → 预览 / 执行。"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QStackedWidget,
)
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor

from app import db
from app import theme
from app.core import batch_rename
from app.core.rename import apply_rules
from app.netdisk import account_display_name
from app.ui.netdisk_browser import NetdiskBrowser
from app.ui.rule_editor import RuleEditor
from app.ui.widgets import (
    ComboBox,
    card, field_group, field_label, hint, button, square_button, icon_button,
    input_with_button, PageHeader, TwoColumn, scroll_wrap, setup_table, table_frame,
    pill_cell, EmptyState,
)


class RenameWorker(QThread):
    done = Signal(dict)

    def __init__(self, account_id, folder, rules, inc_dirs, inc_files):
        super().__init__()
        self.args = (account_id, folder, rules, inc_dirs, inc_files)

    def run(self):
        self.done.emit(batch_rename.run_rename(*self.args))


class ListWorker(QThread):
    done = Signal(list)
    error = Signal(str)

    def __init__(self, account_id, folder):
        super().__init__()
        self.account_id = account_id
        self.folder = folder

    def run(self):
        try:
            self.done.emit(batch_rename.list_folder(self.account_id, self.folder))
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class BatchRenamePage(QWidget):
    def __init__(self):
        super().__init__()
        self._workers = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(TwoColumn(self._build_form(), self._build_right(), left_width=470,
                                  left_min=420, left_max=600))
        self.refresh_accounts()

    def _build_form(self) -> QWidget:
        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setContentsMargins(24, 20, 10, 20)
        lay.setSpacing(12)
        lay.addWidget(PageHeader("批量重命名", "按关键字规则给文件夹里的文件 / 子文件夹改名"))

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(12)

        form = card()
        fl = QVBoxLayout(form)
        fl.setContentsMargins(18, 16, 18, 18)
        fl.setSpacing(14)

        self.account = ComboBox()
        fl.addWidget(field_group("账号", self.account))

        self.folder = QLineEdit("/")
        pick = square_button("folder", "浏览网盘选择文件夹")
        pick.clicked.connect(self.pick_folder)
        fl.addWidget(field_group("目标文件夹", input_with_button(self.folder, pick)))

        opt = QHBoxLayout()
        opt.setSpacing(16)
        self.inc_dirs = QCheckBox("包括文件夹")
        self.inc_dirs.setChecked(True)
        self.inc_files = QCheckBox("包括文件")
        self.inc_files.setChecked(True)
        opt.addWidget(self.inc_dirs)
        opt.addWidget(self.inc_files)
        opt.addStretch()
        fl.addLayout(opt)

        fl.addWidget(field_label("重命名规则"))
        fl.addWidget(hint("这里保存的规则也会被「自动同步」勾选了自动重命名的任务套用。"))
        self.rule_editor = RuleEditor()
        self.rule_editor.set_rules(db.list_rules(None))
        fl.addWidget(self.rule_editor)
        bl.addWidget(form)
        bl.addStretch()
        lay.addWidget(scroll_wrap(body), 1)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        preview = button("预览效果", "Ghost", "eye")
        preview.clicked.connect(self.preview)
        btns.addWidget(preview)
        btns.addStretch()
        self.run_btn = button("执行重命名", "PrimaryLarge", "check")
        self.run_btn.clicked.connect(self.execute)
        btns.addWidget(self.run_btn)
        lay.addLayout(btns)
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
        self.header = PageHeader("预览 / 结果", "先选文件夹，点「预览效果」查看改名结果")
        rl.addWidget(self.header)

        self.result_stack = QStackedWidget()
        self.empty = EmptyState("edit", "还没有预览", "在左侧选好文件夹和规则后点「预览效果」")
        self.result_stack.addWidget(self.empty)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["原名", "新名", "状态"])
        setup_table(self.table, row_height=38)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 90)
        self.result_stack.addWidget(table_frame(self.table))
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

    # ---- 文件夹选择 ----
    def pick_folder(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先在「设置」添加并选择账号")
            return
        self.right_stack.setCurrentIndex(1)
        self.browser.account_id = acc_id
        self.browser.load(self.folder.text().strip() or "/")

    def _use_folder(self):
        self.folder.setText(self.browser.current_dir())
        self.right_stack.setCurrentIndex(0)

    # ---- 预览 ----
    def preview(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先选择账号")
            return
        db.replace_rules(None, self.rule_editor.get_rules())
        self.right_stack.setCurrentIndex(0)
        self.header.set_subtitle("加载中…")
        w = ListWorker(acc_id, self.folder.text().strip() or "/")
        w.done.connect(self._fill_preview)
        w.error.connect(lambda m: self.header.set_subtitle(f"加载失败：{m}"))
        w.finished.connect(lambda x=w: self._workers.remove(x) if x in self._workers else None)
        self._workers.append(w)
        w.start()

    def _fill_preview(self, items: list):
        rules = self.rule_editor.get_rules()
        self.table.setRowCount(0)
        changed = 0
        for it in items:
            isdir = bool(it.get("isdir"))
            if isdir and not self.inc_dirs.isChecked():
                continue
            if not isdir and not self.inc_files.isChecked():
                continue
            old = it["server_filename"]
            new = apply_rules(old, rules)
            r = self.table.rowCount()
            self.table.insertRow(r)
            o = QTableWidgetItem(old)
            o.setToolTip(old)
            self.table.setItem(r, 0, o)
            n = QTableWidgetItem(new)
            n.setToolTip(new)
            if new != old:
                changed += 1
                n.setForeground(QColor(theme.PRIMARY))
                self.table.setCellWidget(r, 2, pill_cell("将改名", "info"))
            else:
                n.setForeground(QColor(theme.MUTED))
                self.table.setCellWidget(r, 2, pill_cell("不变", "muted"))
        self.result_stack.setCurrentIndex(1)
        self.header.set_subtitle(f"共 {self.table.rowCount()} 项，其中 {changed} 项将改名")

    # ---- 执行 ----
    def execute(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先选择账号")
            return
        rules = self.rule_editor.get_rules()
        if not rules:
            QMessageBox.warning(self, "提示", "请先添加至少一条重命名规则")
            return
        db.replace_rules(None, rules)
        if QMessageBox.question(self, "确认", "将对该文件夹内符合规则的项执行重命名，确定？") != QMessageBox.Yes:
            return
        self.run_btn.setEnabled(False)
        w = RenameWorker(acc_id, self.folder.text().strip() or "/", rules,
                         self.inc_dirs.isChecked(), self.inc_files.isChecked())
        w.done.connect(self._on_done)
        w.finished.connect(lambda x=w: self._workers.remove(x) if x in self._workers else None)
        self._workers.append(w)
        w.start()
        self.header.set_subtitle("重命名执行中，详情见「运行记录」…")

    def _on_done(self, result: dict):
        self.run_btn.setEnabled(True)
        msg = f"成功改名 {result['renamed']} / 共 {result['total']} 项"
        if result.get("error"):
            QMessageBox.warning(self, "完成（含错误）", msg + f"\n{result['error']}")
        else:
            QMessageBox.information(self, "完成", msg)
        self.preview()
