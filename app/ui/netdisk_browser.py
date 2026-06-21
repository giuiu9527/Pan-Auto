"""网盘文件浏览器：列出当前账号网盘里的文件 / 文件夹，可进入子目录。

用于验证「能否获取网盘文件」，同时给自动转存提供目标文件夹选择。
列目录在后台线程进行，避免界面卡顿。
"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
)
from PySide6.QtCore import Qt, QThread, Signal, QSize

from app.baidu.client import get_client_for_account
from app.ui.icons import make_icon


def _fmt_size(n: int) -> str:
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


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
            items = client.list_dir(self.path)
            self.done.emit(items)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class NetdiskBrowser(QWidget):
    """可独立使用的网盘浏览器。selected_changed 发出当前目录路径。"""

    selected_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.cwd = "/"
        self.account_id = None
        self.worker: ListWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # 工具行：当前路径 + 上级 + 刷新
        bar = QHBoxLayout()
        self.up_btn = QPushButton(" 上级")
        self.up_btn.setObjectName("Ghost")
        self.up_btn.setIcon(make_icon("up", "#4a5365", 15))
        self.up_btn.clicked.connect(self.go_up)
        bar.addWidget(self.up_btn)
        self.path_label = QLabel("/")
        self.path_label.setStyleSheet("color:#2f6bff; font-weight:600;")
        bar.addWidget(self.path_label, 1)
        self.refresh_btn = QPushButton(" 刷新")
        self.refresh_btn.setObjectName("Ghost")
        self.refresh_btn.setIcon(make_icon("refresh", "#4a5365", 15))
        self.refresh_btn.clicked.connect(self.reload)
        bar.addWidget(self.refresh_btn)
        root.addLayout(bar)

        self.list = QListWidget()
        self.list.setIconSize(QSize(18, 18))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(self._on_double)
        root.addWidget(self.list, 1)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        root.addWidget(self.status)

    def set_account(self, account_id):
        """切换浏览的账号并刷新到根目录。"""
        self.account_id = account_id
        self.load("/")

    def load(self, path: str = "/"):
        self.cwd = path or "/"
        self.path_label.setText(self.cwd)
        self.selected_changed.emit(self.cwd)
        self.up_btn.setEnabled(self.cwd != "/")
        self.list.clear()
        self.status.setText("加载中…")
        self.refresh_btn.setEnabled(False)
        self.worker = ListWorker(self.cwd, self.account_id)
        self.worker.done.connect(self._on_loaded)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def reload(self):
        self.load(self.cwd)

    def go_up(self):
        if self.cwd == "/":
            return
        parent = self.cwd.rsplit("/", 1)[0] or "/"
        self.load(parent)

    def _on_loaded(self, items: list):
        self.refresh_btn.setEnabled(True)
        self.list.clear()
        dirs = [i for i in items if i.get("isdir")]
        files = [i for i in items if not i.get("isdir")]
        folder_icon = make_icon("folder", "#f0a93b", 18)
        file_icon = make_icon("file", "#9aa4b5", 18)
        for it in dirs:
            li = QListWidgetItem(folder_icon, f"  {it['server_filename']}")
            li.setData(Qt.UserRole, it)
            self.list.addItem(li)
        for it in files:
            size = _fmt_size(it.get("size", 0))
            li = QListWidgetItem(file_icon, f"  {it['server_filename']}    {size}")
            li.setData(Qt.UserRole, it)
            self.list.addItem(li)
        self.status.setText(f"共 {len(dirs)} 个文件夹，{len(files)} 个文件")

    def _on_error(self, msg: str):
        self.refresh_btn.setEnabled(True)
        if msg == "未登录":
            self.status.setText("请先在「设置」中登录百度网盘")
        else:
            self.status.setText(f"加载失败：{msg}")

    def _on_double(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if data and data.get("isdir"):
            self.load(data["path"])

    def current_dir(self) -> str:
        return self.cwd

    def selected_files(self) -> list[dict]:
        items = []
        for item in self.list.selectedItems():
            data = item.data(Qt.UserRole)
            if data and not data.get("isdir"):
                items.append(data)
        return items

    def selected_file_paths(self) -> list[str]:
        return [x.get("path", "") for x in self.selected_files() if x.get("path")]
