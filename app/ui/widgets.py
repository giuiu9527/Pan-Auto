"""通用 UI 小部件与辅助函数。"""
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


def card(object_name: str = "Card") -> QFrame:
    f = QFrame()
    f.setObjectName(object_name)
    eff = QGraphicsDropShadowEffect()
    eff.setBlurRadius(12)
    eff.setOffset(0, 1)
    eff.setColor(QColor(45, 80, 160, 14))
    f.setGraphicsEffect(eff)
    return f


def label(text: str, object_name: str = "") -> QLabel:
    lb = QLabel(text)
    if object_name:
        lb.setObjectName(object_name)
    return lb


def field_label(text: str) -> QLabel:
    return label(text, "FieldLabel")


def field_group(text: str, widget: QWidget) -> QWidget:
    """标签紧贴控件的字段组（标签在上、间距 6px），用于表单。"""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)
    lay.addWidget(field_label(text))
    lay.addWidget(widget)
    return w


def vbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for x in widgets:
        if isinstance(x, QWidget):
            lay.addWidget(x)
    return w


def hline_spacer() -> QWidget:
    w = QWidget()
    w.setFixedHeight(1)
    w.setStyleSheet("background:#e5e9f0;")
    return w
