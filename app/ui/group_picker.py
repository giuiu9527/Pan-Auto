"""群文件夹选择器（仿 NeoPan 下拉）。

点击网盘图标弹出：群列表 → 点群进入群文件根目录 → 逐级点进文件夹 →
「同步此文件夹」选定当前/选中的文件夹（或整群）。选定后发出 picked 信号。

发出的字典：
  整群：{gid, gname, display}
  文件夹：{gid, gname, msg_id, from_uk, fs_id, display}
"""
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
)
from PySide6.QtCore import Qt, QThread, Signal, QSize

from app.baidu.client import get_client_for_account
from app.ui.icons import make_icon


class _Worker(QThread):
    done = Signal(list)
    error = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class GroupPickerPopup(QFrame):
    picked = Signal(dict)

    def __init__(self, account_id, parent=None):
        super().__init__(parent, Qt.Popup)
        self.account_id = account_id
        self._alive = True
        self._workers = []
        # 导航状态
        self.gid = ""
        self.gname = ""
        self.crumbs = []          # 从群根到当前目录的名称路径
        self.folder_ref = None    # 当前所在文件夹 {msg_id, from_uk, fs_id}
        self.selected = None      # 单击选中的文件夹 {msg_id, from_uk, fs_id, name}
        self._history = []        # 返回栈：(level, gid, gname, crumbs, folder_ref)
        self.level = "groups"     # groups / grouproot / folder

        self.setObjectName("Card")
        self.setFixedSize(420, 360)
        self.setStyleSheet(
            "QFrame#Card{background:#fff;border:1px solid #e5e9f0;border-radius:10px;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        head = QHBoxLayout()
        self.back_btn = QPushButton(" 返回")
        self.back_btn.setObjectName("Ghost")
        self.back_btn.setIcon(make_icon("up", "#4a5365", 14))
        self.back_btn.clicked.connect(self.go_back)
        self.back_btn.hide()
        head.addWidget(self.back_btn)
        self.title = QLabel("百度群组（点群进文件夹）")
        self.title.setStyleSheet("font-weight:600; color:#2f6bff;")
        head.addWidget(self.title, 1)
        refresh = QPushButton()
        refresh.setObjectName("IconBtn")
        refresh.setIcon(make_icon("refresh", "#4a5365", 14))
        refresh.setFixedSize(26, 24)
        refresh.clicked.connect(self._reload_current)
        head.addWidget(refresh)
        root.addLayout(head)

        self.list = QListWidget()
        self.list.setIconSize(QSize(16, 16))
        self.list.itemClicked.connect(self._on_click)
        self.list.itemDoubleClicked.connect(self._on_double)
        root.addWidget(self.list, 1)

        foot = QHBoxLayout()
        self.hint = QLabel("单击选文件夹，双击进下级")
        self.hint.setObjectName("Muted")
        self.hint.setStyleSheet("color:#8b95a7; font-size:12px;")
        foot.addWidget(self.hint)
        foot.addStretch()
        self.use_btn = QPushButton("同步此文件夹")
        self.use_btn.setObjectName("Primary")
        self.use_btn.clicked.connect(self._confirm)
        self.use_btn.setEnabled(False)
        foot.addWidget(self.use_btn)
        root.addLayout(foot)

        self._folder_icon = make_icon("folder", "#f0a93b", 16)
        self._file_icon = make_icon("file", "#9aa4b5", 16)
        self._load_groups()

    # ---- 数据加载 ----
    def _spawn(self, fn, on_done):
        self.list.clear()
        self.hint.setText("加载中…")
        w = _Worker(fn)
        w.done.connect(on_done)
        w.error.connect(lambda m: self.hint.setText(f"加载失败：{m}"))
        w.finished.connect(lambda x=w: self._workers.remove(x) if x in self._workers else None)
        self._workers.append(w)
        w.start()

    def _client(self):
        return get_client_for_account(self.account_id)

    def _load_groups(self):
        self.level = "groups"
        self.back_btn.hide()
        self.title.setText("百度群组（点群进文件夹）")
        self.use_btn.setEnabled(False)
        self.selected = None

        def fn():
            c = self._client()
            if c is None:
                raise RuntimeError("账号不可用")
            return c.list_groups()

        self._spawn(fn, self._show_groups)

    def _show_groups(self, groups):
        if not self._alive:
            return
        self.list.clear()
        for g in groups:
            it = QListWidgetItem("  " + g["name"])
            it.setIcon(make_icon("users", "#6b7a90", 16))
            it.setData(Qt.UserRole, {"type": "group", "gid": g["gid"], "gname": g["name"]})
            self.list.addItem(it)
        self.hint.setText(f"共 {len(groups)} 个群，点群进入")

    def _load_group_root(self, gid, gname):
        self.level = "grouproot"
        self.gid = gid
        self.gname = gname
        self.crumbs = [gname]
        self.folder_ref = None
        self.selected = None
        self.back_btn.show()
        self.title.setText(gname)
        self.use_btn.setEnabled(True)  # 可"同步整群"

        def fn():
            c = self._client()
            msgs = c.list_group_files(gid)
            # 展平：每个文件带其消息的 msg_id/from_uk
            out = []
            for m in msgs:
                for f in m["files"]:
                    out.append({**f, "msg_id": m["msg_id"], "from_uk": m.get("from_uk", "")})
            return out

        self._spawn(fn, self._show_items)

    def _load_folder(self, ref, name):
        self.level = "folder"
        self.folder_ref = {"msg_id": ref["msg_id"], "from_uk": ref["from_uk"], "fs_id": ref["fs_id"]}
        self.crumbs = self.crumbs + [name]
        self.selected = None
        self.back_btn.show()
        self.title.setText(" / ".join(self.crumbs))
        self.use_btn.setEnabled(True)

        def fn():
            c = self._client()
            kids = c.list_msg_folder(ref["from_uk"], ref["msg_id"], ref["fs_id"], self.gid)
            return [{**k, "msg_id": ref["msg_id"], "from_uk": ref["from_uk"]} for k in kids]

        self._spawn(fn, self._show_items)

    def _show_items(self, items):
        if not self._alive:
            return
        self.list.clear()
        dirs = [i for i in items if i.get("isdir")]
        files = [i for i in items if not i.get("isdir")]
        for f in dirs:
            it = QListWidgetItem("  " + f["server_filename"])
            it.setIcon(self._folder_icon)
            it.setData(Qt.UserRole, {"type": "folder", "item": f})
            self.list.addItem(it)
        for f in files:
            it = QListWidgetItem("  " + f["server_filename"])
            it.setIcon(self._file_icon)
            it.setData(Qt.UserRole, {"type": "file", "item": f})
            self.list.addItem(it)
        self.hint.setText(f"{len(dirs)} 个文件夹，{len(files)} 个文件")

    # ---- 交互 ----
    def _on_click(self, item):
        data = item.data(Qt.UserRole) or {}
        if data.get("type") == "folder":
            f = data["item"]
            self.selected = {
                "msg_id": f["msg_id"], "from_uk": f["from_uk"],
                "fs_id": f["fs_id"], "name": f["server_filename"],
            }
            self.use_btn.setEnabled(True)
            self.hint.setText(f"已选：{f['server_filename']}（双击可进入）")
        else:
            self.selected = None

    def _on_double(self, item):
        data = item.data(Qt.UserRole) or {}
        t = data.get("type")
        if t == "group":
            self._push_history()
            self._load_group_root(data["gid"], data["gname"])
        elif t == "folder":
            f = data["item"]
            self._push_history()
            self._load_folder(
                {"msg_id": f["msg_id"], "from_uk": f["from_uk"], "fs_id": f["fs_id"]},
                f["server_filename"],
            )

    def _push_history(self):
        self._history.append(
            (self.level, self.gid, self.gname, list(self.crumbs), self.folder_ref)
        )

    def go_back(self):
        if not self._history:
            return
        level, gid, gname, crumbs, folder_ref = self._history.pop()
        self.selected = None
        if level == "groups":
            self._load_groups()
        elif level == "grouproot":
            self._load_group_root(gid, gname)
        else:
            self.gid, self.gname = gid, gname
            # 回到某层文件夹：crumbs 已含到该层，folder_ref 为该层
            self.crumbs = crumbs[:-1] if crumbs else []
            self._load_folder(folder_ref, crumbs[-1] if crumbs else "")

    def _reload_current(self):
        if self.level == "groups":
            self._load_groups()
        elif self.level == "grouproot":
            self._load_group_root(self.gid, self.gname)
        elif self.folder_ref:
            name = self.crumbs[-1] if self.crumbs else ""
            self.crumbs = self.crumbs[:-1]
            self._load_folder(self.folder_ref, name)

    def _confirm(self):
        if self.selected:  # 选中了某个文件夹
            ref = self.selected
            display = " / ".join(self.crumbs + [ref["name"]])
            self.picked.emit({
                "gid": self.gid, "gname": self.gname,
                "msg_id": ref["msg_id"], "from_uk": ref["from_uk"], "fs_id": ref["fs_id"],
                "display": display,
            })
        elif self.level == "folder" and self.folder_ref:  # 当前所在文件夹
            self.picked.emit({
                "gid": self.gid, "gname": self.gname,
                "msg_id": self.folder_ref["msg_id"], "from_uk": self.folder_ref["from_uk"],
                "fs_id": self.folder_ref["fs_id"],
                "display": " / ".join(self.crumbs),
            })
        elif self.level == "grouproot":  # 整群
            self.picked.emit({"gid": self.gid, "gname": self.gname, "display": self.gname + "（整群）"})
        else:
            return
        self.close()

    def closeEvent(self, e):
        self._alive = False
        super().closeEvent(e)
