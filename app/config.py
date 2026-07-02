"""全局配置与路径。"""
from pathlib import Path

APP_NAME = "Pan-Auto"
APP_TITLE = "Pan-Auto · 网盘自动转存"
APP_VERSION = "V2.1"

# 用户数据目录：%APPDATA%\Pan-Auto （Windows）
import os

_base = os.environ.get("APPDATA") or str(Path.home())
DATA_DIR = Path(_base) / APP_NAME
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "pan_auto.db"

# 主题色（取自参考 UI 的蓝色调）
COLOR_PRIMARY = "#2f6bff"
COLOR_PRIMARY_DARK = "#1d4ed8"
COLOR_SIDEBAR_ACTIVE_BG = "#eaf2ff"
COLOR_CONTENT_BG = "#f5f7fb"
COLOR_BORDER = "#e5e9f0"

# 默认转存节流参数（防风控）
DEFAULT_MIN_DELAY = 3.0   # 每次转存之间最小间隔（秒）
DEFAULT_MAX_DELAY = 8.0   # 最大间隔（秒），实际取区间内随机值
