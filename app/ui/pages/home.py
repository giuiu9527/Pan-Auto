"""概览页：账号 / 任务状态一眼看清 + 快捷入口。"""
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QFrame,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Signal

from app import db
from app import theme
from app.config import APP_NAME
from app.netdisk import provider_label
from app.ui.icons import make_pixmap
from app.ui.widgets import page_root, PageHeader, label, fmt_ago, ElidedLabel


class StatCard(QFrame):
    def __init__(self, icon: str, color: str, title: str):
        super().__init__()
        self.setObjectName("StatCard")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(12)
        ic = QLabel()
        ic.setFixedSize(40, 40)
        ic.setAlignment(Qt.AlignCenter)
        # 注意：Qt 样式表里 8 位 #RRGGBBAA 会被当成 #AARRGGBB，必须用 rgba()
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        ic.setStyleSheet(f"background:rgba({r},{g},{b},0.13); border-radius:10px;")
        ic.setPixmap(make_pixmap(icon, color, 20))
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.value = QLabel("—")
        self.value.setObjectName("StatValue")
        col.addWidget(self.value)
        t = QLabel(title)
        t.setObjectName("StatLabel")
        col.addWidget(t)
        lay.addLayout(col, 1)

    def set(self, value: str):
        self.value.setText(value)


class QuickCard(QFrame):
    clicked = Signal(str)

    def __init__(self, icon: str, title: str, desc: str, target: str):
        super().__init__()
        self.setObjectName("QuickCard")
        self.target = target
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(74)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)
        ic = QLabel()
        ic.setFixedSize(40, 40)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet(f"background:{theme.PRIMARY_SOFT}; border-radius:10px;")
        ic.setPixmap(make_pixmap(icon, theme.PRIMARY, 20))
        lay.addWidget(ic)
        box = QVBoxLayout()
        box.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet("font-size:14px; font-weight:600;")
        d = ElidedLabel(desc, "Hint")
        box.addWidget(t)
        box.addWidget(d)
        lay.addLayout(box, 1)
        arrow = QLabel()
        arrow.setPixmap(make_pixmap("chevron-right", theme.MUTED_2, 16))
        lay.addWidget(arrow)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.target)
        super().mouseReleaseEvent(e)


class HomePage(QWidget):
    navigate = Signal(str)

    def __init__(self):
        super().__init__()
        root = page_root(self)

        self.header = PageHeader("概览", "")
        root.addWidget(self.header)

        # 统计卡
        stats = QHBoxLayout()
        stats.setSpacing(12)
        self.stat_tasks = StatCard("sync", theme.PRIMARY, "同步任务（启用 / 全部）")
        self.stat_files = StatCard("check-circle", theme.SUCCESS, "累计已同步文件")
        self.stat_last = StatCard("clock", theme.WARNING, "最近一次同步")
        self.stat_err = StatCard("alert", theme.DANGER, "24 小时内错误")
        for s in (self.stat_tasks, self.stat_files, self.stat_last, self.stat_err):
            s.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            stats.addWidget(s, 1)
        root.addLayout(stats)

        head = QLabel("快捷入口")
        head.setObjectName("SectionTitle")
        root.addWidget(head)

        grid = QGridLayout()
        grid.setSpacing(12)
        items = [
            ("sync", "自动同步", "分享链接 / 群文件夹定时增量转存", "auto"),
            ("users", "好友 / 群文件", "手动挑选好友、群里发来的文件转存", "friends"),
            ("edit", "批量重命名", "按关键字规则批量改名", "rename"),
            ("eraser", "广告清理", "扫描并删除命中关键词的广告文件", "adclean"),
            ("target", "广告插入", "把自己的广告文件复制到多个文件夹", "ad"),
            ("logs", "运行记录", "查看每次同步的成功 / 跳过 / 失败", "logs"),
        ]
        for i, (ic, t, d, tg) in enumerate(items):
            c = QuickCard(ic, t, d, tg)
            c.clicked.connect(self.navigate.emit)
            grid.addWidget(c, i // 3, i % 3)
        root.addLayout(grid)
        root.addStretch()

        tip = label(
            f"{APP_NAME} 会在后台按任务频率自动同步；关闭窗口可最小化到托盘继续运行。",
            "Hint",
        )
        tip.setWordWrap(True)
        root.addWidget(tip)
        self.refresh()

    def on_shown(self):
        self.refresh()

    def refresh(self):
        try:
            acc = db.get_active_account()
            n = db.account_count()
            st = db.task_counts()
        except Exception:  # noqa: BLE001
            return
        if acc and acc.get("username"):
            extra = f"，共 {n} 个账号" if n > 1 else ""
            self.header.set_subtitle(
                f"当前账号：{acc['username']}（{provider_label(acc.get('provider'))}）{extra}"
            )
        else:
            self.header.set_subtitle("还没有登录网盘账号，请先到「设置」添加")
        self.stat_tasks.set(f"{st['enabled']} / {st['total']}")
        self.stat_files.set(str(st["transferred"]))
        self.stat_last.set(fmt_ago(st["last_run"]))
        self.stat_err.set(str(st["errors_24h"]))
