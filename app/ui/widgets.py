"""通用 UI 小部件与辅助函数（全站共用的排版积木）。

所有页面统一用这里的积木拼，保证标题、卡片、表单、表格、状态的观感一致；
文字相关的控件默认做了「不裁切」处理（自动换行 / 省略号 / 固定行高）。
"""
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QButtonGroup,
    QTableWidget,
    QAbstractItemView,
    QHeaderView,
    QSizePolicy,
    QSplitter,
    QScrollArea,
    QComboBox,
)
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QFontMetrics

from app.ui.icons import make_icon, make_pixmap
from app import theme


class ComboBox(QComboBox):
    """全站统一的下拉框：弹层至少和最长选项一样宽（以前弹层和下拉框等宽，窄下拉框里选项被截断）。

    配合 theme 里的 `combobox-popup: 0` + QListView 样式：行高 32px、悬停/选中为浅蓝底，
    不再是系统菜单式的 24px 紧凑行 + 深蓝高亮。
    """

    def showPopup(self):
        fm = self.fontMetrics()
        longest = max((fm.horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        view = self.view()
        view.setMinimumWidth(max(self.width(), longest + 56))   # 左右内边距 + 滚动条余量
        super().showPopup()


# ---- 基础 ----
def card(object_name: str = "Card") -> QFrame:
    f = QFrame()
    f.setObjectName(object_name)
    return f


def label(text: str, object_name: str = "") -> QLabel:
    lb = QLabel(text)
    if object_name:
        lb.setObjectName(object_name)
    return lb


def field_label(text: str) -> QLabel:
    return label(text, "FieldLabel")


def _wrap_policy(lb: QLabel) -> None:
    """换行标签：横向不撑宽父容器，但保留 heightForWidth（否则布局会少算行高、内容重叠）。"""
    sp = lb.sizePolicy()
    sp.setHorizontalPolicy(QSizePolicy.Ignored)
    sp.setVerticalPolicy(QSizePolicy.Preferred)
    sp.setHeightForWidth(True)
    lb.setSizePolicy(sp)
    lb.setMinimumWidth(40)


def hint(text: str) -> QLabel:
    """说明文字：自动换行，永远不会把父容器撑宽 / 被裁掉。"""
    lb = label(text, "Hint")
    lb.setWordWrap(True)
    _wrap_policy(lb)
    return lb


def muted(text: str) -> QLabel:
    lb = label(text, "Muted")
    lb.setWordWrap(True)
    _wrap_policy(lb)
    return lb


def field_group(text: str, widget: QWidget, hint_text: str = "") -> QWidget:
    """标签在上、控件在下的表单字段组。"""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    lay.addWidget(field_label(text))
    lay.addWidget(widget)
    w.hint_label = None
    if hint_text:
        w.hint_label = hint(hint_text)
        lay.addWidget(w.hint_label)
    return w


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("Divider")
    f.setFixedHeight(1)
    return f


def elide(lb: QLabel, text: str, width: int, mode=Qt.ElideRight) -> None:
    """把文字按可用宽度省略后设给 QLabel，完整文字放 tooltip。"""
    fm = QFontMetrics(lb.font())
    lb.setText(fm.elidedText(text, mode, max(20, width)))
    lb.setToolTip(text if fm.horizontalAdvance(text) > width else "")


class ElidedLabel(QLabel):
    """随宽度自动省略的单行标签（不换行、不撑宽父容器）。"""

    def __init__(self, text: str = "", object_name: str = "", mode=Qt.ElideRight):
        super().__init__()
        self._full = text
        self._mode = mode
        if object_name:
            self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(24)
        self.setToolTip(text)

    def setText(self, text: str):  # noqa: N802
        self._full = text or ""
        self.setToolTip(self._full)
        self._apply()

    def fullText(self) -> str:  # noqa: N802
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply()

    def _apply(self):
        fm = QFontMetrics(self.font())
        super().setText(fm.elidedText(self._full, self._mode, max(16, self.width() - 2)))


# ---- 按钮 ----
def icon_button(name: str, color: str = theme.TEXT_2, tip: str = "", size: int = 18,
                width: float = 2.0) -> QPushButton:
    """32×32 无边框图标按钮（表格操作列 / 工具栏）。"""
    b = QPushButton()
    b.setObjectName("IconBtn")
    b.setIcon(make_icon(name, color, size, width=width))
    b.setIconSize(QSize(size, size))
    b.setFixedSize(32, 32)
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


def square_button(name: str, tip: str = "", color: str = theme.TEXT_2) -> QPushButton:
    """34×34 带边框图标按钮，放在输入框右侧（选文件夹等）。"""
    b = QPushButton()
    b.setObjectName("SquareBtn")
    b.setIcon(make_icon(name, color, 16))
    b.setIconSize(QSize(16, 16))
    b.setFixedSize(34, 34)
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


def button(text: str, kind: str = "Ghost", icon: str = "", icon_color: str = "") -> QPushButton:
    """文字按钮。kind: Primary / PrimaryLarge / Ghost / Danger / Link"""
    b = QPushButton(text)
    b.setObjectName(kind)
    b.setCursor(Qt.PointingHandCursor)
    if icon:
        color = icon_color or ("#ffffff" if kind.startswith("Primary") else theme.TEXT_2)
        if kind == "Danger" and not icon_color:
            color = theme.DANGER
        b.setIcon(make_icon(icon, color, 16))
        b.setIconSize(QSize(16, 16))
    return b


def input_with_button(line_edit, btn) -> QWidget:
    """输入框 + 右侧方按钮 的组合行。"""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    lay.addWidget(line_edit, 1)
    lay.addWidget(btn)
    return w


class SegmentBar(QFrame):
    """分段切换（互斥），如「分享同步 / 群组同步」。changed(key)"""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], current: str = ""):
        super().__init__()
        self.setObjectName("SegmentBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in options:
            b = QPushButton(text)
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._on_click(k))
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b, 1)
        self.current = current or options[0][0]
        self.buttons[self.current].setChecked(True)

    def _on_click(self, key: str):
        if key == self.current:
            return
        self.current = key
        self.changed.emit(key)

    def set_current(self, key: str, emit: bool = False):
        if key not in self.buttons:
            return
        self.current = key
        self.buttons[key].setChecked(True)
        if emit:
            self.changed.emit(key)


# ---- 页面骨架 ----
class PageHeader(QWidget):
    """页面标题区：标题 + 副标题（左），操作按钮（右）。"""

    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = label(title, "PageTitle")
        col.addWidget(self.title)
        self.subtitle = label(subtitle, "PageSubtitle")
        self.subtitle.setVisible(bool(subtitle))
        col.addWidget(self.subtitle)
        lay.addLayout(col, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        lay.addLayout(self.actions)

    def add_action(self, w: QWidget) -> QWidget:
        self.actions.addWidget(w)
        return w

    def set_subtitle(self, text: str):
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))


def page_root(page: QWidget, margins=(24, 20, 24, 20), spacing: int = 14) -> QVBoxLayout:
    lay = QVBoxLayout(page)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


def scroll_wrap(inner: QWidget) -> QScrollArea:
    """把表单包进纵向滚动区：宽度跟随、只纵向滚动。"""
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QScrollArea.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sa.setWidget(inner)
    return sa


class TwoColumn(QSplitter):
    """左（表单）右（结果）双栏，用户可拖动分隔条；左栏有合理的最小/最大宽度。"""

    def __init__(self, left: QWidget, right: QWidget, left_width: int = 430,
                 left_min: int = 380, left_max: int = 560):
        super().__init__(Qt.Horizontal)
        self.setChildrenCollapsible(False)
        self.setHandleWidth(14)
        left.setMinimumWidth(left_min)
        left.setMaximumWidth(left_max)
        right.setMinimumWidth(360)
        self.addWidget(left)
        self.addWidget(right)
        self.setStretchFactor(0, 0)
        self.setStretchFactor(1, 1)
        self.setSizes([left_width, 900])


# ---- 状态 ----
class StatusPill(QLabel):
    """彩色状态药丸：kind = success / warning / danger / info / muted / primary"""

    def __init__(self, text: str = "", kind: str = "muted"):
        super().__init__(text)
        self.setObjectName("Pill")
        self.setAlignment(Qt.AlignCenter)
        self.set(text, kind)

    def set(self, text: str, kind: str = "muted"):
        self.setText(text)
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)


def pill_cell(text: str, kind: str) -> QWidget:
    """表格单元里的状态药丸（居中、不撑高）。"""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(8, 0, 8, 0)
    lay.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
    lay.addWidget(StatusPill(text, kind))
    return w


class InfoBox(QFrame):
    """浅色提示框（info / warn）。"""

    def __init__(self, text: str, kind: str = "info"):
        super().__init__()
        self.setObjectName("InfoBox" if kind == "info" else "WarnBox")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(make_pixmap("info" if kind == "info" else "alert",
                                 "#1E40AF" if kind == "info" else "#92400E", 15))
        ic.setAlignment(Qt.AlignTop)
        lay.addWidget(ic)
        self.text = label(text, "InfoBoxText" if kind == "info" else "WarnBoxText")
        self.text.setWordWrap(True)
        _wrap_policy(self.text)
        lay.addWidget(self.text, 1)


class EmptyState(QWidget):
    """空态：大图标 + 标题 + 说明。"""

    def __init__(self, icon: str, title: str, desc: str = ""):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(6)
        lay.addStretch()
        ic = QLabel()
        ic.setAlignment(Qt.AlignCenter)
        ic.setPixmap(make_pixmap(icon, "#C3CAD8", 52, width=1.6))
        lay.addWidget(ic)
        t = QLabel(title)
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet(f"font-size:14px; font-weight:600; color:{theme.TEXT_2};")
        lay.addWidget(t)
        self.desc = QLabel(desc)
        self.desc.setAlignment(Qt.AlignCenter)
        self.desc.setWordWrap(True)
        self.desc.setObjectName("Hint")
        lay.addWidget(self.desc)
        lay.addStretch()


# ---- 表格 ----
def setup_table(table: QTableWidget, row_height: int = 44, selectable: bool = False,
                stretch_last: bool = False) -> None:
    """统一表格观感：无行号、不换行 + 省略号、整行选择、固定行高。"""
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.ElideRight)
    table.setFrameShape(QFrame.NoFrame)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setFocusPolicy(Qt.NoFocus)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(
        QAbstractItemView.SingleSelection if selectable else QAbstractItemView.NoSelection
    )
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    hh = table.horizontalHeader()
    hh.setHighlightSections(False)
    hh.setStretchLastSection(stretch_last)
    hh.setMinimumSectionSize(56)
    hh.setFixedHeight(36)
    hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)


def table_frame(table: QWidget) -> QFrame:
    """给表格套一层圆角描边容器。"""
    f = QFrame()
    f.setObjectName("TableFrame")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(1, 1, 1, 1)
    lay.addWidget(table)
    return f


def two_line_cell(title: str, sub: str, icon: str = "", icon_color: str = "") -> QWidget:
    """表格单元：两行文字（主标题 + 灰色副标题），可带左侧图标；超长省略。"""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(10, 0, 8, 0)
    lay.setSpacing(8)
    if icon:
        ic = QLabel()
        ic.setPixmap(make_pixmap(icon, icon_color or theme.MUTED, 16))
        ic.setFixedWidth(18)
        lay.addWidget(ic)
    col = QVBoxLayout()
    col.setSpacing(0)
    col.setContentsMargins(0, 0, 0, 0)
    t = ElidedLabel(title)
    t.setStyleSheet("font-weight:600;")
    s = ElidedLabel(sub, "Hint")
    col.addWidget(t)
    col.addWidget(s)
    lay.addLayout(col, 1)
    w.setToolTip(f"{title}\n{sub}")
    return w


def actions_cell(buttons: list[QPushButton]) -> QWidget:
    """表格操作列：一排图标按钮。"""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(4, 0, 4, 0)
    lay.setSpacing(2)
    lay.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
    for b in buttons:
        lay.addWidget(b)
    return w


def fmt_size(n) -> str:
    if not n:
        return ""
    x = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024:
            return f"{x:.0f} {unit}" if unit == "B" else f"{x:.1f} {unit}"
        x /= 1024
    return f"{x:.1f} PB"


def fmt_time(ts, fmt: str = "%m-%d %H:%M") -> str:
    if not ts:
        return ""
    import time as _t

    try:
        return _t.strftime(fmt, _t.localtime(ts))
    except (ValueError, OSError, OverflowError):
        return ""


def fmt_ago(ts) -> str:
    """相对时间：刚刚 / 5 分钟前 / 3 小时前 / 2 天前"""
    if not ts:
        return "从未"
    import time as _t

    d = int(_t.time() - ts)
    if d < 60:
        return "刚刚"
    if d < 3600:
        return f"{d // 60} 分钟前"
    if d < 86400:
        return f"{d // 3600} 小时前"
    return f"{d // 86400} 天前"
