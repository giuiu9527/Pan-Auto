"""运行记录页：按级别筛选 + 关键字搜索 + 清空。"""
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QButtonGroup,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QPlainTextEdit,
)
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt, QTimer

from app import db
from app import theme
from app.ui.widgets import (
    page_root, PageHeader, button, setup_table, table_frame, pill_cell, fmt_time,
)

LEVELS = [
    ("", "全部"),
    ("ok", "成功"),
    ("info", "信息"),
    ("skip", "跳过"),
    ("error", "失败"),
]
LEVEL_KIND = {"ok": "success", "skip": "warning", "error": "danger", "info": "info"}
LEVEL_TEXT = {"ok": "成功", "skip": "跳过", "error": "失败", "info": "信息"}


class LogsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.level = ""
        root = page_root(self)

        self.header = PageHeader("运行记录", "每次同步 / 改名 / 清理的详细结果，最新在最上面")
        refresh = button("刷新", "Ghost", "refresh")
        refresh.clicked.connect(self.reload)
        self.header.add_action(refresh)
        clear = button("清空记录", "Danger", "trash")
        clear.clicked.connect(self.clear_all)
        self.header.add_action(clear)
        root.addWidget(self.header)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        for key, text in LEVELS:
            b = QPushButton(text)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(key == "")
            b.clicked.connect(lambda _=False, k=key: self.set_level(k))
            self.chip_group.addButton(b)
            bar.addWidget(b)
        bar.addSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索记录内容…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(320)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self.reload)
        self.search.textChanged.connect(lambda _t: self._debounce.start())
        bar.addWidget(self.search, 1)
        bar.addStretch()
        root.addLayout(bar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["时间", "状态", "内容"])
        setup_table(self.table, row_height=36, selectable=True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 86)
        root.addWidget(table_frame(self.table), 1)

        # 选中一条记录 → 在这里看完整内容（长的失败原因在表格里会被省略号截掉），可直接选中复制
        self.detail = QPlainTextEdit()
        self.detail.setObjectName("Log")
        self.detail.setReadOnly(True)
        self.detail.setFixedHeight(96)
        self.detail.setPlaceholderText("点上面任意一条记录，这里显示完整内容（可选中复制）")
        root.addWidget(self.detail)
        self.table.itemSelectionChanged.connect(self._show_detail)

        self.reload()

    def _show_detail(self):
        row = self.table.currentRow()
        if row < 0:
            self.detail.clear()
            return
        ts = self.table.item(row, 0)
        msg = self.table.item(row, 2)
        self.detail.setPlainText((ts.text() if ts else "") + "\n" + (msg.text() if msg else ""))

    def on_shown(self):
        self.reload()

    def set_level(self, key: str):
        self.level = key
        self.reload()

    def reload(self):
        logs = db.list_logs(400, self.level or None, self.search.text().strip())
        self.detail.clear()
        self.table.setRowCount(0)
        self.table.setRowCount(len(logs))
        for r, lg in enumerate(logs):
            ts = QTableWidgetItem(fmt_time(lg["ts"], "%Y-%m-%d %H:%M:%S"))
            ts.setForeground(QColor(theme.MUTED))
            self.table.setItem(r, 0, ts)
            lvl = lg["level"]
            self.table.setCellWidget(r, 1, pill_cell(LEVEL_TEXT.get(lvl, lvl), LEVEL_KIND.get(lvl, "muted")))
            text = (lg["message"] or "").replace("⏱ ", "").replace("⏱", "")
            msg = QTableWidgetItem(text)
            msg.setToolTip(text)
            if lvl == "error":
                msg.setForeground(QColor(theme.DANGER))
            self.table.setItem(r, 2, msg)
        self.header.set_subtitle(
            f"显示最近 {len(logs)} 条" + ("（已筛选）" if self.level or self.search.text().strip() else "")
            + "，最新在最上面"
        )

    def clear_all(self):
        if QMessageBox.question(self, "清空记录", "确定清空全部运行记录？（不影响去重记录）") != QMessageBox.Yes:
            return
        db.clear_logs()
        self.reload()
