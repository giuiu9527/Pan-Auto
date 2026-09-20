"""网盘文件浏览器：列出当前账号网盘里的文件 / 文件夹，可进入子目录。

给自动转存 / 重命名 / 广告页选择目标文件夹用；列目录在后台线程进行。
"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QLineEdit,
)
from PySide6.QtCore import Qt, QThread, Signal, QSize

from app import theme
from app.netdisk import get_client_for_account
from app.quark.client import display_path, is_quark_path
from app.ui.icons import make_icon
from app.ui.widgets import icon_button, ElidedLabel, fmt_size


class ListWorker(QThread):
    done = Signal(list)
    error = Signal(str)

    def __init__(self, path: str, account_id):
        super().__init__()
        self.path = path
        self.account_id = account_id

    def run(self):
        client = get_client_for_account(self.account_id)
        if client is None:
            self.error.emit("未登录")
            return
        try:
            self.done.emit(client.list_dir(self.path))
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class NetdiskBrowser(QWidget):
    """可独立使用的网盘浏览器。selected_changed 发出当前目录路径。"""

    selected_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.cwd = "/"
        self._history: list[str] = []
        self.account_id = None
        self._items: list[dict] = []
        # 保留所有在跑的线程引用，直到它们 finished，避免 QThread 运行中被 GC
        # 销毁（Qt 会 abort 进程）。_seq 用于只采纳最后一次加载的结果。
        self._workers: list[ListWorker] = []
        self._seq = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.up_btn = icon_button("arrow-left", theme.TEXT_2, "上一级")
        self.up_btn.clicked.connect(self.go_up)
        bar.addWidget(self.up_btn)
        self.path_label = ElidedLabel("/", mode=Qt.ElideMiddle)
        self.path_label.setStyleSheet(f"color:{theme.PRIMARY}; font-weight:600;")
        bar.addWidget(self.path_label, 1)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("筛选当前目录…")
        self.filter.setClearButtonEnabled(True)
        self.filter.setFixedWidth(170)
        self.filter.textChanged.connect(lambda _t: self._render())
        bar.addWidget(self.filter)
        self.refresh_btn = icon_button("refresh", theme.TEXT_2, "刷新")
        self.refresh_btn.clicked.connect(self.reload)
        bar.addWidget(self.refresh_btn)
        root.addLayout(bar)

        self.list = QListWidget()
        self.list.setIconSize(QSize(18, 18))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setFrameShape(QListWidget.NoFrame)
        self.list.setStyleSheet(f"QListWidget{{border:1px solid {theme.BORDER}; border-radius:8px; padding:4px;}}")
        self.list.itemDoubleClicked.connect(self._on_double)
        root.addWidget(self.list, 1)

        self.status = QLabel("")
        self.status.setObjectName("Hint")
        root.addWidget(self.status)
        self._folder_icon = make_icon("folder", "#F0A93B", 18)
        self._file_icon = make_icon("file", theme.MUTED_2, 18)

    def set_account(self, account_id):
        self.account_id = account_id
        self._history.clear()
        self.load("/")

    def load(self, path: str = "/"):
        self.cwd = path or "/"
        shown = display_path(self.cwd)
        self.path_label.setText(shown)
        self.selected_changed.emit(shown)
        self.up_btn.setEnabled(bool(self._history) or self.cwd != "/")
        self.list.clear()
        self._items = []
        self.status.setText("加载中…")
        self.refresh_btn.setEnabled(False)
        self._seq += 1
        seq = self._seq
        worker = ListWorker(self.cwd, self.account_id)
        worker.done.connect(lambda items, s=seq: s == self._seq and self._on_loaded(items))
        worker.error.connect(lambda msg, s=seq: s == self._seq and self._on_error(msg))
        worker.finished.connect(lambda w=worker: self._drop_worker(w))
        self._workers.append(worker)
        worker.start()

    def _drop_worker(self, w):
        if w in self._workers:
            self._workers.remove(w)

    def reload(self):
        self.load(self.cwd)

    def go_up(self):
        if self._history:
            self.load(self._history.pop())
            return
        if is_quark_path(self.cwd):
            self.load("/")
            return
        if self.cwd == "/":
            return
        parent = self.cwd.rsplit("/", 1)[0] or "/"
        self.load(parent)

    def _on_loaded(self, items: list):
        self.refresh_btn.setEnabled(True)
        self._items = items
        self._render()

    def _render(self):
        self.list.clear()
        q = self.filter.text().strip().lower()
        items = [i for i in self._items if not q or q in (i.get("server_filename") or "").lower()]
        dirs = [i for i in items if i.get("isdir")]
        files = [i for i in items if not i.get("isdir")]
        for it in dirs:
            li = QListWidgetItem(self._folder_icon, it["server_filename"])
            li.setData(Qt.UserRole, it)
            li.setToolTip(it["server_filename"])
            self.list.addItem(li)
        for it in files:
            size = fmt_size(it.get("size", 0))
            li = QListWidgetItem(self._file_icon, f"{it['server_filename']}    {size}")
            li.setData(Qt.UserRole, it)
            li.setToolTip(it["server_filename"])
            self.list.addItem(li)
        self.status.setText(f"{len(dirs)} 个文件夹，{len(files)} 个文件" + ("（已筛选）" if q else "") + " · 双击进入文件夹")

    def _on_error(self, msg: str):
        self.refresh_btn.setEnabled(True)
        if msg == "未登录":
            self.status.setText("请先在「设置」中登录网盘账号")
        else:
            self.status.setText(f"加载失败：{msg}")

    def _on_double(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if data and data.get("isdir"):
            self._history.append(self.cwd)
            self.filter.clear()
            self.load(data["path"])

    def current_dir(self) -> str:
        return display_path(self.cwd)

    def selected_files(self) -> list[dict]:
        items = []
        for item in self.list.selectedItems():
            data = item.data(Qt.UserRole)
            if data and not data.get("isdir"):
                items.append(data)
        return items

    def selected_file_paths(self) -> list[str]:
        return [x.get("path", "") for x in self.selected_files() if x.get("path")]
