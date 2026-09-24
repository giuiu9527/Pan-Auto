"""清理通知区里的「幽灵托盘图标」（进程被强杀后残留的图标）。

Windows 只有在鼠标划过失效图标时才会把它移除。这里对托盘工具栏（含「^」隐藏区）
按网格发一遍 WM_MOUSEMOVE，效果等同鼠标划过，死图标立即消失。纯 ctypes，任何失败都静默。
"""
from __future__ import annotations

import ctypes
import sys


def refresh_tray_icons() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return _refresh()
    except Exception:  # noqa: BLE001
        return 0


def _refresh() -> int:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    FindWindowW = user32.FindWindowW
    FindWindowExW = user32.FindWindowExW
    FindWindowExW.restype = wintypes.HWND
    FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    GetClientRect = user32.GetClientRect
    SendMessageW = user32.SendMessageW
    SendMessageW.restype = ctypes.c_ssize_t
    SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
    WM_MOUSEMOVE = 0x0200

    toolbars = []
    tray = FindWindowW("Shell_TrayWnd", None)
    if tray:
        notify = FindWindowExW(tray, None, "TrayNotifyWnd", None)
        if notify:
            pager = FindWindowExW(notify, None, "SysPager", None)
            tb = FindWindowExW(pager or notify, None, "ToolbarWindow32", None)
            if tb:
                toolbars.append(tb)
    overflow = FindWindowW("NotifyIconOverflowWindow", None)
    if overflow:
        tb = FindWindowExW(overflow, None, "ToolbarWindow32", None)
        if tb:
            toolbars.append(tb)

    touched = 0
    for hwnd in toolbars:
        rect = wintypes.RECT()
        if not GetClientRect(hwnd, ctypes.byref(rect)):
            continue
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            continue
        step = 8
        for x in range(0, w, step):
            for y in range(0, h, step):
                SendMessageW(hwnd, WM_MOUSEMOVE, 0, (y << 16) | (x & 0xFFFF))
        touched += 1
    return touched
