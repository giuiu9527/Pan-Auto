"""好友消息 / 群文件转存页（百度网盘）。

左侧选账号 + 切换「好友 / 群组」+ 选对象；右侧列出该对象发来的文件消息，
勾选文件后转存到指定文件夹。转存按消息分组调用 mbox 接口。
"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QButtonGroup,
    QStackedWidget,
    QMessageBox,
)
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QColor

from app.ui.widgets import card, field_group, label
from app.ui.icons import make_icon
from app.ui.netdisk_browser import NetdiskBrowser
from app.baidu.client import get_client_for_account
from app.core.transfer import run_task
from app import db

INTERVALS = [
    ("每 1 分钟同步一次", "1m"),
    ("每 30 分钟同步一次", "30m"),
    ("每小时同步一次", "hourly"),
    ("每 6 小时同步一次", "6h"),
    ("每天同步一次", "daily"),
]

DEFAULT_INTERVAL = "daily"


def _interval_text(key: str) -> str:
    return {
        "1m": "每1分钟",
        "30m": "每30分钟",
        "hourly": "每小时",
        "6h": "每6小时",
        "daily": "每天",
    }.get(key, key)


def _fmt_size(n: int) -> str:
    if not n:
        return ""
    x = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024:
            return f"{x:.0f}{unit}" if unit == "B" else f"{x:.1f}{unit}"
        x /= 1024
    return f"{x:.1f}PB"


def _fmt_time(ts: int) -> str:
    if not ts:
        return ""
    import time as _t

    try:
        return _t.strftime("%m-%d %H:%M", _t.localtime(ts))
    except (ValueError, OSError):
        return ""


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
            if self.mode == "friend":
                self.done.emit(client.list_friends())
            else:
                self.done.emit(client.list_groups())
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
        ok = 0
        failed = 0
        errors = []
        for from_uk, msg_id, fsids in self.jobs:
            try:
                if self.mode == "friend":
                    res = client.transfer_friend_files(
                        from_uk, msg_id, fsids, self.target_dir
                    )
                else:
                    res = client.transfer_group_files(
                        self.gid, from_uk, msg_id, fsids, self.target_dir
                    )
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
    """立即跑一个已保存的定时同步任务（复用统一 run_task）。"""

    done = Signal(dict)

    def __init__(self, task: dict):
        super().__init__()
        self.task = task

    def run(self):
        self.done.emit(run_task(self.task))


class FolderWorker(QThread):
    """展开好友/群消息里的某个共享文件夹（列子内容）。"""

    done = Signal(object, list)   # tree_item, children
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
            children = client.list_msg_folder(
                self.from_uk, self.msg_id, self.fs_id, self.gid
            )
            self.done.emit(self.item, children)
        except Exception as e:  # noqa: BLE001
            self.error.emit(self.item, str(e))


def _icon_btn(icon_name: str, color: str, tip: str) -> QPushButton:
    b = QPushButton()
    b.setObjectName("IconBtn")
    b.setIcon(make_icon(icon_name, color, 18, width=2.3))
    b.setIconSize(QSize(18, 18))
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    b.setFixedSize(32, 28)
    return b


class FriendMessagePage(QWidget):
    def __init__(self):
        super().__init__()
        self.mode = "friend"
        self.entity_id = None  # 当前选中的好友 uk / 群 gid
        self._workers = []

        columns = QHBoxLayout(self)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(0)

        # ===== 左：账号 + Tab + 对象列表 =====
        left = QWidget()
        left.setFixedWidth(300)
        columns.addWidget(left)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(22, 14, 12, 16)
        ll.setSpacing(11)

        title = QLabel("好友消息 / 群文件")
        title.setObjectName("PageTitle")
        ll.addWidget(title)

        self.account = QComboBox()
        self.account.currentIndexChanged.connect(lambda _=0: self.reload_entities())
        ll.addWidget(field_group("账号 *", self.account))

        tab_row = QHBoxLayout()
        self.tab_group = QButtonGroup(self)
        self.friend_tab = QPushButton("好友")
        self.friend_tab.setObjectName("Tab")
        self.friend_tab.setCheckable(True)
        self.friend_tab.setChecked(True)
        self.group_tab = QPushButton("群组")
        self.group_tab.setObjectName("Tab")
        self.group_tab.setCheckable(True)
        self.tab_group.addButton(self.friend_tab)
        self.tab_group.addButton(self.group_tab)
        self.tab_group.setExclusive(True)
        self.friend_tab.clicked.connect(lambda: self.set_mode("friend"))
        self.group_tab.clicked.connect(lambda: self.set_mode("group"))
        tab_row.addWidget(self.friend_tab)
        tab_row.addWidget(self.group_tab)
        tab_row.addStretch()
        ll.addLayout(tab_row)

        list_card = card()
        lc = QVBoxLayout(list_card)
        lc.setContentsMargins(8, 8, 8, 8)
        self.entity_list = QListWidget()
        self.entity_list.itemClicked.connect(self._on_entity_clicked)
        lc.addWidget(self.entity_list)
        self.entity_status = QLabel("")
        self.entity_status.setObjectName("Muted")
        lc.addWidget(self.entity_status)
        ll.addWidget(list_card, 1)

        # ===== 右：消息文件 / 目录选择 =====
        self.right_stack = QStackedWidget()
        columns.addWidget(self.right_stack, 1)
        self.right_stack.addWidget(self._build_messages_page())
        self.right_stack.addWidget(self._build_folder_page())
        self.right_stack.setCurrentIndex(0)

        self.refresh_accounts()
        self.reload_sync_tasks()

    # ---- 右侧：消息页 ----
    def _build_messages_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(6, 14, 20, 16)
        rl.setSpacing(10)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("转存到："))
        self.target = QLineEdit("/来自好友的分享")
        bar.addWidget(self.target, 1)
        pick = QPushButton()
        pick.setObjectName("Ghost")
        pick.setIcon(make_icon("folder", "#4a5365", 16))
        pick.setFixedSize(40, 34)
        pick.setToolTip("浏览网盘选择文件夹")
        pick.clicked.connect(self.pick_folder)
        bar.addWidget(pick)
        refresh = QPushButton(" 刷新")
        refresh.setObjectName("Ghost")
        refresh.setIcon(make_icon("refresh", "#4a5365", 15))
        refresh.clicked.connect(self.reload_messages)
        bar.addWidget(refresh)
        rl.addLayout(bar)

        # 定时同步选项行
        opt = QHBoxLayout()
        opt.addWidget(QLabel("定时："))
        self.interval = QComboBox()
        for nm, key in INTERVALS:
            self.interval.addItem(nm, key)
        self.interval.setCurrentIndex(self.interval.findData(DEFAULT_INTERVAL))
        opt.addWidget(self.interval)
        self.rename_on = QCheckBox("转存后重命名")
        opt.addWidget(self.rename_on)
        self.ad_skip = QCheckBox("过滤广告文件")
        self.ad_skip.setChecked(True)
        opt.addWidget(self.ad_skip)
        opt.addStretch()
        self.add_sync_btn = QPushButton("  加入定时同步")
        self.add_sync_btn.setObjectName("Ghost")
        self.add_sync_btn.setIcon(make_icon("sync", "#2f6bff", 15))
        self.add_sync_btn.clicked.connect(self.add_sync_task)
        opt.addWidget(self.add_sync_btn)
        rl.addLayout(opt)

        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(6, 6, 6, 6)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["文件 / 消息", "大小"])
        self.tree.setColumnWidth(0, 420)
        self.tree.setRootIsDecorated(True)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self._file_icon = make_icon("file", "#9aa4b5", 16)
        self._folder_icon = make_icon("folder", "#f0a93b", 16)
        cl.addWidget(self.tree)
        rl.addWidget(c, 1)

        foot = QHBoxLayout()
        sel_all = QPushButton("全选")
        sel_all.setObjectName("Ghost")
        sel_all.clicked.connect(lambda: self._set_all_checked(True))
        sel_none = QPushButton("全不选")
        sel_none.setObjectName("Ghost")
        sel_none.clicked.connect(lambda: self._set_all_checked(False))
        foot.addWidget(sel_all)
        foot.addWidget(sel_none)
        foot.addStretch()
        self.msg_status = QLabel("请选择左侧的好友 / 群组")
        self.msg_status.setObjectName("Muted")
        foot.addWidget(self.msg_status)
        foot.addStretch()
        self.transfer_btn = QPushButton("  转存选中")
        self.transfer_btn.setObjectName("Primary")
        self.transfer_btn.setIcon(make_icon("check", "#ffffff", 16))
        self.transfer_btn.clicked.connect(self.do_transfer)
        foot.addWidget(self.transfer_btn)
        rl.addLayout(foot)

        # ---- 已加入的定时同步任务 ----
        tl = QLabel("已加入的定时同步任务")
        tl.setObjectName("FieldLabel")
        rl.addWidget(tl)
        self.task_table = QTableWidget(0, 5)
        self.task_table.setHorizontalHeaderLabels(["名称", "类型", "频率", "状态", "操作"])
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.verticalHeader().setDefaultSectionSize(38)
        self.task_table.setShowGrid(False)
        self.task_table.setSelectionMode(QTableWidget.NoSelection)
        self.task_table.setMaximumHeight(190)
        hh = self.task_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 2, 3, 4):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        rl.addWidget(self.task_table)
        return page

    def _build_folder_page(self) -> QWidget:
        page = QWidget()
        rl = QVBoxLayout(page)
        rl.setContentsMargins(6, 14, 20, 16)
        rl.setSpacing(10)
        head = QHBoxLayout()
        t = QLabel("选择转存目标文件夹")
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
        self.msg_status.setText("请选择左侧的好友 / 群组")
        self.reload_entities()

    # ---- 左侧对象列表 ----
    def reload_entities(self):
        acc_id = self.account.currentData()
        self.entity_list.clear()
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
        self.entity_list.clear()
        noun = "好友" if self.mode == "friend" else "群组"
        if not items:
            self.entity_status.setText(f"没有{noun}")
            return
        for it in items:
            if self.mode == "friend":
                text = it["name"]
                data = {"id": it["uk"], "name": it["name"]}
            else:
                cnt = it.get("count") or 0
                text = f"{it['name']}  ({cnt}人)" if cnt else it["name"]
                data = {"id": it["gid"], "name": it["name"]}
            li = QListWidgetItem(text)
            li.setData(Qt.UserRole, data)
            self.entity_list.addItem(li)
        self.entity_status.setText(f"共 {len(items)} 个{noun}")

    def _on_entity_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        self.entity_id = data["id"]
        self.entity_name = data["name"]
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
        name = getattr(self, "entity_name", "") or self.entity_id
        data = {
            "account_id": acc_id,
            "kind": self.mode,  # friend / group
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
        QMessageBox.information(
            self,
            "已加入定时同步",
            f"已把「{name}」加入定时同步（{self.interval.currentText()}）。\n"
            "后台会按间隔自动只转存新增文件；下方列表可管理。",
        )

    # ---- 定时同步任务列表 ----
    def reload_sync_tasks(self):
        if not hasattr(self, "task_table"):
            return
        tasks = [t for t in db.list_tasks() if t.get("kind") in ("friend", "group")]
        self.task_table.setRowCount(0)
        for t in tasks:
            r = self.task_table.rowCount()
            self.task_table.insertRow(r)
            self.task_table.setItem(
                r, 0, QTableWidgetItem(t.get("entity_name") or t.get("note") or "-")
            )
            self.task_table.setItem(
                r, 1, QTableWidgetItem("好友" if t["kind"] == "friend" else "群")
            )
            self.task_table.setItem(r, 2, QTableWidgetItem(_interval_text(t["interval"])))
            st = QTableWidgetItem("● 启用" if t["enabled"] else "○ 暂停")
            st.setForeground(QColor("#18a957") if t["enabled"] else QColor("#8b95a7"))
            self.task_table.setItem(r, 3, st)

            ops = QWidget()
            ol = QHBoxLayout(ops)
            ol.setContentsMargins(2, 0, 2, 0)
            ol.setSpacing(2)
            run_b = _icon_btn("play", "#2f6bff", "立即同步")
            run_b.clicked.connect(lambda _=False, tt=dict(t): self.run_sync(tt))
            tog = _icon_btn(
                "pause" if t["enabled"] else "play",
                "#a16207" if t["enabled"] else "#18a957",
                "暂停" if t["enabled"] else "启用",
            )
            tog.clicked.connect(
                lambda _=False, tid=t["id"], en=t["enabled"]: self.toggle_sync(tid, en)
            )
            del_b = _icon_btn("trash", "#e5484d", "删除")
            del_b.clicked.connect(lambda _=False, tid=t["id"]: self.del_sync(tid))
            for b in (run_b, tog, del_b):
                ol.addWidget(b)
            self.task_table.setCellWidget(r, 4, ops)

    def run_sync(self, task: dict):
        self.msg_status.setText(f"正在同步「{task.get('entity_name', '')}」…")
        w = SyncRunWorker(task)
        w.done.connect(self._on_sync_done)
        w.finished.connect(lambda x=w: self._drop_worker(x))
        self._workers.append(w)
        w.start()

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

    def del_sync(self, task_id: int):
        if QMessageBox.question(self, "删除任务", "确定删除该定时同步任务？") == QMessageBox.Yes:
            db.delete_task(task_id)
            self.reload_sync_tasks()

    # ---- 右侧消息文件 ----
    def reload_messages(self):
        if self.entity_id is None:
            return
        acc_id = self.account.currentData()
        self.tree.clear()
        self.msg_status.setText("加载中…")
        w = MessagesWorker(acc_id, self.mode, self.entity_id)
        w.done.connect(self._on_messages)
        w.error.connect(lambda m: self.msg_status.setText(f"加载失败：{m}"))
        w.finished.connect(lambda x=w: self._drop_worker(x))
        self._workers.append(w)
        w.start()

    def _on_messages(self, messages: list):
        self.tree.clear()
        total_files = 0
        for msg in messages:
            sender = msg.get("from_uk") or "对方"
            head = QTreeWidgetItem(
                [f"来自 {sender} · {_fmt_time(msg.get('ctime', 0))}", ""]
            )
            head.setData(
                0, Qt.UserRole,
                {"kind": "msg", "msg_id": msg["msg_id"], "from_uk": msg.get("from_uk", "")},
            )
            head.setForeground(0, QColor("#5b6473"))
            self.tree.addTopLevelItem(head)
            for f in msg["files"]:
                head.addChild(self._make_file_item(f, msg["msg_id"], msg.get("from_uk", "")))
                total_files += 1
            head.setExpanded(True)
        if not messages:
            self.msg_status.setText("该对象暂无文件消息")
        else:
            self.msg_status.setText(
                f"共 {len(messages)} 条消息，{total_files} 个文件（双击文件夹进下级）"
            )

    def _make_file_item(self, f: dict, msg_id: str, from_uk: str) -> QTreeWidgetItem:
        isdir = bool(f.get("isdir"))
        size_col = "整个文件夹" if isdir else _fmt_size(f.get("size", 0))
        it = QTreeWidgetItem([f["server_filename"], size_col])
        it.setIcon(0, self._folder_icon if isdir else self._file_icon)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(0, Qt.Unchecked)
        it.setData(
            0, Qt.UserRole,
            {
                "kind": "file",
                "fs_id": f["fs_id"],
                "isdir": 1 if isdir else 0,
                "server_filename": f["server_filename"],
                "size": f.get("size", 0),
                "msg_id": msg_id,
                "from_uk": from_uk,
                "loaded": False,
            },
        )
        if isdir:  # 占位子项，使其可展开（懒加载）
            it.addChild(QTreeWidgetItem(["  展开查看…", ""]))
        return it

    # ---- 文件夹懒加载（进下级）----
    def _on_item_expanded(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.UserRole)
        if not data or data.get("kind") != "file" or not data.get("isdir"):
            return
        if data.get("loaded"):
            return
        data["loaded"] = True
        item.setData(0, Qt.UserRole, data)
        item.takeChildren()
        item.addChild(QTreeWidgetItem(["  加载中…", ""]))
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
                item.addChild(QTreeWidgetItem(["  (空文件夹)", ""]))
                return
            for f in children:
                item.addChild(
                    self._make_file_item(f, data.get("msg_id", ""), data.get("from_uk", ""))
                )
        except RuntimeError:
            pass  # 树可能已刷新，item 被销毁

    def _on_folder_error(self, item, msg: str):
        try:
            item.takeChildren()
            item.addChild(QTreeWidgetItem([f"  加载失败：{msg}", ""]))
            d = item.data(0, Qt.UserRole) or {}
            d["loaded"] = False  # 允许重试
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
        """递归收集勾选的文件/文件夹，按 (from_uk, msg_id) 分组。

        勾选的文件夹整体转存（用它的 fs_id），不再深入其子项。
        """
        for i in range(item.childCount()):
            ch = item.child(i)
            d = ch.data(0, Qt.UserRole)
            if not d or d.get("kind") != "file":
                self._collect_checked(ch, acc)
                continue
            if ch.checkState(0) == Qt.Checked:
                acc.setdefault((d["from_uk"], d["msg_id"]), []).append(d["fs_id"])
                if d.get("isdir"):
                    continue  # 整个文件夹已选，跳过子项避免重复
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
        target = self.target.text().strip() or "/"
        self.transfer_btn.setEnabled(False)
        self.msg_status.setText("正在转存…")
        gid = self.entity_id if self.mode == "group" else ""
        w = TransferWorker(acc_id, self.mode, gid, jobs, target)
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
            QMessageBox.warning(
                self, "转存完成（含失败）",
                msg + (f"\n错误：{result['error']}" if result.get("error") else ""),
            )
        else:
            QMessageBox.information(self, "转存完成", msg)
        self.reload_messages()

    def _drop_worker(self, w):
        if w in self._workers:
            self._workers.remove(w)
