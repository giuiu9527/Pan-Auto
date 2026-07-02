"""基于系统 WebView2（Edge）的百度登录，替代内置 Chromium（QtWebEngine）。

在**独立子进程**里运行（pywebview 有自己的事件循环，不能和 PySide6 主循环共存）：
打开百度登录页 → 用户登录 → 抓取 Cookie（含 httpOnly 的 BDUSS）→ 以
`PANAUTO_RESULT:{json}` 打到 stdout，主程序读取。

缺少 WebView2 运行时时返回 code=webview2_missing，由主程序弹窗引导下载。
"""
from __future__ import annotations

import json
import sys
import time

LOGIN_URL = "https://pan.baidu.com/"
RESULT_PREFIX = "PANAUTO_RESULT:"
WEBVIEW2_DOWNLOAD = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"  # Evergreen 引导安装器


def webview2_installed() -> bool:
    """查注册表判断系统是否装了 WebView2 运行时（Win11 一般自带）。"""
    if sys.platform != "win32":
        return False
    import winreg

    guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    keys = [
        r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\\" + guid,
        r"SOFTWARE\Microsoft\EdgeUpdate\Clients\\" + guid,
    ]
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for k in keys:
            try:
                h = winreg.OpenKey(root, k)
                v, _ = winreg.QueryValueEx(h, "pv")
                if v and v not in ("0.0.0.0", ""):
                    return True
            except OSError:
                continue
    return False


def _flatten_cookies(raw) -> dict:
    """把 pywebview 返回的 cookie（http.cookiejar / dict / SimpleCookie）拍平成 {name: value}。"""
    out: dict[str, str] = {}
    if not raw:
        return out
    for c in raw:
        try:
            # http.cookiejar.Cookie
            name = getattr(c, "name", None)
            value = getattr(c, "value", None)
            if name is not None:
                out[name] = value or ""
                continue
        except Exception:  # noqa: BLE001
            pass
        if isinstance(c, dict):
            # {name, value} 或 SimpleCookie 序列化
            if "name" in c:
                out[str(c["name"])] = str(c.get("value", ""))
            else:
                for k, v in c.items():
                    out[str(k)] = str(getattr(v, "value", v))
    return out


def run() -> int:
    """子进程入口：打开登录窗口，成功后把 Cookie JSON 打到 stdout。"""
    result = {"ok": False, "cookies": {}, "code": "", "error": ""}

    if not webview2_installed():
        result["code"] = "webview2_missing"
        result["error"] = "系统未安装 WebView2 运行时"
        _emit(result)
        return 0

    try:
        import webview
    except Exception as e:  # noqa: BLE001
        result["code"] = "webview_import_failed"
        result["error"] = str(e)
        _emit(result)
        return 0

    window = webview.create_window(
        "登录百度网盘", LOGIN_URL, width=1000, height=720
    )

    def worker():
        deadline = time.time() + 300  # 5 分钟超时
        try:
            while time.time() < deadline:
                time.sleep(1.3)
                try:
                    cookies = _flatten_cookies(window.get_cookies())
                except Exception:  # noqa: BLE001
                    # 窗口被关闭等
                    break
                if "BDUSS" in cookies and cookies.get("BDUSS"):
                    result["ok"] = True
                    result["cookies"] = cookies
                    break
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e)
        finally:
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                pass

    try:
        webview.start(worker, gui="edgechromium")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "WebView2" in msg or "runtime" in msg.lower():
            result["code"] = "webview2_missing"
        else:
            result["code"] = "webview_failed"
        result["error"] = msg

    _emit(result)
    return 0


def _emit(result: dict) -> None:
    sys.stdout.write("\n" + RESULT_PREFIX + json.dumps(result) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(run())
