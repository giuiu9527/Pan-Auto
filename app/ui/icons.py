"""矢量线性图标（Feather 风格），渲染成 QIcon / QPixmap，可着色。

避免使用 emoji（不同系统观感不一），统一为细线图标，贴近 NeoPan。
"""
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from app.config import DATA_DIR


def _dpr() -> float:
    """当前屏幕缩放比，用于高清渲染图标。"""
    app = QApplication.instance()
    if app is not None:
        scr = app.primaryScreen()
        if scr is not None:
            return max(1.0, scr.devicePixelRatio())
    return 1.0

# 24x24，stroke 用占位符 {c} 替换颜色
_PATHS = {
    "home": '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
            '<path d="M9 22V12h6v10"/>',
    "sync": '<path d="M23 4v6h-6"/><path d="M1 20v-6h6"/>'
            '<path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10"/>'
            '<path d="M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>'
             '<circle cx="9" cy="7" r="4"/>'
             '<path d="M23 21v-2a4 4 0 0 0-3-3.87"/>'
             '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "logs": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
            '<path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/>'
            '<path d="M10 9H8"/>',
    "settings": '<path d="M4 21v-7"/><path d="M4 10V3"/><path d="M12 21v-9"/>'
                '<path d="M12 8V3"/><path d="M20 21v-5"/><path d="M20 12V3"/>'
                '<path d="M1 14h6"/><path d="M9 8h6"/><path d="M17 16h6"/>',
    "target": '<circle cx="12" cy="12" r="9"/>'
              '<circle cx="12" cy="12" r="5"/>'
              '<circle cx="12" cy="12" r="1"/>',
    "shuffle": '<path d="M16 3h5v5"/><path d="M4 20L21 3"/>'
               '<path d="M21 16v5h-5"/><path d="M15 15l6 6"/>'
               '<path d="M4 4l5 5"/>',
    "search": '<circle cx="11" cy="11" r="8"/>'
              '<path d="M21 21l-4.35-4.35"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/>'
             '<path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16'
             'a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24'
             'a2 2 0 0 0-1.79 1.11z"/>',
    "cloud": '<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9'
              'a2 2 0 0 1 2 2z"/>',
    "file": '<path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>'
            '<path d="M13 2v7h7"/>',
    "up": '<path d="M12 19V5"/><path d="M5 12l7-7 7 7"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "trash": '<path d="M3 6h18"/>'
             '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
             '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "play": '<path d="M5 3l14 9-14 9z"/>',
    "pause": '<rect x="6" y="4" width="4" height="16" rx="1"/>'
             '<rect x="14" y="4" width="4" height="16" rx="1"/>',
    "edit": '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>'
            '<path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4z"/>',
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "user": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>'
            '<circle cx="12" cy="7" r="4"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
            '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "refresh": '<path d="M23 4v6h-6"/><path d="M1 20v-6h6"/>'
               '<path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10"/>'
               '<path d="M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    "switch": '<path d="M16 3h5v5"/><path d="M4 20L21 3"/>'
              '<path d="M21 16v5h-5"/><path d="M15 15l6 6"/><path d="M4 4l5 5"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'
              '<path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
}


def _svg(name: str, color: str, width: float = 2.0) -> bytes:
    inner = _PATHS.get(name, "")
    fill = color if name in ("play", "pause") else "none"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="{fill}" stroke="{color}" stroke-width="{width}" '
        f'stroke-linecap="round" stroke-linejoin="round">{inner}</svg>'
    ).encode("utf-8")


# 把着色后的 SVG 落地成文件，交给 QIcon 矢量渲染（任意 DPI 都清晰）
_ICON_DIR = DATA_DIR / "_icons"
_ICON_DIR.mkdir(parents=True, exist_ok=True)
_path_cache: dict[str, str] = {}


def _svg_path(name: str, color: str, width: float) -> str:
    key = f"{name}_{color.lstrip('#')}_{str(width).replace('.', '')}"
    if key not in _path_cache:
        p = _ICON_DIR / (key + ".svg")
        p.write_bytes(_svg(name, color, width))
        _path_cache[key] = str(p)
    return _path_cache[key]


def make_icon(name: str, color: str = "#4b5563", size: int = 20,
              width: float = 2.0) -> QIcon:
    # QIcon 直接读取 SVG，按控件 iconSize 在原生分辨率下矢量渲染
    return QIcon(_svg_path(name, color, width))


def make_pixmap(name: str, color: str = "#4b5563", size: int = 20,
                width: float = 2.0) -> QPixmap:
    icon = make_icon(name, color, size, width)
    dpr = _dpr()
    try:
        return icon.pixmap(QSize(size, size), dpr)
    except TypeError:
        pm = icon.pixmap(QSize(size, size))
        pm.setDevicePixelRatio(dpr)
        return pm
