"""批量重命名页（独立功能）：选账号 + 选文件夹 + 关键字规则 → 预览 / 执行。"""
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
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QStackedWidget,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor

from app.ui.widgets import card, field_label, field_group, label
from app.ui.icons import make_icon
from app.ui.rule_editor import RuleEditor
from app.ui.netdisk_browser import NetdiskBrowser
from app.core import batch_rename
from app.core.rename import apply_rules
from app import db


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

        title = QLabel("批量重命名")
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
        self.folder = QLineEdit("/")
        dr.addWidget(self.folder, 1)
        pick = QPushButton()
        pick.setObjectName("Ghost")
        pick.setIcon(make_icon("folder", "#4a5365", 16))
        pick.setFixedSize(42, 40)
        pick.setToolTip("浏览网盘选择文件夹")
        pick.clicked.connect(self.pick_folder)
        dr.addWidget(pick)
        fl.addWidget(field_group("选择文件夹 *", dir_widget))

        opt = QHBoxLayout()
        self.inc_dirs = QCheckBox("包括文件夹")
        self.inc_dirs.setChecked(True)
        self.inc_files = QCheckBox("包括文件")
        self.inc_files.setChecked(True)
        opt.addWidget(self.inc_dirs)
        opt.addWidget(self.inc_files)
        opt.addStretch()
        fl.addLayout(opt)

        fl.addWidget(field_label("重命名规则"))
        rl_hint = label("这里的规则也会被「自动转存」的自动重命名选项套用。", "Muted")
        fl.addWidget(rl_hint)
        self.rule_editor = RuleEditor()
        self.rule_editor.set_rules(db.list_rules(None))  # 载入已保存的全局规则
        fl.addWidget(self.rule_editor)
        root.addWidget(form)

        btns = QHBoxLayout()
        preview = QPushButton("预览效果")
        preview.setObjectName("Ghost")
        preview.clicked.connect(self.preview)
        btns.addWidget(preview)
        btns.addStretch()
        self.run_btn = QPushButton("  执行重命名")
        self.run_btn.setObjectName("Primary")
        self.run_btn.setIcon(make_icon("check", "#ffffff", 16))
        self.run_btn.clicked.connect(self.execute)
        btns.addWidget(self.run_btn)
        left_lay.addLayout(btns)

        # ===== 右：预览结果 / 目录选择 =====
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
        head = QLabel("预览 / 结果")
        head.setObjectName("PageTitle")
        rl.addWidget(head)
        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(6, 6, 6, 6)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["原名", "新名", "状态"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        cl.addWidget(self.table)
        rl.addWidget(c, 1)
        self.hint = QLabel("先选文件夹，点「预览效果」看改名结果。")
        self.hint.setObjectName("Muted")
        rl.addWidget(self.hint)
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
            self.account.addItem(acc["username"] or "百度用户", acc["id"])
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
        db.replace_rules(None, self.rule_editor.get_rules())  # 保存为全局规则
        self.right_stack.setCurrentIndex(0)
        self.hint.setText("加载中…")
        w = ListWorker(acc_id, self.folder.text().strip() or "/")
        w.done.connect(self._fill_preview)
        w.error.connect(lambda m: self.hint.setText(f"加载失败：{m}"))
        w.finished.connect(lambda x=w: self._workers.remove(x))
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
            self.table.setItem(r, 0, QTableWidgetItem(old))
            self.table.setItem(r, 1, QTableWidgetItem(new))
            if new != old:
                changed += 1
                st = QTableWidgetItem("将改名")
                st.setForeground(QColor("#2f6bff"))
            else:
                st = QTableWidgetItem("不变")
                st.setForeground(QColor("#8b95a7"))
            self.table.setItem(r, 2, st)
        self.hint.setText(f"共 {self.table.rowCount()} 项，其中 {changed} 项将改名")

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
        db.replace_rules(None, rules)  # 保存为全局规则，供自动转存套用
        if QMessageBox.question(
            self, "确认", "将对该文件夹内符合规则的项执行重命名，确定？"
        ) != QMessageBox.Yes:
            return
        w = RenameWorker(
            acc_id,
            self.folder.text().strip() or "/",
            rules,
            self.inc_dirs.isChecked(),
            self.inc_files.isChecked(),
        )
        w.done.connect(self._on_done)
        w.finished.connect(lambda x=w: self._workers.remove(x))
        self._workers.append(w)
        w.start()
        QMessageBox.information(self, "已开始", "重命名已在后台执行，详情见「转存记录」。")

    def _on_done(self, result: dict):
        msg = f"成功改名 {result['renamed']} / 共 {result['total']} 项"
        if result.get("error"):
            QMessageBox.warning(self, "完成（含错误）", msg + f"\n{result['error']}")
        else:
            QMessageBox.information(self, "完成", msg)
        self.preview()
