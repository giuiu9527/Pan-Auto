"""鍏ㄥ眬閰嶇疆涓庤矾寰勩€?""
from pathlib import Path

APP_NAME = "Pan-Auto"
APP_TITLE = "Pan-Auto 路 缃戠洏鑷姩杞瓨"
APP_VERSION = "V1.0"

# 鐢ㄦ埛鏁版嵁鐩綍锛?APPDATA%\Pan-Auto 锛圵indows锛?import os

_base = os.environ.get("APPDATA") or str(Path.home())
DATA_DIR = Path(_base) / APP_NAME
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "pan_auto.db"

# 涓婚鑹诧紙鍙栬嚜鍙傝€?UI 鐨勮摑鑹茶皟锛?COLOR_PRIMARY = "#2f6bff"
COLOR_PRIMARY_DARK = "#1d4ed8"
COLOR_SIDEBAR_ACTIVE_BG = "#eaf2ff"
COLOR_CONTENT_BG = "#f5f7fb"
COLOR_BORDER = "#e5e9f0"

# 榛樿杞瓨鑺傛祦鍙傛暟锛堥槻椋庢帶锛?DEFAULT_MIN_DELAY = 3.0   # 姣忔杞瓨涔嬮棿鏈€灏忛棿闅旓紙绉掞級
DEFAULT_MAX_DELAY = 8.0   # 鏈€澶ч棿闅旓紙绉掞級锛屽疄闄呭彇鍖洪棿鍐呴殢鏈哄€?