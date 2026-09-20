"""好友消息 / 群文件页（百度网盘）。

左侧：账号 + 好友/群切换 + 对象列表（可筛选）；右侧：该对象发来的文件树（可展开进
多级文件夹），勾选后转存到指定文件夹；底部可把该对象加入定时同步并管理任务。
"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QStackedWidget,
    QMessageBox,
    QAbstractItemView,
)
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QColor

from app import db
from app import theme
from app.baidu.client import get_client_for_account
from app.core.transfer import (
    run_task, INTERVAL_CHOICES, interval_label, is_task_running, running_task_ids,
    next_run_ts,
)
from app.ui.icons import make_icon
from app.ui.netdisk_browser import NetdiskBrowser
from app.ui.widgets import (
    card, field_group, button, square_button, icon_button, input_with_button,
    SegmentBar, PageHeader, TwoColumn, setup_table, table_frame, actions_cell,
    pill_cell, fmt_size, fmt_time, label,
)

DEFAULT_INTERVAL = "hourly"


class EntitiesWorker(QThread):
    done = Signal(list)
    error = Signal(str)

    def __init__(self, account_id, mode):
        super().__init__()
        self.account_id = account_id
        self.mode = mode

    def run(self):
        client = get_client_for_account(self.account_id)
        if client is None:
            self.error.emit("账号不可用，请先在「设置」登录百度网盘")
            return
        try:
            self.done.emit(client.list_friends() if self.mode == "friend" else client.list_groups())
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class MessagesWorker(QThread):
    done = Signal(list)
    error = Signal(str)

    def __init__(self, account_id, mode, entity_id):
        super().__init__()
        self.account_id = account_id
        self.mode = mode
        self.entity_id = entity_id

    def run(self):
        client = get_client_for_account(self.account_id)
        if client is None:
            self.error.emit("账号不可用")
            return
        try:
            if self.mode == "friend":
                self.done.emit(client.list_friend_files(self.entity_id))
            else:
                self.done.emit(client.list_group_files(self.entity_id))
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class TransferWorker(QThread):
    done = Signal(dict)

    def __init__(self, account_id, mode, gid, jobs, target_dir):
        super().__init__()
        self.account_id = account_id
        self.mode = mode
        self.gid = gid
        self.jobs = jobs  # [(from_uk, msg_id, [fsid, ...])]
        self.target_dir = target_dir

    def run(self):
        import random
        import time as _t

        client = get_client_for_account(self.account_id)
        if client is None:
            self.done.emit({"ok": 0, "failed": len(self.jobs), "error": "账号不可用"})
            return
        try:
            target = client.resolve_target(self.target_dir)
        except Exception as e:  # noqa: BLE001
            self.done.emit({"ok": 0, "failed": len(self.jobs), "error": f"目标目录处理失败：{e}"})
            return
        ok = 0
        failed = 0
        errors = []
        for from_uk, msg_id, fsids in self.jobs:
            try:
                if self.mode == "friend":
                    res = client.transfer_friend_files(from_uk, msg_id, fsids, target)
                else:
                    res = client.transfer_group_files(self.gid, from_uk, msg_id, fsids, target)
                errno = res.get("errno")
                if errno in (0, None):
                    ok += 1
                else:
                    failed += 1
                    from app.baidu.client import _share_err

                    errors.append(_share_err(errno, "转存失败"))
            except Exception as e:  # noqa: BLE001
                failed += 1
                errors.append(str(e))
            _t.sleep(random.uniform(1.5, 3.0))
        self.done.emit({"ok": ok, "failed": failed, "error": "; ".join(errors[:3])})


class SyncRunWorker(QThread):
    done = Signal(dict)

    def __init__(self, task: dict):
        super().__init__()
        self.task = task

    def run(self):
        self.done.emit(run_task(self.task))


class FolderWorker(QThread):
    done = Signal(object, list)
    error = Signal(object, str)

    def __init__(self, account_id, from_uk, msg_id, fs_id, gid, item):
        super().__init__()
        self.account_id = account_id
        self.from_uk = from_uk
        self.msg_id = msg_id
        self.fs_id = fs_id
        self.gid = gid
        self.item = item

    def run(self):
        client = get_client_for_account(self.account_id)
        if client is None:
            self.error.emit(self.item, "账号不可用")
            return
        try:
            self.done.emit(self.item, client.list_msg_folder(self.from_uk, self.msg_id, self.fs_id, self.gid))
        except Exception as e:  # noqa: BLE001
            self.error.emit(self.item, str(e))


class FriendMessagePage(QWidget):
    tasks_changed = Signal()

    def __init__(self):
        super().__init__()
        self.mode = "friend"
        self.entity_id = None
        self.entity_name = ""
        self._entities: list[dict] = []
        self._workers = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self._build_messages_page())
        self.right_stack.addWidget(self._build_folder_page())
        outer.addWidget(TwoColumn(self._build_left(), self.right_stack, left_width=330,
                                  left_min=290, left_max=420))

        self.refresh_accounts()
        self.reload_sync_tasks()

    # ===== 左：账号 + 对象列表 =====
    def _build_left(self) -> QWidget:
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(24, 20, 10, 20)
        ll.setSpacing(12)

        ll.addWidget(PageHeader("好友 / 群文件", "手动挑选转存，或加入定时同步"))

        self.account = QComboBox()
        self.account.currentIndexChanged.connect(lambda _=0: self.reload_entities())
        ll.addWidget(field_group("百度账号", self.account))

        self.seg = SegmentBar([("friend", "好友"), ("group", "群组")], "friend")
        self.seg.changed.connect(self.set_mode)
        ll.addWidget(self.seg)

        c = card()
        lc = QVBoxLayout(c)
        lc.setContentsMargins(10, 10, 10, 10)
        lc.setSpacing(8)
        self.entity_filter = QLineEdit()
        self.entity_filter.setPlaceholderText("筛选名称…")
        self.entity_filter.setClearButtonEnabled(True)
        self.entity_filter.textChanged.connect(lambda _t: self._render_entities())
        lc.addWidget(self.entity_filter)
        self.entity_list = QListWidget()
        self.entity_list.setFrameShape(QListWidget.NoFrame)
        self.entity_list.setIconSize(QSize(16, 16))
        self.entity_list.itemClicked.connect(self._on_entity_clicked)
        lc.addWidget(self.entity_list, 1)
        self.entity_status = label("", "Hint")
        self.entity_status.setWordWrap(True)
        lc.addWidget(self.entity_status)
        ll.addWidget(c, 1)
        return left

    # ===== 右：消息文件 =====
    def _build_messages_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(10, 20, 24, 20)
        rl.setSpacing(12)

        self.header = PageHeader("文件消息", "请在左侧选择好友 / 群组")
        refresh = button("刷新", "Ghost", "refresh")
        refresh.clicked.connect(self.reload_messages)
        self.header.add_action(refresh)
        rl.addWidget(self.header)

        # 转存目标
        bar = QHBoxLayout()
        bar.setSpacing(8)
        lb = QLabel("转存到")
        lb.setObjectName("FieldLabel")
        bar.addWidget(lb)
        self.target = QLineEdit("/来自好友的分享")
        pick = square_button("folder", "浏览网盘选择文件夹")
        pick.clicked.connect(self.pick_folder)
        bar.addWidget(input_with_button(self.target, pick), 1)
        rl.addLayout(bar)

        # 文件树
        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(8)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["文件 / 消息", "大小"])
        self.tree.setFrameShape(QTreeWidget.NoFrame)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.tree.setColumnWidth(1, 100)
        self.tree.header().setFixedHeight(34)
        self.tree.setRootIsDecorated(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self._file_icon = make_icon("file", theme.MUTED_2, 16)
        self._folder_icon = make_icon("folder", "#F0A93B", 16)
        self._msg_icon = make_icon("message", theme.MUTED, 16)
        cl.addWidget(self.tree, 1)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        sel_all = button("全选", "Ghost")
        sel_all.clicked.connect(lambda: self._set_all_checked(True))
        sel_none = button("全不选", "Ghost")
        sel_none.clicked.connect(lambda: self._set_all_checked(False))
        foot.addWidget(sel_all)
        foot.addWidget(sel_none)
        self.msg_status = label("", "Hint")
        foot.addWidget(self.msg_status, 1)
        self.transfer_btn = button("转存选中", "Primary", "check")
        self.transfer_btn.clicked.connect(self.do_transfer)
        foot.addWidget(self.transfer_btn)
        cl.addLayout(foot)
        rl.addWidget(c, 3)

        # 定时同步
        sc = card()
        sl = QVBoxLayout(sc)
        sl.setContentsMargins(14, 12, 14, 12)
        sl.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        t = QLabel("定时同步")
        t.setObjectName("SectionTitle")
        head.addWidget(t)
        self.sync_hint = label("选中左侧对象后可加入定时同步", "Hint")
        head.addWidget(self.sync_hint, 1)
        self.add_sync_btn = button("加入定时同步", "Ghost", "plus", theme.PRIMARY)
        self.add_sync_btn.clicked.connect(self.add_sync_task)
        head.addWidget(self.add_sync_btn)
        sl.addLayout(head)

        opts = QHBoxLayout()
        opts.setSpacing(12)
        self.interval = QComboBox()
        self.interval.setObjectName("Compact")
        for key in INTERVAL_CHOICES:
            self.interval.addItem(interval_label(key), key)
        self.interval.setCurrentIndex(self.interval.findData(DEFAULT_INTERVAL))
        opts.addWidget(self.interval)
        self.rename_on = QCheckBox("转存后重命名")
        opts.addWidget(self.rename_on)
        self.ad_skip = QCheckBox("过滤广告")
        self.ad_skip.setChecked(True)
        opts.addWidget(self.ad_skip)
        opts.addStretch()
        sl.addLayout(opts)

        self.task_table = QTableWidget(0, 4)
        self.task_table.setHorizontalHeaderLabels(["名称", "频率", "状态", "操作"])
        setup_table(self.task_table, row_height=40)
        hh = self.task_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 2, 3):
            hh.setSectionResizeMode(i, QHeaderView.Fixed)
        self.task_table.setColumnWidth(1, 92)
        self.task_table.setColumnWidth(2, 150)
        self.task_table.setColumnWidth(3, 112)
        self.task_table.setMinimumHeight(118)
        sl.addWidget(table_frame(self.task_table), 1)
        rl.addWidget(sc, 2)
        return page

    def _build_folder_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(10, 20, 24, 20)
        rl.setSpacing(12)
        head = PageHeader("选择转存目标文件夹", "双击进入文件夹，选好后点「使用此文件夹」")
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
        self.reload_sync_tasks()

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
        self.reload_entities()

    def set_mode(self, mode: str):
        if mode == self.mode:
            return
        self.mode = mode
        self.entity_id = None
        self.tree.clear()
        self.header.set_subtitle("请在左侧选择好友 / 群组")
        self.msg_status.setText("")
        self.reload_entities()

    # ---- 左侧对象列表 ----
    def reload_entities(self):
        acc_id = self.account.currentData()
        self.entity_list.clear()
        self._entities = []
        if acc_id is None:
            self.entity_status.setText("请先在「设置」登录百度账号")
            return
        self.entity_status.setText("加载中…")
        w = EntitiesWorker(acc_id, self.mode)
        w.done.connect(self._on_entities)
        w.error.connect(lambda m: self.entity_status.setText(f"加载失败：{m}"))
        w.finished.connect(lambda x=w: self._drop_worker(x))
        self._workers.append(w)
        w.start()

    def _on_entities(self, items: list):
        self._entities = items
        self._render_entities()

    def _render_entities(self):
        self.entity_list.clear()
        noun = "好友" if self.mode == "friend" else "群组"
        q = self.entity_filter.text().strip().lower()
        shown = 0
        for it in self._entities:
            name = it["name"]
            if q and q not in name.lower():
                continue
            if self.mode == "friend":
                text = name
                data = {"id": it["uk"], "name": name}
                icon = make_icon("user", theme.PRIMARY, 16)
            else:
                cnt = it.get("count") or 0
                text = f"{name}（{cnt} 人）" if cnt else name
                data = {"id": it["gid"], "name": name}
                icon = make_icon("users", "#7C3AED", 16)
            li = QListWidgetItem(icon, text)
            li.setToolTip(text)
            li.setData(Qt.UserRole, data)
            self.entity_list.addItem(li)
            shown += 1
        if not self._entities:
            self.entity_status.setText(f"没有{noun}")
        else:
            self.entity_status.setText(f"共 {len(self._entities)} 个{noun}" + (f"，显示 {shown} 个" if q else ""))

    def _on_entity_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        self.entity_id = data["id"]
        self.entity_name = data["name"]
        self.sync_hint.setText(f"把「{self.entity_name}」加入定时同步，保存到「转存到」所填目录")
        self.reload_messages()

    # ---- 加入定时同步 ----
    def add_sync_task(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先选择账号")
            return
        if not self.entity_id:
            QMessageBox.warning(self, "提示", "请先在左侧选择要同步的好友 / 群组")
            return
        noun = "好友" if self.mode == "friend" else "群"
        name = self.entity_name or self.entity_id
        data = {
            "account_id": acc_id,
            "kind": self.mode,
            "entity_id": str(self.entity_id),
            "entity_name": name,
            "target_dir": self.target.text().strip() or "/",
            "interval": self.interval.currentData(),
            "rename_on": 1 if self.rename_on.isChecked() else 0,
            "ad_skip": 1 if self.ad_skip.isChecked() else 0,
            "note": f"{noun}：{name}",
            "enabled": 1,
        }
        db.add_task(data)
        db.add_log("info", f"新增{noun}同步任务：{name}")
        self.reload_sync_tasks()
        self.tasks_changed.emit()
        QMessageBox.information(
            self, "已加入定时同步",
            f"已把「{name}」加入定时同步（{self.interval.currentText()}）。\n"
            "后台会按间隔自动只转存新增文件；「自动同步」页也能管理它。",
        )

    # ---- 定时同步任务列表 ----
    def reload_sync_tasks(self):
        if not hasattr(self, "task_table"):
            return
        tasks = [t for t in db.list_tasks() if t.get("kind") in ("friend", "group")]
        running = running_task_ids()
        self.task_table.setRowCount(0)
        self.task_table.setRowCount(len(tasks))
        for r, t in enumerate(tasks):
            name = t.get("entity_name") or t.get("note") or "-"
            it = QTableWidgetItem(name)
            it.setIcon(make_icon("user" if t["kind"] == "friend" else "users",
                                 theme.PRIMARY if t["kind"] == "friend" else "#7C3AED", 16))
            it.setToolTip(f"{'好友' if t['kind'] == 'friend' else '群'}：{name}\n保存到 {t.get('target_dir') or '/'}")
            self.task_table.setItem(r, 0, it)
            iv = QTableWidgetItem(interval_label(t["interval"]))
            iv.setForeground(QColor(theme.TEXT_2))
            self.task_table.setItem(r, 1, iv)
            fails = int(t.get("fail_count") or 0)
            if t["id"] in running:
                st, kind = "运行中", "primary"
            elif not t["enabled"]:
                st, kind = "已暂停", "muted"
            elif fails:
                st, kind = f"失败 {fails} 次", "danger"
            else:
                nxt = next_run_ts(t)
                st, kind = (f"下次 {fmt_time(nxt)}", "success") if nxt else ("等待首次同步", "info")
            self.task_table.setCellWidget(r, 2, pill_cell(st, kind))

            run_b = icon_button("play", theme.PRIMARY, "立即同步")
            run_b.clicked.connect(lambda _=False, tt=dict(t): self.run_sync(tt))
            tog = icon_button(
                "pause" if t["enabled"] else "play",
                theme.WARNING if t["enabled"] else theme.SUCCESS,
                "暂停" if t["enabled"] else "启用",
            )
            tog.clicked.connect(lambda _=False, tid=t["id"], en=t["enabled"]: self.toggle_sync(tid, en))
            del_b = icon_button("trash", theme.DANGER, "删除")
            del_b.clicked.connect(lambda _=False, tid=t["id"]: self.del_sync(tid))
            self.task_table.setCellWidget(r, 3, actions_cell([run_b, tog, del_b]))

    def run_sync(self, task: dict):
        if is_task_running(task.get("id")):
            QMessageBox.information(self, "正在运行", "该任务正在同步中，请稍候。")
            return
        self.msg_status.setText(f"正在同步「{task.get('entity_name', '')}」…")
        w = SyncRunWorker(task)
        w.done.connect(self._on_sync_done)
        w.finished.connect(lambda x=w: self._drop_worker(x))
        self._workers.append(w)
        w.start()
        self.reload_sync_tasks()

    def _on_sync_done(self, result: dict):
        self.msg_status.setText(
            f"同步完成：新增 {result.get('transferred', 0)}，"
            f"跳过 {result.get('skipped', 0)}，改名 {result.get('renamed', 0)}"
        )
        if result.get("error"):
            QMessageBox.warning(self, "同步完成（含错误）", str(result["error"]))
        self.reload_sync_tasks()

    def toggle_sync(self, task_id: int, enabled: int):
        db.set_task_enabled(task_id, not enabled)
        self.reload_sync_tasks()
        self.tasks_changed.emit()

    def del_sync(self, task_id: int):
        if QMessageBox.question(self, "删除任务", "确定删除该定时同步任务？") == QMessageBox.Yes:
            db.delete_task(task_id)
            self.reload_sync_tasks()
            self.tasks_changed.emit()

    # ---- 右侧消息文件 ----
    def reload_messages(self):
        if self.entity_id is None:
            return
        acc_id = self.account.currentData()
        self.tree.clear()
        self.header.set_subtitle(f"{self.entity_name} · 加载中…")
        self.msg_status.setText("")
        w = MessagesWorker(acc_id, self.mode, self.entity_id)
        w.done.connect(self._on_messages)
        w.error.connect(lambda m: self.header.set_subtitle(f"加载失败：{m}"))
        w.finished.connect(lambda x=w: self._drop_worker(x))
        self._workers.append(w)
        w.start()

    def _on_messages(self, messages: list):
        self.tree.clear()
        total_files = 0
        for msg in messages:
            sender = msg.get("from_uk") or "对方"
            head = QTreeWidgetItem([f"来自 {sender} · {fmt_time(msg.get('ctime', 0))}", ""])
            head.setIcon(0, self._msg_icon)
            head.setData(0, Qt.UserRole, {"kind": "msg", "msg_id": msg["msg_id"], "from_uk": msg.get("from_uk", "")})
            head.setForeground(0, QColor(theme.MUTED))
            self.tree.addTopLevelItem(head)
            for f in msg["files"]:
                head.addChild(self._make_file_item(f, msg["msg_id"], msg.get("from_uk", "")))
                total_files += 1
            head.setExpanded(True)
        if not messages:
            self.header.set_subtitle(f"{self.entity_name} · 暂无文件消息")
        else:
            self.header.set_subtitle(
                f"{self.entity_name} · {len(messages)} 条消息，{total_files} 个文件（展开文件夹可进下级）"
            )

    def _make_file_item(self, f: dict, msg_id: str, from_uk: str) -> QTreeWidgetItem:
        isdir = bool(f.get("isdir"))
        it = QTreeWidgetItem([f["server_filename"], "文件夹" if isdir else fmt_size(f.get("size", 0))])
        it.setIcon(0, self._folder_icon if isdir else self._file_icon)
        it.setToolTip(0, f["server_filename"])
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(0, Qt.Unchecked)
        it.setData(0, Qt.UserRole, {
            "kind": "file", "fs_id": f["fs_id"], "isdir": 1 if isdir else 0,
            "server_filename": f["server_filename"], "size": f.get("size", 0),
            "msg_id": msg_id, "from_uk": from_uk, "loaded": False,
        })
        if isdir:
            it.addChild(QTreeWidgetItem(["展开查看…", ""]))
        return it

    # ---- 文件夹懒加载 ----
    def _on_item_expanded(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.UserRole)
        if not data or data.get("kind") != "file" or not data.get("isdir") or data.get("loaded"):
            return
        data["loaded"] = True
        item.setData(0, Qt.UserRole, data)
        item.takeChildren()
        item.addChild(QTreeWidgetItem(["加载中…", ""]))
        acc_id = self.account.currentData()
        gid = self.entity_id if self.mode == "group" else ""
        w = FolderWorker(acc_id, data["from_uk"], data["msg_id"], data["fs_id"], gid, item)
        w.done.connect(self._on_folder_loaded)
        w.error.connect(self._on_folder_error)
        w.finished.connect(lambda x=w: self._drop_worker(x))
        self._workers.append(w)
        w.start()

    def _on_folder_loaded(self, item, children: list):
        try:
            item.takeChildren()
            data = item.data(0, Qt.UserRole) or {}
            if not children:
                item.addChild(QTreeWidgetItem(["（空文件夹）", ""]))
                return
            for f in children:
                item.addChild(self._make_file_item(f, data.get("msg_id", ""), data.get("from_uk", "")))
        except RuntimeError:
            pass

    def _on_folder_error(self, item, msg: str):
        try:
            item.takeChildren()
            item.addChild(QTreeWidgetItem([f"加载失败：{msg}", ""]))
            d = item.data(0, Qt.UserRole) or {}
            d["loaded"] = False
            item.setData(0, Qt.UserRole, d)
        except RuntimeError:
            pass

    def _set_all_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked

        def walk(item):
            for i in range(item.childCount()):
                ch = item.child(i)
                d = ch.data(0, Qt.UserRole)
                if d and d.get("kind") == "file":
                    ch.setCheckState(0, state)
                walk(ch)

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    # ---- 目录选择 ----
    def pick_folder(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先选择账号")
            return
        self.right_stack.setCurrentIndex(1)
        self.browser.account_id = acc_id
        self.browser.load(self.target.text().strip() or "/")

    def _use_folder(self):
        self.target.setText(self.browser.current_dir())
        self.right_stack.setCurrentIndex(0)

    # ---- 转存 ----
    def _collect_checked(self, item, acc: dict):
        for i in range(item.childCount()):
            ch = item.child(i)
            d = ch.data(0, Qt.UserRole)
            if not d or d.get("kind") != "file":
                self._collect_checked(ch, acc)
                continue
            if ch.checkState(0) == Qt.Checked:
                acc.setdefault((d["from_uk"], d["msg_id"]), []).append(d["fs_id"])
                if d.get("isdir"):
                    continue
            self._collect_checked(ch, acc)

    def do_transfer(self):
        acc_id = self.account.currentData()
        if acc_id is None:
            QMessageBox.warning(self, "提示", "请先选择账号")
            return
        jobs_map: dict = {}
        for i in range(self.tree.topLevelItemCount()):
            self._collect_checked(self.tree.topLevelItem(i), jobs_map)
        jobs = [(fu, mid, fsids) for (fu, mid), fsids in jobs_map.items()]
        if not jobs:
            QMessageBox.warning(self, "提示", "请先勾选要转存的文件")
            return
        if QMessageBox.question(
            self, "转存确认",
            f"将转存 {len(jobs)} 条消息里勾选的文件到：\n{self.target.text().strip() or '/'}\n\n"
            "注意：百度按整条消息转存（同一条消息里的其它文件也会一起带过来）。",
        ) != QMessageBox.Yes:
            return
        self.transfer_btn.setEnabled(False)
        self.msg_status.setText("正在转存…")
        gid = self.entity_id if self.mode == "group" else ""
        w = TransferWorker(acc_id, self.mode, gid, jobs, self.target.text().strip() or "/")
        w.done.connect(self._on_transfer_done)
        w.finished.connect(lambda x=w: self._drop_worker(x))
        self._workers.append(w)
        w.start()

    def _on_transfer_done(self, result: dict):
        self.transfer_btn.setEnabled(True)
        msg = f"完成：成功 {result['ok']} 条消息，失败 {result['failed']} 条"
        self.msg_status.setText(msg)
        db.add_log("info", f"好友/群文件转存 {msg}")
        if result.get("failed"):
            QMessageBox.warning(self, "转存完成（含失败）",
                                msg + (f"\n错误：{result['error']}" if result.get("error") else ""))
        else:
            QMessageBox.information(self, "转存完成", msg)

    def _drop_worker(self, w):
        if w in self._workers:
            self._workers.remove(w)
