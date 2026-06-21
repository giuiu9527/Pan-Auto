"""占位页：尚未实现的功能。"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

from app.ui.icons import make_pixmap


class PlaceholderPage(QWidget):
    def __init__(self, title: str, desc: str = "该功能将在后续版本提供"):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        t = QLabel(title)
        t.setObjectName("PageTitle")
        root.addWidget(t)
        root.addStretch()
        icon = QLabel()
        icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(make_pixmap("users", "#c2cad8", 56))
        root.addWidget(icon)
        d = QLabel(desc)
        d.setObjectName("Muted")
        d.setAlignment(Qt.AlignCenter)
        d.setStyleSheet("margin-top:12px;")
        root.addWidget(d)
        root.addStretch()
