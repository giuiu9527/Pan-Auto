"""转存记录页：展示运行日志。"""
import time

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt

from app import db

LEVEL_COLORS = {
    "ok": "#16a34a",
    "skip": "#a16207",
    "error": "#dc2626",
    "info": "#2563eb",
}
LEVEL_TEXT = {"ok": "成功", "skip": "跳过", "error": "失败", "info": "信息"}


class LogsPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("转存记录")
        title.setObjectName("PageTitle")
        head.addWidget(title)
        head.addStretch()
        refresh = QPushButton("刷新")
        refresh.setObjectName("Ghost")
        refresh.clicked.connect(self.reload)
        head.addWidget(refresh)
        root.addLayout(head)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["时间", "状态", "内容"])
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        root.addWidget(self.table)

        self.reload()

    def reload(self):
        logs = db.list_logs(300)
        self.table.setRowCount(0)
        for lg in logs:
            r = self.table.rowCount()
            self.table.insertRow(r)
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(lg["ts"]))
            self.table.setItem(r, 0, QTableWidgetItem(ts))
            lvl = QTableWidgetItem(LEVEL_TEXT.get(lg["level"], lg["level"]))
            lvl.setForeground(QColor(LEVEL_COLORS.get(lg["level"], "#374151")))
            self.table.setItem(r, 1, lvl)
            self.table.setItem(r, 2, QTableWidgetItem(lg["message"]))
        if not logs:
            self.table.setRowCount(1)
            empty = QTableWidgetItem("暂无记录")
            empty.setForeground(QColor("#9ca3af"))
            self.table.setItem(0, 2, empty)
