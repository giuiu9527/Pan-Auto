"""自动同步页（仿 NeoPan）：分享同步 / 群组同步 双 Tab + 右侧统一任务列表。"""
import json

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
    QButtonGroup,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QFrame,
    QStackedWidget,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal, QSize

from app.ui.widgets import card, field_label, field_group, label
from app.ui.icons import make_icon, make_pixmap
from app.ui.netdisk_browser import NetdiskBrowser
from app.ui.group_picker import GroupPickerPopup
from app.core.transfer import run_task, next_run_ts, running_task_ids, set_task_running
from app.netdisk import account_display_name
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
        self.editing_id = None       # 正在编辑的任务 id
        self.mode = "share"          # share / group
        self.group_ref = None        # 群同步选中的目标 {gid,gname,display,[msg_id,from_uk,fs_id]}
        self._pickers = []           # 持有弹窗引用，直到其线程结束，避免 QThread 被回收
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

        self.form_title = QLabel("自动同步")
        self.form_title.setObjectName("PageTitle")
        left_lay.addWidget(self.form_title)

        # Tab：分享同步 / 群组同步（放进卡片内，见下方 fl）
        self.tab_group = QButtonGroup(self)
        self.share_tab = QPushButton("  分享同步")
        self.share_tab.setObjectName("Tab")
        self.share_tab.setCheckable(True)
        self.share_tab.setChecked(True)
        self.share_tab.setFixedHeight(36)
        self.share_tab.setCursor(Qt.PointingHandCursor)
        self.share_tab.setIcon(make_icon("link", "#ffffff", 15))
        self.group_tab = QPushButton("  群组同步")
        self.group_tab.setObjectName("Tab")
        self.group_tab.setCheckable(True)
        self.group_tab.setFixedHeight(36)
        self.group_tab.setCursor(Qt.PointingHandCursor)
        self.group_tab.setIcon(make_icon("users", "#5b6473", 15))
        self.tab_group.addButton(self.share_tab)
        self.tab_group.addButton(self.group_tab)
        self.tab_group.setExclusive(True)
        self.share_tab.clicked.connect(lambda: self.set_tab("share"))
        self.group_tab.clicked.connect(lambda: self.set_tab("group"))
        tab_row = QHBoxLayout()
        tab_row.setSpacing(8)
        tab_row.addWidget(self.share_tab, 1)
        tab_row.addWidget(self.group_tab, 1)

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
        fl.setContentsMargins(18, 14, 18, 16)
        fl.setSpacing(12)

        fl.addLayout(tab_row)

        self.account = QComboBox()
        fl.addWidget(field_group("转存到哪个账号 *", self.account))

        # 分享 / 群组 各自的输入区（切换）。用 Maximum 高度策略，避免被拉伸出空白
        self.input_stack = QStackedWidget()
        self.input_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.input_stack.addWidget(self._build_share_input())
        self.input_stack.addWidget(self._build_group_input())
        fl.addWidget(self.input_stack)

        # 保存位置（共用）
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
        fl.addWidget(field_group("保存位置", dir_widget))

        # 选项（共用）
        self.rename_on = QCheckBox("同步后自动重命名新增文件（套用「批量重命名」规则）")
        fl.addWidget(self.rename_on)
        self.ad_skip = QCheckBox("同步时自动过滤广告文件（关键词在「设置」页配置）")
        self.ad_skip.setChecked(True)
        fl.addWidget(self.ad_skip)

        self.interval = QComboBox()
        for name, key in INTERVALS:
            self.interval.addItem(name, key)
        self.interval.setCurrentIndex(3)
        fl.addWidget(field_group("同步时间间隔", self.interval))

        self.note = QLineEdit()
        self.note.setPlaceholderText("便于识别，如：BL讲义更新")
        fl.addWidget(field_group("任务备注（可选）", self.note))
        root.addWidget(form_card)
        root.addStretch()  # 卡片按内容高度停靠顶部，多余空间留白在下方，避免中间空档

        btn_row = QHBoxLayout()
        self.cancel_edit_btn = QPushButton("取消编辑")
        self.cancel_edit_btn.setObjectName("Ghost")
        self.cancel_edit_btn.clicked.connect(self.reset_form)
        self.cancel_edit_btn.hide()
        btn_row.addWidget(self.cancel_edit_btn)
        btn_row.addStretch()
        self.save_btn = QPushButton("  加入同步")
        self.save_btn.setObjectName("Primary")
        self.save_btn.setIcon(make_icon("plus", "#ffffff", 16))
        self.save_btn.clicked.connect(self.on_save)
        btn_row.addWidget(self.save_btn)
        left_lay.addLayout(btn_row)

        # ============ 右：任务面板 / 目录选择 ============
        self.right_stack = QStackedWidget()
        columns.addWidget(self.right_stack, 1)
        self.right_stack.addWidget(self._build_task_page())
        self.right_stack.addWidget(self._build_folder_page())
        self.right_stack.setCurrentIndex(0)

        self.refresh_accounts()
        self.reload_tasks()

    # ---- 左侧输入区 ----
    def _build_share_input(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.link = QLineEdit()
        self.link.setPlaceholderText("粘贴分享链接，提取码可写在链接里 ?pwd=xxxx")
        lay.addWidget(field_group("分享链接（含提取码）*", self.link))
        return w

    def _build_group_input(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        gw = QWidget()
        gr = QHBoxLayout(gw)
        gr.setContentsMargins(0, 0, 0, 0)
        gr.setSpacing(8)
        self.group_display = QLineEdit()
        self.group_display.setReadOnly(True)
        self.group_display.setPlaceholderText("点右侧图标选群，进群选文件夹")
        gr.addWidget(self.group_display, 1)
        self.group_pick_btn = QPushButton()
        self.group_pick_btn.setObjectName("Ghost")
        self.group_pick_btn.setIcon(make_icon("users", "#2f6bff", 16))
        self.group_pick_btn.setToolTip("选择百度群和文件夹")
        self.group_pick_btn.setFixedSize(42, 40)
        self.group_pick_btn.clicked.connect(self.open_group_picker)
        gr.addWidget(self.group_pick_btn)
        lay.addWidget(field_group("选择群文件夹 *", gw))
        return w

    def set_tab(self, mode: str):
        self.mode = mode
        self.input_stack.setCurrentIndex(0 if mode == "share" else 1)
        self.share_tab.setIcon(make_icon("link", "#ffffff" if mode == "share" else "#5b6473", 15))
        self.group_tab.setIcon(make_icon("users", "#ffffff" if mode == "group" else "#5b6473", 15))

    def open_group_picker(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先在「设置」添加并选择百度账号")
            return
        pop = GroupPickerPopup(acc_id, self)
        pop.picked.connect(self._on_group_picked)
        pop.destroyed.connect(lambda _=None, p=pop: self._pickers.remove(p) if p in self._pickers else None)
        gp = self.group_display.mapToGlobal(self.group_display.rect().bottomLeft())
        pop.move(gp)
        pop.show()
        self._pickers.append(pop)

    def _on_group_picked(self, ref: dict):
        self.group_ref = ref
        self.group_display.setText(ref.get("display", ref.get("gname", "")))

    # ---- 右侧页 ----
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
        self.table.setHorizontalHeaderLabels(["任务", "账号", "路径", "频率", "状态", "操作"])
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
        title = QLabel("选择保存位置")
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
            self.account.addItem(account_display_name(acc), acc["id"])
        idx = self.account.findData(prev)
        if idx >= 0:
            self.account.setCurrentIndex(idx)
        self.account.blockSignals(False)

    # ---- 保存位置选择 ----
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
        account_id = self.account.currentData()
        if account_id is None:
            QMessageBox.warning(self, "提示", "请先在「设置」添加并选择账号")
            return
        common = {
            "account_id": account_id,
            "target_dir": self.target.text().strip() or "/",
            "interval": self.interval.currentData(),
            "rename_on": 1 if self.rename_on.isChecked() else 0,
            "ad_skip": 1 if self.ad_skip.isChecked() else 0,
            "note": self.note.text().strip(),
            "enabled": 1,
        }
        if self.mode == "share":
            link = self.link.text().strip()
            if not link:
                QMessageBox.warning(self, "提示", "请填写分享链接")
                return
            data = {**common, "kind": "share", "link": link, "pwd": ""}
        else:
            if not self.group_ref:
                QMessageBox.warning(self, "提示", "请先选择要同步的群 / 群文件夹")
                return
            ref = self.group_ref
            folder = ""
            if ref.get("fs_id"):
                folder = json.dumps(
                    {"fs_id": ref["fs_id"], "msg_id": ref["msg_id"], "from_uk": ref.get("from_uk", "")}
                )
            data = {
                **common,
                "kind": "group",
                "entity_id": str(ref["gid"]),
                "entity_name": ref.get("display") or ref.get("gname"),
                "link": folder,
                "pwd": "",
                "note": common["note"] or f"群：{ref.get('display') or ref.get('gname')}",
            }

        if self.editing_id is None:
            db.add_task(data)
            tip = "任务已加入自动同步计划。"
        else:
            db.update_task(self.editing_id, data)
            tip = "任务已更新。"
        db.add_log("info", f"{'更新' if self.editing_id else '新增'}同步任务：{data.get('note') or data.get('link')}")
        self.reset_form()
        self.reload_tasks()
        QMessageBox.information(self, "已保存", tip)

    def reset_form(self):
        self.editing_id = None
        self.save_btn.setText("  加入同步")
        self.save_btn.setIcon(make_icon("plus", "#ffffff", 16))
        self.cancel_edit_btn.hide()
        self.link.clear()
        self.note.clear()
        self.group_ref = None
        self.group_display.clear()
        self.target.setText("/来自好友的分享")
        self.rename_on.setChecked(False)
        self.ad_skip.setChecked(True)
        self.interval.setCurrentIndex(3)

    def load_for_edit(self, task: dict):
        self.editing_id = task["id"]
        self.save_btn.setText("  更新任务")
        self.save_btn.setIcon(make_icon("check", "#ffffff", 16))
        self.cancel_edit_btn.show()
        idx = self.account.findData(task["account_id"])
        if idx >= 0:
            self.account.setCurrentIndex(idx)
        self.target.setText(task["target_dir"] or "/")
        self.note.setText(task["note"] or "")
        self.rename_on.setChecked(bool(task["rename_on"]))
        self.ad_skip.setChecked(bool(task.get("ad_skip")))
        iv = self.interval.findData(task["interval"])
        if iv >= 0:
            self.interval.setCurrentIndex(iv)
        if task.get("kind", "share") == "share":
            self.set_tab("share")
            self.share_tab.setChecked(True)
            self.link.setText(task["link"] or "")
        else:
            self.set_tab("group")
            self.group_tab.setChecked(True)
            ref = {"gid": task.get("entity_id"), "gname": task.get("entity_name"),
                   "display": task.get("entity_name")}
            try:
                fr = json.loads(task.get("link") or "")
                if isinstance(fr, dict) and fr.get("fs_id"):
                    ref.update({"fs_id": fr["fs_id"], "msg_id": str(fr["msg_id"]),
                                "from_uk": str(fr.get("from_uk", ""))})
            except (ValueError, TypeError):
                pass
            self.group_ref = ref
            self.group_display.setText(task.get("entity_name") or "")

    # ---- 任务列表 ----
    def reload_tasks(self):
        tasks = db.list_tasks()
        running = running_task_ids()
        self.table.setRowCount(0)
        enabled = 0
        for t in tasks:
            if t["enabled"]:
                enabled += 1
            r = self.table.rowCount()
            self.table.insertRow(r)
            kind = t.get("kind", "share")
            prefix = "🔗 " if kind == "share" else "👥 "
            name = t["note"] or t.get("entity_name") or t["link"] or "-"
            self.table.setItem(r, 0, QTableWidgetItem(prefix + name))
            self.table.setItem(r, 1, QTableWidgetItem(t.get("account_name") or "—"))
            self.table.setItem(r, 2, QTableWidgetItem(t["target_dir"]))
            self.table.setItem(r, 3, QTableWidgetItem(_interval_text(t["interval"])))
            if t["id"] in running:
                stxt, scolor = "⟳ 运行中", Qt.blue
            elif t["enabled"]:
                nxt = next_run_ts(t)
                if nxt:
                    import time as _t
                    stxt = "● 下次 " + _t.strftime("%m-%d %H:%M", _t.localtime(nxt))
                else:
                    stxt = "● 待首次同步"
                scolor = Qt.darkGreen
            else:
                stxt, scolor = "○ 暂停", Qt.gray
            status = QTableWidgetItem(stxt)
            status.setForeground(scolor)
            self.table.setItem(r, 4, status)

            ops = QWidget()
            ol = QHBoxLayout(ops)
            ol.setContentsMargins(4, 0, 4, 0)
            ol.setSpacing(3)
            ol.setAlignment(Qt.AlignVCenter)
            run_b = _icon_btn("play", "#2f6bff", "立即同步")
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
        set_task_running(task.get("id"), True)  # 立即在列表显示"运行中"
        worker = TransferWorker(task)
        worker.finished_task.connect(self._on_transfer_done)
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(worker)
        worker.start()
        self.reload_tasks()
        QMessageBox.information(self, "已开始", "同步已在后台执行，进度见「转存记录」。")

    def _on_transfer_done(self, result: dict):
        msg = (
            f"新增 {result['transferred']}，跳过 {result['skipped']}，"
            f"改名 {result['renamed']}"
        )
        if result.get("error"):
            QMessageBox.warning(self, "同步完成（含错误）", msg + f"\n错误：{result['error']}")
        else:
            QMessageBox.information(self, "同步完成", msg)
        self.reload_tasks()


def _interval_text(key: str) -> str:
    return {"30m": "每30分钟", "hourly": "每小时", "6h": "每6小时", "daily": "每天"}.get(
        key, key
    )
