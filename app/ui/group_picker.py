"""群文件夹选择器（下拉弹窗）。

点击按钮弹出：群列表 → 双击群进入群文件根目录 → 逐级双击进文件夹 →
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
    QListWidget,
    QListWidgetItem,
)
from PySide6.QtCore import Qt, QThread, Signal, QSize

from app import theme
from app.baidu.client import get_client_for_account
from app.ui.icons import make_icon
from app.ui.widgets import icon_button, button, ElidedLabel


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
        self.gid = ""
        self.gname = ""
        self.crumbs = []
        self.folder_ref = None
        self.selected = None
        self._history = []
        self.level = "groups"

        self.setObjectName("Card")
        self.setFixedSize(480, 420)
        self.setStyleSheet(
            f"QFrame#Card{{background:{theme.CARD};border:1px solid {theme.BORDER_STRONG};border-radius:12px;}}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.back_btn = icon_button("arrow-left", theme.TEXT_2, "返回上一级")
        self.back_btn.clicked.connect(self.go_back)
        self.back_btn.hide()
        head.addWidget(self.back_btn)
        self.title = ElidedLabel("选择百度群", mode=Qt.ElideMiddle)
        self.title.setStyleSheet(f"font-weight:600; color:{theme.TEXT};")
        head.addWidget(self.title, 1)
        refresh = icon_button("refresh", theme.TEXT_2, "刷新")
        refresh.clicked.connect(self._reload_current)
        head.addWidget(refresh)
        root.addLayout(head)

        self.list = QListWidget()
        self.list.setIconSize(QSize(16, 16))
        self.list.setStyleSheet(f"QListWidget{{border:1px solid {theme.BORDER}; border-radius:8px; padding:4px;}}")
        self.list.itemClicked.connect(self._on_click)
        self.list.itemDoubleClicked.connect(self._on_double)
        root.addWidget(self.list, 1)

        self.hint = QLabel("双击群进入；单击选中文件夹，双击进入下级")
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        foot = QHBoxLayout()
        foot.addStretch()
        self.use_btn = button("同步此文件夹", "Primary", "check")
        self.use_btn.clicked.connect(self._confirm)
        self.use_btn.setEnabled(False)
        foot.addWidget(self.use_btn)
        root.addLayout(foot)

        self._folder_icon = make_icon("folder", "#F0A93B", 16)
        self._file_icon = make_icon("file", theme.MUTED_2, 16)
        self._group_icon = make_icon("users", "#7C3AED", 16)
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
        self.title.setText("选择百度群")
        self.use_btn.setEnabled(False)
        self.use_btn.setText("同步此文件夹")
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
            it = QListWidgetItem(self._group_icon, g["name"])
            it.setData(Qt.UserRole, {"type": "group", "gid": g["gid"], "gname": g["name"]})
            self.list.addItem(it)
        self.hint.setText(f"共 {len(groups)} 个群，双击进入群文件")

    def _load_group_root(self, gid, gname):
        self.level = "grouproot"
        self.gid = gid
        self.gname = gname
        self.crumbs = [gname]
        self.folder_ref = None
        self.selected = None
        self.back_btn.show()
        self.title.setText(gname)
        self.use_btn.setEnabled(True)
        self.use_btn.setText("同步整群")

        def fn():
            c = self._client()
            msgs = c.list_group_files(gid)
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
        self.use_btn.setText("同步当前文件夹")

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
            it = QListWidgetItem(self._folder_icon, f["server_filename"])
            it.setData(Qt.UserRole, {"type": "folder", "item": f})
            self.list.addItem(it)
        for f in files:
            it = QListWidgetItem(self._file_icon, f["server_filename"])
            it.setData(Qt.UserRole, {"type": "file", "item": f})
            self.list.addItem(it)
        self.hint.setText(f"{len(dirs)} 个文件夹，{len(files)} 个文件 · 单击选中文件夹，双击进入")

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
            self.use_btn.setText("同步选中文件夹")
            self.hint.setText(f"已选：{f['server_filename']}（双击可进入）")
        else:
            self.selected = None
            if self.level == "folder":
                self.use_btn.setText("同步当前文件夹")
            elif self.level == "grouproot":
                self.use_btn.setText("同步整群")

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
        if self.selected:
            ref = self.selected
            display = " / ".join(self.crumbs + [ref["name"]])
            self.picked.emit({
                "gid": self.gid, "gname": self.gname,
                "msg_id": ref["msg_id"], "from_uk": ref["from_uk"], "fs_id": ref["fs_id"],
                "display": display,
            })
        elif self.level == "folder" and self.folder_ref:
            self.picked.emit({
                "gid": self.gid, "gname": self.gname,
                "msg_id": self.folder_ref["msg_id"], "from_uk": self.folder_ref["from_uk"],
                "fs_id": self.folder_ref["fs_id"],
                "display": " / ".join(self.crumbs),
            })
        elif self.level == "grouproot":
            self.picked.emit({"gid": self.gid, "gname": self.gname, "display": self.gname + "（整群）"})
        else:
            return
        self.close()

    def closeEvent(self, e):
        self._alive = False
        super().closeEvent(e)
