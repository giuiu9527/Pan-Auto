"""开机自启管理（Windows 注册表）。"""
import sys
import winreg
from pathlib import Path

from app.config import APP_NAME

_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _exe_path() -> str:
    """获取当前程序的可执行路径（打包版用 exe，源码版用 pythonw + main.py）。"""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    # 源码运行：用 pythonw 无控制台启动
    venv = Path(sys.executable).parent
    pythonw = venv / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    main_py = Path(__file__).resolve().parents[1] / "main.py"
    return f'"{pythonw}" "{main_py}"'


def is_autostart_enabled() -> bool:
    """检查是否已设置开机自启。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    """启用或禁用开机自启。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _exe_path())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass
