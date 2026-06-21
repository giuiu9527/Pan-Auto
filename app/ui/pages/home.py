"""主页：品牌区 + 快捷操作卡片。"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QFrame,
)
from PySide6.QtCore import Qt, Signal

from app.ui.icons import make_pixmap


class QuickCard(QFrame):
    clicked = Signal(str)

    def __init__(self, icon: str, title: str, desc: str, target: str):
        super().__init__()
        self.setObjectName("QuickCard")
        self.target = target
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)

        ic = QLabel()
        ic.setFixedSize(40, 40)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet("background:#eef4ff; border-radius:8px;")
        ic.setPixmap(make_pixmap(icon, "#2f6bff", 22))
        lay.addWidget(ic)

        box = QVBoxLayout()
        box.setSpacing(3)
        t = QLabel(title)
        t.setStyleSheet("font-size:14.5px; font-weight:600;")
        d = QLabel(desc)
        d.setObjectName("Muted")
        box.addWidget(t)
        box.addWidget(d)
        lay.addLayout(box)
        lay.addStretch()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.target)
        super().mouseReleaseEvent(e)


class HomePage(QWidget):
    navigate = Signal(str)

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 18)
        root.setSpacing(14)

        brand = QVBoxLayout()
        brand.setSpacing(6)
        logo_row = QHBoxLayout()
        logo_row.addStretch()
        logo = QLabel()
        logo.setPixmap(make_pixmap("cloud", "#2f6bff", 34))
        logo_row.addWidget(logo)
        title = QLabel("Pan-Auto")
        title.setObjectName("H1")
        logo_row.addWidget(title)
        logo_row.addStretch()
        brand.addLayout(logo_row)
        sub = QLabel("百度网盘自动转存工具 · 定时把好友分享与链接转存到你的网盘")
        sub.setObjectName("Muted")
        sub.setAlignment(Qt.AlignCenter)
        brand.addWidget(sub)
        root.addLayout(brand)

        head = QLabel("快捷操作")
        head.setObjectName("H2")
        root.addWidget(head)

        grid = QGridLayout()
        grid.setSpacing(12)
        items = [
            ("sync", "自动转存", "添加分享链接，定时自动转存", "auto"),
            ("edit", "批量重命名", "按关键字规则批量改名", "rename"),
            ("target", "广告插入", "把广告文件插入到目标文件夹", "ad"),
            ("users", "好友消息", "转存好友聊天发来的文件夹", "friends"),
            ("logs", "转存记录", "查看每次转存的成功/失败日志", "logs"),
        ]
        for i, (ic, t, d, tg) in enumerate(items):
            c = QuickCard(ic, t, d, tg)
            c.clicked.connect(self.navigate.emit)
            grid.addWidget(c, i // 2, i % 2)
        root.addLayout(grid)
        root.addStretch()
