"""全局视觉系统：设计令牌 + QSS。

原则（这次重做界面的核心约束）：
- 字号只用整数 px（12 / 13 / 14 / 16 / 18 / 22），不用 11.5px 这种会被四舍五入
  后导致行高不一致、文字顶到边的值。
- 所有输入控件 / 按钮统一 36px 高（min-height + 内边距），文字永远不会被裁掉。
- 表格不换行、超长省略号（在各页里 setWordWrap(False)），行高 44px。
- 状态只用颜色文字或 StatusPill，不用 ● ○ ⟳ 🔗 这类 emoji / 特殊符号（YaHei
  没有这些字形，会回退到 Segoe UI Emoji/Symbol，行高被撑大、文字被裁）。
"""
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent / "ui" / "assets"
_CHECK_SVG = (_ASSETS / "check.svg").as_posix()
_CHEVRON_SVG = (_ASSETS / "chevron.svg").as_posix()

# ---- 调色板 ----
PRIMARY = "#2F6BFF"
PRIMARY_DARK = "#1F54E0"
PRIMARY_SOFT = "#EAF1FF"
PRIMARY_SOFT2 = "#DCE7FF"

BG = "#F3F5F9"
CARD = "#FFFFFF"
BORDER = "#E6EAF2"
BORDER_STRONG = "#D5DBE7"

TEXT = "#1F2937"
TEXT_2 = "#4B5563"
MUTED = "#6B7280"
MUTED_2 = "#9CA3AF"

SUCCESS = "#16A34A"
SUCCESS_SOFT = "#E7F7EC"
WARNING = "#D97706"
WARNING_SOFT = "#FFF4E0"
DANGER = "#DC2626"
DANGER_SOFT = "#FDECEC"
INFO = "#2563EB"
INFO_SOFT = "#E8F0FF"

FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif'

APP_QSS = f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: 13px;
    color: {TEXT};
    outline: none;
}}
QWidget {{ background: transparent; }}
QToolTip {{
    background: #111827; color: white; border: none;
    padding: 6px 9px; border-radius: 6px; font-size: 12px;
}}
QWidget#Root {{ background: {BG}; }}
QStackedWidget#Content {{ background: {BG}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ---- 标题栏 ---- */
QWidget#TitleBar {{ background: {PRIMARY}; }}
QLabel#TitleText {{ color: white; font-size: 13px; font-weight: 600; }}
QLabel#TitleSub {{ color: rgba(255,255,255,0.72); font-size: 12px; }}
QPushButton#WinBtn, QPushButton#WinBtnClose {{
    background: transparent; border: none; min-width: 46px; min-height: 38px;
}}
QPushButton#WinBtn:hover {{ background: rgba(255,255,255,0.18); }}
QPushButton#WinBtn:pressed {{ background: rgba(255,255,255,0.28); }}
QPushButton#WinBtnClose:hover {{ background: #E5484D; }}
QPushButton#WinBtnClose:pressed {{ background: #C7353A; }}

/* ---- 侧边栏 ---- */
QWidget#Sidebar {{ background: {CARD}; border-right: 1px solid {BORDER}; }}
QLabel#Brand {{ font-size: 16px; font-weight: 700; color: {TEXT}; }}
QLabel#BrandSub {{ font-size: 11px; color: {MUTED_2}; }}
QLabel#NavSection {{
    font-size: 11px; font-weight: 600; color: {MUTED_2};
    padding: 10px 18px 4px 18px;
}}
QPushButton#NavItem {{
    background: transparent; border: none; border-left: 3px solid transparent;
    text-align: left; padding: 0 14px 0 15px; min-height: 40px;
    color: {TEXT_2}; font-size: 13px; border-radius: 0;
}}
QPushButton#NavItem:hover {{ background: #F4F6FA; color: {TEXT}; }}
QPushButton#NavItem:checked {{
    background: {PRIMARY_SOFT}; color: {PRIMARY}; font-weight: 600;
    border-left: 3px solid {PRIMARY};
}}
QWidget#Sidebar[compact="true"] QPushButton#NavItem {{
    padding: 0; text-align: center; border-left: 3px solid transparent;
}}
QFrame#AccountCard {{
    background: #F8FAFD; border: 1px solid {BORDER}; border-radius: 10px;
}}
QFrame#AccountCard:hover {{ border-color: {PRIMARY}; background: {PRIMARY_SOFT}; }}
QLabel#AccountName {{ font-weight: 600; font-size: 13px; color: {TEXT}; }}
QLabel#AccountSub {{ font-size: 12px; color: {MUTED}; }}

/* ---- 页面 ---- */
QLabel#PageTitle {{ font-size: 18px; font-weight: 700; color: {TEXT}; }}
QLabel#PageSubtitle {{ font-size: 13px; color: {MUTED}; }}
QLabel#SectionTitle {{ font-size: 14px; font-weight: 600; color: {TEXT}; }}
QLabel#H1 {{ font-size: 22px; font-weight: 700; color: {TEXT}; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Hint {{ color: {MUTED}; font-size: 12px; }}
QLabel#FieldLabel {{ font-weight: 600; color: {TEXT_2}; font-size: 12px; }}
QLabel#StatValue {{ font-size: 22px; font-weight: 700; color: {TEXT}; }}
QLabel#StatLabel {{ font-size: 12px; color: {MUTED}; }}

QFrame#Card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#CardFlat {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#QuickCard {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#QuickCard:hover {{ border-color: {PRIMARY}; background: #FBFCFF; }}
QFrame#StatCard {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#Divider {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#InfoBox {{
    background: {INFO_SOFT}; border: 1px solid #C9DAFF; border-radius: 8px;
}}
QLabel#InfoBoxText {{ color: #1E40AF; font-size: 12px; }}
QFrame#WarnBox {{
    background: {WARNING_SOFT}; border: 1px solid #F6D9A5; border-radius: 8px;
}}
QLabel#WarnBoxText {{ color: #92400E; font-size: 12px; }}

/* ---- 输入控件：统一 36px ---- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {CARD}; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
    padding: 0 10px; min-height: 34px; max-height: 34px;
    selection-background-color: {PRIMARY}; selection-color: white;
}}
QPlainTextEdit, QTextEdit {{
    background: {CARD}; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
    padding: 6px 8px; selection-background-color: {PRIMARY}; selection-color: white;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {PRIMARY};
}}
QLineEdit:read-only {{ background: #F8FAFD; color: {TEXT_2}; }}
QLineEdit:disabled, QComboBox:disabled {{ background: #F3F4F6; color: {MUTED_2}; }}
QLineEdit::placeholder {{ color: {MUTED_2}; }}
QComboBox {{ combobox-popup: 0; }}
QComboBox::drop-down {{ border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url("{_CHEVRON_SVG}"); width: 12px; height: 12px; margin-right: 8px; }}
/* 下拉弹层：普通列表（combobox-popup:0），行高 32px，悬停/选中浅蓝底 */
QComboBox QAbstractItemView {{
    border: 1px solid {BORDER_STRONG}; border-radius: 8px; background: {CARD};
    selection-background-color: {PRIMARY_SOFT}; selection-color: {PRIMARY};
    padding: 4px; outline: none;
}}
QComboBox QAbstractItemView::item {{
    min-height: 32px; padding: 0 10px; border-radius: 6px; color: {TEXT};
}}
QComboBox QAbstractItemView::item:hover {{ background: #F4F7FD; color: {TEXT}; }}
QComboBox QAbstractItemView::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
QComboBox#Compact {{ min-height: 28px; max-height: 28px; padding: 0 8px; font-size: 12px; }}
QComboBox#Compact::drop-down {{ width: 22px; }}

/* ---- 按钮 ---- */
QPushButton {{ border-radius: 8px; }}
QPushButton#Primary {{
    background: {PRIMARY}; color: white; border: 1px solid {PRIMARY};
    padding: 0 16px; min-height: 34px; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {PRIMARY_DARK}; border-color: {PRIMARY_DARK}; }}
QPushButton#Primary:pressed {{ background: #1A48C4; }}
QPushButton#Primary:disabled {{ background: #B9C8EE; border-color: #B9C8EE; color: white; }}
QPushButton#PrimaryLarge {{
    background: {PRIMARY}; color: white; border: 1px solid {PRIMARY};
    padding: 0 18px; min-height: 42px; font-weight: 600; font-size: 14px;
}}
QPushButton#PrimaryLarge:hover {{ background: {PRIMARY_DARK}; }}
QPushButton#PrimaryLarge:disabled {{ background: #B9C8EE; border-color: #B9C8EE; }}
QPushButton#Ghost {{
    background: {CARD}; color: {TEXT_2}; border: 1px solid {BORDER_STRONG};
    padding: 0 14px; min-height: 34px; font-weight: 500;
}}
QPushButton#Ghost:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; background: #FBFCFF; }}
QPushButton#Ghost:pressed {{ background: {PRIMARY_SOFT}; }}
QPushButton#Ghost:disabled {{ color: {MUTED_2}; border-color: {BORDER}; }}
QPushButton#Danger {{
    background: {CARD}; color: {DANGER}; border: 1px solid #F3C4C4;
    padding: 0 14px; min-height: 34px; font-weight: 500;
}}
QPushButton#Danger:hover {{ background: {DANGER_SOFT}; border-color: {DANGER}; }}
QPushButton#Danger:disabled {{ color: {MUTED_2}; border-color: {BORDER}; }}
QPushButton#Link {{
    background: transparent; color: {PRIMARY}; border: none; padding: 0 6px;
    min-height: 28px; font-weight: 600;
}}
QPushButton#Link:hover {{ text-decoration: underline; }}
QPushButton#IconBtn {{
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; padding: 0;
}}
QPushButton#IconBtn:hover {{ background: #EEF2F8; border-color: {BORDER}; }}
QPushButton#IconBtn:pressed {{ background: {PRIMARY_SOFT2}; }}
QPushButton#IconBtn:disabled {{ background: transparent; }}
QPushButton#SquareBtn {{
    background: {CARD}; border: 1px solid {BORDER_STRONG}; border-radius: 8px;
    min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; padding: 0;
}}
QPushButton#SquareBtn:hover {{ border-color: {PRIMARY}; background: #FBFCFF; }}

/* 分段选项卡（同一控件组内的互斥切换） */
QFrame#SegmentBar {{ background: #EEF1F6; border-radius: 9px; }}
QPushButton#Segment {{
    background: transparent; border: none; border-radius: 7px;
    padding: 0 14px; min-height: 30px; color: {TEXT_2}; font-weight: 500;
}}
QPushButton#Segment:hover {{ color: {TEXT}; }}
QPushButton#Segment:checked {{ background: {CARD}; color: {PRIMARY}; font-weight: 600; }}

/* 大块模式按钮（广告插入 随机/指定） */
QPushButton#ModeTab {{
    background: {CARD}; border: 1px solid {BORDER_STRONG}; border-radius: 10px;
    padding: 0 14px; min-height: 40px; color: {TEXT_2}; font-weight: 600;
}}
QPushButton#ModeTab:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
QPushButton#ModeTab:checked {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; border-color: {PRIMARY}; }}

/* 过滤芯片（日志页） */
QPushButton#Chip {{
    background: {CARD}; border: 1px solid {BORDER_STRONG}; border-radius: 14px;
    padding: 0 12px; min-height: 26px; max-height: 26px; color: {TEXT_2}; font-size: 12px;
}}
QPushButton#Chip:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
QPushButton#Chip:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; color: white; font-weight: 600; }}

/* 状态药丸 */
QLabel#Pill {{ border-radius: 11px; padding: 0 10px; min-height: 22px; max-height: 22px; font-size: 12px; font-weight: 600; }}
QLabel#Pill[kind="success"] {{ background: {SUCCESS_SOFT}; color: {SUCCESS}; }}
QLabel#Pill[kind="warning"] {{ background: {WARNING_SOFT}; color: {WARNING}; }}
QLabel#Pill[kind="danger"]  {{ background: {DANGER_SOFT}; color: {DANGER}; }}
QLabel#Pill[kind="info"]    {{ background: {INFO_SOFT}; color: {INFO}; }}
QLabel#Pill[kind="muted"]   {{ background: #EEF0F4; color: {MUTED}; }}
QLabel#Pill[kind="primary"] {{ background: {PRIMARY}; color: white; }}

QLabel#CountBadge {{
    background: {PRIMARY_SOFT}; color: {PRIMARY}; border-radius: 10px;
    padding: 0 8px; min-height: 20px; max-height: 20px; font-size: 12px; font-weight: 700;
}}
QLabel#VersionBadge {{
    background: #EEF0F4; color: {TEXT_2}; border-radius: 6px;
    padding: 0 8px; min-height: 22px; max-height: 22px; font-size: 12px; font-weight: 600;
}}

/* 可点击的选择行（广告插入） */
QFrame#PickRow {{ background: {CARD}; border: 1px solid {BORDER_STRONG}; border-radius: 10px; }}
QFrame#PickRow:hover {{ border-color: {PRIMARY}; background: #FBFCFF; }}
QLabel#PickText {{ color: {TEXT_2}; }}

/* ---- 勾选框 ---- */
QCheckBox {{ spacing: 8px; color: {TEXT_2}; min-height: 24px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border: 1px solid {BORDER_STRONG};
    border-radius: 5px; background: {CARD};
}}
QCheckBox::indicator:hover {{ border-color: {PRIMARY}; }}
QCheckBox::indicator:checked {{
    background: {PRIMARY}; border-color: {PRIMARY}; image: url("{_CHECK_SVG}");
}}
QCheckBox::indicator:disabled {{ background: #F3F4F6; }}

/* ---- 表格 / 列表 / 树 ---- */
QTableWidget, QTableView, QListWidget, QTreeWidget {{
    background: {CARD}; border: none; gridline-color: {BORDER};
    selection-background-color: {PRIMARY_SOFT}; selection-color: {TEXT};
    alternate-background-color: #FAFBFD;
}}
QTableWidget::item, QTableView::item {{ padding: 0 10px; border-bottom: 1px solid #F1F3F7; }}
QTableWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {TEXT}; }}
QTableWidget::item:hover {{ background: #F7F9FC; }}
QListWidget::item {{ padding: 0 10px; min-height: 34px; border-radius: 6px; }}
QListWidget::item:hover {{ background: #F4F7FD; }}
QListWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
QTreeWidget::item {{ min-height: 30px; padding: 0 4px; }}
QTreeWidget::item:hover {{ background: #F4F7FD; }}
QTreeWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {TEXT}; }}
QTreeWidget::branch {{ background: transparent; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: #F6F8FB; border: none; border-bottom: 1px solid {BORDER};
    padding: 0 10px; min-height: 36px; font-weight: 600; font-size: 12px; color: {MUTED};
}}
QHeaderView::section:first {{ border-top-left-radius: 8px; }}
QHeaderView::section:last {{ border-top-right-radius: 8px; }}
QTableCornerButton::section {{ background: #F6F8FB; border: none; }}
QFrame#TableFrame {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QPlainTextEdit#Log {{ background: #F8FAFD; border: 1px solid {BORDER}; border-radius: 8px; }}

/* ---- 分割条 / 状态栏 / 滚动条 ---- */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: 14px; }}
QWidget#StatusBar {{ background: {CARD}; border-top: 1px solid {BORDER}; }}
QLabel#StatusText {{ color: {MUTED}; font-size: 12px; }}
QPushButton#StatusAction {{
    background: transparent; color: {PRIMARY}; border: none;
    padding: 0 8px; min-height: 24px; font-size: 12px; font-weight: 600; border-radius: 6px;
}}
QPushButton#StatusAction:hover {{ background: {PRIMARY_SOFT}; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px 1px; }}
QScrollBar::handle:vertical {{ background: #DCE1EA; border-radius: 3px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: #B4BCCB; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 1px 2px; }}
QScrollBar::handle:horizontal {{ background: #DCE1EA; border-radius: 3px; min-width: 36px; }}
QScrollBar::handle:horizontal:hover {{ background: #B4BCCB; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- 对话框 ---- */
QMessageBox {{ background: {CARD}; }}
QMessageBox QLabel {{ color: {TEXT}; font-size: 13px; }}
QMessageBox QPushButton, QProgressDialog QPushButton, QDialog QPushButton#DlgBtn {{
    background: {CARD}; color: {TEXT_2}; border: 1px solid {BORDER_STRONG};
    padding: 0 16px; min-height: 32px; min-width: 72px; border-radius: 8px;
}}
QMessageBox QPushButton:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
QMessageBox QPushButton:default {{ background: {PRIMARY}; color: white; border-color: {PRIMARY}; }}
QProgressBar {{ border: 1px solid {BORDER}; border-radius: 6px; background: #F1F3F7; text-align: center; min-height: 14px; }}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 5px; }}
QMenu {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
"""
