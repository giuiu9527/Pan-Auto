"""全局 QSS 样式：浅色蓝调、细腻质感，贴近 NeoPan。"""

# 调色板
PRIMARY = "#2f6bff"
PRIMARY_DARK = "#1f54e0"
PRIMARY_SOFT = "#eef4ff"
TEXT = "#2b3445"
MUTED = "#8b95a7"
BORDER = "#eaedf3"
BG = "#f4f6fb"
CARD = "#ffffff"

APP_QSS = f"""
* {{
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 13px;
    color: {TEXT};
    outline: none;
}}
QToolTip {{
    background: #2b3445; color: white; border: none;
    padding: 5px 8px; border-radius: 4px;
}}

QWidget#Root {{ background: {BG}; }}

/* ---- 标题栏 ---- */
QWidget#TitleBar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {PRIMARY}, stop:1 {PRIMARY_DARK});
}}
QLabel#TitleText {{ color: white; font-size: 13.5px; font-weight: 600; }}
QPushButton#WinBtn, QPushButton#WinBtnClose {{
    background: transparent; color: rgba(255,255,255,0.92); border: none;
    font-size: 14px; min-width: 44px; min-height: 36px; font-weight: 600;
}}
QPushButton#WinBtn:hover {{ background: rgba(255,255,255,0.20); color: white; }}
QPushButton#WinBtn:pressed {{ background: rgba(255,255,255,0.28); }}
QPushButton#WinBtnClose:hover {{ background: #e5484d; color: white; }}
QPushButton#WinBtnClose:pressed {{ background: #c7353a; }}

/* ---- 侧边栏 ---- */
QWidget#Sidebar {{ background: white; border-right: 1px solid {BORDER}; }}
QLabel#Brand {{ font-size: 16px; font-weight: 600; color: {TEXT}; }}
QPushButton#NavItem {{
    background: transparent; border: none; text-align: left;
    padding: 9px 12px; margin: 2px 10px;
    color: #5b6473; font-size: 13.5px; border-radius: 8px;
}}
QPushButton#NavItem:hover {{ background: #f2f5fb; }}
QPushButton#NavItem:checked {{
    background: {PRIMARY_SOFT}; color: {PRIMARY}; font-weight: 500;
}}

QWidget#AccountBox {{ background: transparent; border-top: 1px solid {BORDER}; }}
QFrame#AccountChip {{
    background: #fbfcfe; border: 1px solid {BORDER}; border-radius: 8px;
}}
QFrame#AccountChip:hover {{ border-color: {PRIMARY}; }}
QFrame#PickRow {{
    background: white; border: 1px solid #e3e8f1; border-radius: 7px;
}}
QFrame#PickRow:hover {{ border-color: {PRIMARY}; }}
QLabel#PickText {{ color: #5b6473; font-size: 13px; }}

/* ---- 卡片 ---- */
QFrame#Card, QFrame#QuickCard {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
}}
QFrame#QuickCard:hover {{ border-color: {PRIMARY}; }}

QLabel#PageTitle {{ font-size: 16px; font-weight: 600; color: {TEXT}; }}
QLabel#H1 {{ font-size: 23px; font-weight: 600; color: {TEXT}; }}
QLabel#H2 {{ font-size: 15px; font-weight: 700; color: {TEXT}; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#FieldLabel {{ font-weight: 500; color: #41495a; font-size: 13px; }}

/* ---- 输入控件 ---- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    background: #ffffff; border: 1px solid #e3e8f1; border-radius: 7px;
    padding: 8px 10px; selection-background-color: {PRIMARY};
    selection-color: white;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {PRIMARY}; background: #fcfdff;
}}
QLineEdit::placeholder {{ color: #aeb6c4; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    border: 1px solid {BORDER}; border-radius: 8px; background: white;
    selection-background-color: {PRIMARY_SOFT}; selection-color: {PRIMARY};
    padding: 4px;
}}

/* ---- 按钮 ---- */
QPushButton#Primary {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {PRIMARY}, stop:1 {PRIMARY_DARK});
    color: white; border: none; border-radius: 7px;
    padding: 9px 16px; font-weight: 500; font-size: 13px;
}}
QPushButton#Primary:hover {{ background: {PRIMARY_DARK}; }}
QPushButton#Primary:disabled {{ background: #b9c6e6; }}

QPushButton#Ghost {{
    background: white; color: #4a5365; border: 1px solid #e3e8f1;
    border-radius: 7px; padding: 6px 11px;
}}
QPushButton#Ghost:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}

QPushButton#Danger {{
    background: white; color: #e5484d; border: 1px solid #f3cccd;
    border-radius: 7px; padding: 6px 10px;
}}
QPushButton#Danger:hover {{ background: #fdeced; }}

QPushButton#Tab {{
    background: transparent; border: none; border-radius: 7px;
    padding: 7px 15px; color: #5b6473; font-weight: 600;
}}
QPushButton#Tab:checked {{ background: {PRIMARY}; color: white; }}

/* ---- 任务面板渐变头 ---- */
QFrame#SyncHeader {{
    border-radius: 8px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #19c4b6, stop:1 #2f8bff);
}}
QLabel#SyncHeaderTitle {{ color: white; font-size: 15px; font-weight: 600; }}
QLabel#SyncHeaderSub {{ color: rgba(255,255,255,0.85); font-size: 12px; }}
QLabel#RoundBadge {{
    color: white; font-weight: 700; font-size: 14px;
    border: 3px solid rgba(255,255,255,0.6); border-radius: 22px;
}}
QPushButton#IconBtn {{
    background: transparent; border: none; border-radius: 6px; padding: 4px;
}}
QPushButton#IconBtn:hover {{ background: #eef2f8; }}

QCheckBox {{ spacing: 8px; color: #3a4456; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border: 1px solid #cbd3e0;
    border-radius: 5px; background: white;
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY}; border-color: {PRIMARY};
}}

/* ---- 表格 / 列表 ---- */
QTableWidget, QListWidget, QPlainTextEdit#Log {{
    background: white; border: 1px solid {BORDER}; border-radius: 8px;
    gridline-color: #f0f2f7;
}}
QTableWidget::item, QListWidget::item {{ padding: 3px 6px; }}
QListWidget::item:hover {{ background: #f4f7fd; }}
QListWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
QHeaderView::section {{
    background: #f6f8fc; border: none; border-bottom: 1px solid {BORDER};
    padding: 7px 8px; font-weight: 600; color: #5b6473;
}}
QTableCornerButton::section {{ background: #f6f8fc; border: none; }}

/* ---- 状态栏 ---- */
QWidget#StatusBar {{ background: white; border-top: 1px solid {BORDER}; }}
QPushButton#StatusAction {{
    background: transparent; color: {PRIMARY}; border: none;
    padding: 3px 8px; font-size: 11.5px; font-weight: 600;
}}
QPushButton#StatusAction:hover {{ background: {PRIMARY_SOFT}; border-radius: 5px; }}
QLabel#Badge {{
    background: #18a957; color: white; border-radius: 5px;
    padding: 3px 9px; font-size: 11.5px; font-weight: 600;
}}
QLabel#MemberBadge {{
    background: #fff4d6; color: #b07b00; border-radius: 5px;
    padding: 2px 7px; font-size: 11px; font-weight: 600;
}}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #d3dae6; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #aab6c8; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""
