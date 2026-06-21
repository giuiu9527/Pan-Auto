"""自动转存页（仿 NeoPan）：左侧编辑任务表单 + 右侧任务列表面板（可编辑）。"""
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
    QFrame,
    QStackedWidget,
)
from PySide6.QtCore import Qt, QThread, Signal, QSize

from app.ui.widgets import card, field_label, field_group, label
from app.ui.icons import make_icon, make_pixmap
from app.ui.netdisk_browser import NetdiskBrowser
from app.core.transfer import run_task
from app import db

INTERVALS = [
    ("每 30 分钟同步一次", "30m"),
    ("每小时同步一次", "hourly"),
    ("每 6 小时同步一次", "6h"),
    ("每天同步一次", "daily"),
]


class TransferWorker(QThread):
    finished_task = Signal(dict)

    def __init__(self, task: dict):
        super().__init__()
        self.task = task

    def run(self):
        result = run_task(self.task)
        self.finished_task.emit(result)


def _icon_btn(icon_name: str, color: str, tip: str) -> QPushButton:
    b = QPushButton()
    b.setObjectName("IconBtn")
    b.setIcon(make_icon(icon_name, color, 19, width=2.3))
    b.setIconSize(QSize(19, 19))
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    b.setFixedSize(34, 30)
    return b


class AutoSyncPage(QWidget):
    def __init__(self):
        super().__init__()
        self.editing_id = None  # 正在编辑的任务 id；None 表示新建
        self._workers = []

        columns = QHBoxLayout(self)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(0)

        # ============ 左：编辑表单 ============
        left = QWidget()
        left.setFixedWidth(438)
        columns.addWidget(left)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(22, 14, 16, 16)
        left_lay.setSpacing(11)

        self.form_title = QLabel("新增同步任务")
        self.form_title.setObjectName("PageTitle")
        left_lay.addWidget(self.form_title)

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

        form_card = card()
        fl = QVBoxLayout(form_card)
        fl.setContentsMargins(18, 16, 18, 16)
        fl.setSpacing(12)

        self.account = QComboBox()
        fl.addWidget(field_group("转存到哪个账号 *", self.account))

        self.link = QLineEdit()
        self.link.setPlaceholderText("粘贴分享链接，提取码可直接写在链接里 ?pwd=xxxx")
        fl.addWidget(field_group("分享链接（含提取码）*", self.link))

        dir_widget = QWidget()
        dir_row = QHBoxLayout(dir_widget)
        dir_row.setContentsMargins(0, 0, 0, 0)
        dir_row.setSpacing(8)
        self.target = QLineEdit("/来自好友的分享")
        dir_row.addWidget(self.target, 1)
        pick = QPushButton()
        pick.setObjectName("Ghost")
        pick.setIcon(make_icon("folder", "#4a5365", 16))
        pick.setToolTip("浏览网盘选择文件夹")
        pick.setFixedSize(42, 40)
        pick.clicked.connect(self.pick_folder)
        dir_row.addWidget(pick)
        fl.addWidget(field_group("目标文件夹", dir_widget))

        self.rename_on = QCheckBox("转存后自动重命名（套用「批量重命名」页里的规则）")
        fl.addWidget(self.rename_on)

        self.interval = QComboBox()
        for name, key in INTERVALS:
            self.interval.addItem(name, key)
        self.interval.setCurrentIndex(3)
        fl.addWidget(field_group("定时同步间隔", self.interval))

        self.note = QLineEdit()
        self.note.setPlaceholderText("便于识别，如：BL讲义更新")
        fl.addWidget(field_group("任务备注（可选）", self.note))
        root.addWidget(form_card)

        btn_row = QHBoxLayout()
        self.cancel_edit_btn = QPushButton("取消编辑")
        self.cancel_edit_btn.setObjectName("Ghost")
        self.cancel_edit_btn.clicked.connect(self.reset_form)
        self.cancel_edit_btn.hide()
        btn_row.addWidget(self.cancel_edit_btn)
        btn_row.addStretch()
        self.save_btn = QPushButton("  加入定时转存")
        self.save_btn.setObjectName("Primary")
        self.save_btn.setIcon(make_icon("plus", "#ffffff", 16))
        self.save_btn.clicked.connect(self.on_save)
        btn_row.addWidget(self.save_btn)
        left_lay.addLayout(btn_row)

        # ============ 右：任务面板 / 目录选择（内联切换）============
        self.right_stack = QStackedWidget()
        columns.addWidget(self.right_stack, 1)
        self.right_stack.addWidget(self._build_task_page())
        self.right_stack.addWidget(self._build_folder_page())
        self.right_stack.setCurrentIndex(0)

        self.refresh_accounts()
        self.reload_tasks()

    def _build_task_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(6, 16, 20, 18)
        rl.setSpacing(11)

        self.header = self._build_header()
        rl.addWidget(self.header)

        table_card = card()
        tcl = QVBoxLayout(table_card)
        tcl.setContentsMargins(6, 6, 6, 6)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["任务", "账号", "路径", "频率", "状态", "操作"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        hh = self.table.horizontalHeader()
        hh.setMinimumSectionSize(60)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        for i in (1, 3, 4, 5):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        tcl.addWidget(self.table)
        rl.addWidget(table_card, 1)
        return page

    def _build_folder_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(6, 16, 20, 18)
        rl.setSpacing(11)

        head = QHBoxLayout()
        title = QLabel("选择转存目标文件夹")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        head.addStretch()
        close = QPushButton("✕")
        close.setObjectName("IconBtn")
        close.setFixedSize(30, 28)
        close.clicked.connect(lambda: self.right_stack.setCurrentIndex(0))
        head.addWidget(close)
        rl.addLayout(head)

        browser_card = card()
        bcl = QVBoxLayout(browser_card)
        bcl.setContentsMargins(14, 12, 14, 12)
        bcl.setSpacing(8)
        self.browser = NetdiskBrowser()
        bcl.addWidget(self.browser)
        use = QPushButton("  使用此文件夹")
        use.setObjectName("Primary")
        use.setIcon(make_icon("check", "#ffffff", 16))
        use.clicked.connect(self._use_folder)
        bcl.addWidget(use)
        rl.addWidget(browser_card, 1)
        return page

    def _build_header(self) -> QFrame:
        h = QFrame()
        h.setObjectName("SyncHeader")
        h.setFixedHeight(66)
        lay = QHBoxLayout(h)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(12)
        self.badge = QLabel("0")
        self.badge.setObjectName("RoundBadge")
        self.badge.setFixedSize(44, 44)
        self.badge.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.badge)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.header_title = QLabel("同步任务")
        self.header_title.setObjectName("SyncHeaderTitle")
        self.header_sub = QLabel("暂无任务")
        self.header_sub.setObjectName("SyncHeaderSub")
        col.addWidget(self.header_title)
        col.addWidget(self.header_sub)
        lay.addLayout(col)
        lay.addStretch()
        return h

    # ---- 主窗口切到本页 ----
    def on_shown(self):
        self.refresh_accounts()
        self.reload_tasks()

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

    # ---- 目标文件夹选择（右侧内联切换）----
    def pick_folder(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先在「设置」添加并选择账号")
            return
        self.right_stack.setCurrentIndex(1)
        self.browser.account_id = acc_id
        self.browser.load(self.target.text().strip() or "/")

    def _use_folder(self):
        self.target.setText(self.browser.current_dir())
        self.right_stack.setCurrentIndex(0)

    # ---- 保存（新增 / 更新）----
    def on_save(self):
        link = self.link.text().strip()
        if not link:
            QMessageBox.warning(self, "提示", "请填写分享链接")
            return
        account_id = self.account.currentData()
        if account_id is None:
            QMessageBox.warning(self, "提示", "请先在「设置」添加并选择账号")
            return
        data = {
            "account_id": account_id,
            "kind": "share",
            "link": link,
            "pwd": "",  # 提取码从链接中解析
            "target_dir": self.target.text().strip() or "/",
            "interval": self.interval.currentData(),
            "rename_on": 1 if self.rename_on.isChecked() else 0,
            "note": self.note.text().strip(),
            "enabled": 1,
        }
        if self.editing_id is None:
            task_id = db.add_task(data)
            db.add_log("info", f"新增任务：{data['note'] or link}", task_id)
            tip = "任务已加入定时转存计划。"
        else:
            task_id = self.editing_id
            db.update_task(task_id, data)
            db.add_log("info", f"更新任务：{data['note'] or link}", task_id)
            tip = "任务已更新。"
        self.reset_form()
        self.reload_tasks()
        QMessageBox.information(self, "已保存", tip)

    def reset_form(self):
        self.editing_id = None
        self.form_title.setText("新增同步任务")
        self.save_btn.setText("  加入定时转存")
        self.save_btn.setIcon(make_icon("plus", "#ffffff", 16))
        self.cancel_edit_btn.hide()
        self.link.clear()
        self.note.clear()
        self.target.setText("/来自好友的分享")
        self.rename_on.setChecked(False)
        self.interval.setCurrentIndex(3)

    def load_for_edit(self, task: dict):
        self.editing_id = task["id"]
        self.form_title.setText("编辑同步任务")
        self.save_btn.setText("  更新任务")
        self.save_btn.setIcon(make_icon("check", "#ffffff", 16))
        self.cancel_edit_btn.show()
        idx = self.account.findData(task["account_id"])
        if idx >= 0:
            self.account.setCurrentIndex(idx)
        self.link.setText(task["link"] or "")
        self.target.setText(task["target_dir"] or "/")
        self.note.setText(task["note"] or "")
        self.rename_on.setChecked(bool(task["rename_on"]))
        iv = self.interval.findData(task["interval"])
        if iv >= 0:
            self.interval.setCurrentIndex(iv)
        self.link.setFocus()

    # ---- 任务列表 ----
    def reload_tasks(self):
        tasks = db.list_tasks()
        self.table.setRowCount(0)
        enabled = 0
        for t in tasks:
            if t["enabled"]:
                enabled += 1
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(t["note"] or t["link"]))
            self.table.setItem(r, 1, QTableWidgetItem(t.get("account_name") or "—"))
            self.table.setItem(r, 2, QTableWidgetItem(t["target_dir"]))
            self.table.setItem(r, 3, QTableWidgetItem(_interval_text(t["interval"])))
            status = QTableWidgetItem("● 启用" if t["enabled"] else "○ 暂停")
            status.setForeground(Qt.darkGreen if t["enabled"] else Qt.gray)
            self.table.setItem(r, 4, status)

            ops = QWidget()
            ol = QHBoxLayout(ops)
            ol.setContentsMargins(4, 0, 4, 0)
            ol.setSpacing(3)
            ol.setAlignment(Qt.AlignVCenter)
            run_b = _icon_btn("play", "#2f6bff", "立即转存")
            run_b.clicked.connect(lambda _=False, tt=dict(t): self.run_now(tt))
            edit_b = _icon_btn("edit", "#334155", "编辑")
            edit_b.clicked.connect(lambda _=False, tt=dict(t): self.load_for_edit(tt))
            toggle_b = _icon_btn(
                "pause" if t["enabled"] else "play",
                "#a16207" if t["enabled"] else "#18a957",
                "暂停" if t["enabled"] else "启用",
            )
            toggle_b.clicked.connect(
                lambda _=False, tid=t["id"], en=t["enabled"]: self.toggle(tid, en)
            )
            del_b = _icon_btn("trash", "#e5484d", "删除")
            del_b.clicked.connect(lambda _=False, tid=t["id"]: self.on_delete(tid))
            for b in (run_b, edit_b, toggle_b, del_b):
                ol.addWidget(b)
            self.table.setCellWidget(r, 5, ops)

        total = len(tasks)
        self.badge.setText(str(enabled))
        self.header_sub.setText(
            f"启用 {enabled} / 共 {total} 个任务" if total else "暂无任务，在左侧添加"
        )

    def toggle(self, task_id: int, currently_enabled: int):
        db.set_task_enabled(task_id, not currently_enabled)
        self.reload_tasks()

    def on_delete(self, task_id: int):
        if (
            QMessageBox.question(self, "删除任务", "确定删除该任务？")
            == QMessageBox.Yes
        ):
            db.delete_task(task_id)
            if self.editing_id == task_id:
                self.reset_form()
            self.reload_tasks()

    def run_now(self, task: dict):
        if task.get("account_id") is None or db.get_account(task["account_id"]) is None:
            QMessageBox.warning(self, "账号不可用", "该任务绑定的账号已删除，请重建任务")
            return
        worker = TransferWorker(task)
        worker.finished_task.connect(self._on_transfer_done)
        worker.finished.connect(lambda w=worker: self._workers.remove(w))
        self._workers.append(worker)
        worker.start()
        QMessageBox.information(self, "已开始", "转存已在后台执行，进度见「转存记录」。")

    def _on_transfer_done(self, result: dict):
        msg = (
            f"新增 {result['transferred']}，跳过 {result['skipped']}，"
            f"改名 {result['renamed']}"
        )
        if result.get("error"):
            QMessageBox.warning(self, "转存完成（含错误）", msg + f"\n错误：{result['error']}")
        else:
            QMessageBox.information(self, "转存完成", msg)
        self.reload_tasks()


def _interval_text(key: str) -> str:
    return {"30m": "每30分钟", "hourly": "每小时", "6h": "每6小时", "daily": "每天"}.get(
        key, key
    )
