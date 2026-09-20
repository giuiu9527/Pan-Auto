"""在线更新协议（客户端侧，纯逻辑，不含界面）。

方案按 `D:\\Test Code\\软件包更新方式.md`：服务端只是 OpenList 上的一个目录
`/Pan-Auto`，里面固定名的 `update.json` 清单 + 带版本号的 zip + 同名 `.sha256`。
客户端：读清单 → 按段比版本 → 下载 zip 到 %TEMP% → 校验 SHA-256 → 杀主程序 →
写 .bat（UTF-8 带 BOM）→ `cmd.exe /c` 启动 → 退出；.bat 解压、xcopy 覆盖、重启主程序。

主程序只负责启动旁边的 `update.exe`（`launch_updater`）；下载/安装都在 `update.exe`
（`updater_main.py` → `app/ui/updater_window.py`）里做，因为主程序运行时不能覆盖自己。
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Callable, Optional

from app.config import APP_NAME, APP_VERSION_PLAIN

# ★ OpenList 上 /Pan-Auto 目录的公开只读分享链接（在 OpenList 网页手动开分享后填入）。
#   清单 = 该链接 + update.json；下载 = 该链接 + 清单里的 archive；校验 = 下载地址 + .sha256
#   发布脚本 ci/win/publish_openlist.ps1 会从这里读取同一个值做发布后自检，别在两处各写一份。
UPDATE_PUBLIC_BASE = ""  # TODO: 形如 "http://209.146.116.186:5244/sd/xxxxxxxx/"，开好分享后填入
# 开发调试可用环境变量临时指到本地 http.server（发布包里不要设置它）
_ENV_OVERRIDE = "PAN_AUTO_UPDATE_BASE"

MAIN_EXE_NAME = "Pan-Auto.exe"
UPDATER_EXE_NAME = "update.exe"
ARCHIVE_PREFIX = "Pan-Auto-v"
ARCHIVE_SUFFIX = "-portable.zip"

REQUEST_TIMEOUT = 20


class UpdateError(RuntimeError):
    pass


# ---- 地址 / 路径 ----
def public_base() -> str:
    base = os.environ.get(_ENV_OVERRIDE) or UPDATE_PUBLIC_BASE
    base = (base or "").strip()
    if base and not base.endswith("/"):
        base += "/"
    return base


def is_configured() -> bool:
    return bool(public_base())


def app_dir() -> Path:
    """主程序所在目录（打包版 = exe 目录；源码版 = 仓库根）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def main_exe_path() -> Path:
    return app_dir() / MAIN_EXE_NAME


# ---- 版本 ----
def parse_version(text: str) -> tuple[int, ...]:
    """'v3.0.1' → (3, 0, 1)。按段转整数，非数字段取前导数字，缺段补 0。"""
    s = (text or "").strip().lstrip("vV")
    parts = []
    for seg in s.split("."):
        digits = ""
        for ch in seg:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def _exe_file_version(path: Path) -> str:
    """读 exe 的 VERSIONINFO（GetFileVersionInfoW）；读不到返回空串。"""
    if sys.platform != "win32" or not path.exists():
        return ""
    try:
        from ctypes import wintypes

        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
            return ""
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
            return ""

        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [
                ("dwSignature", wintypes.DWORD),
                ("dwStrucVersion", wintypes.DWORD),
                ("dwFileVersionMS", wintypes.DWORD),
                ("dwFileVersionLS", wintypes.DWORD),
                ("dwProductVersionMS", wintypes.DWORD),
                ("dwProductVersionLS", wintypes.DWORD),
            ]

        ffi = ctypes.cast(ptr, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        ms, ls = ffi.dwFileVersionMS, ffi.dwFileVersionLS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}"
    except Exception:  # noqa: BLE001
        return ""


def local_version() -> str:
    """本地版本：优先主程序 exe 的 VERSIONINFO，其次 VERSION 文件，最后编译进来的常量。"""
    v = _exe_file_version(main_exe_path())
    if v and v != "0.0.0":
        return v
    for p in (app_dir() / "_internal" / "VERSION", app_dir() / "VERSION"):
        try:
            t = p.read_text(encoding="utf-8").strip().lstrip("vV")
            if t:
                return t
        except OSError:
            pass
    return APP_VERSION_PLAIN


# ---- 网络 ----
def _http_get(url: str, timeout: float = REQUEST_TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}-updater", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise UpdateError(f"HTTP {e.code}：{url}") from e
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(f"网络请求失败：{getattr(e, 'reason', e)}") from e


def fetch_manifest() -> dict:
    """读 update.json；缺 version / archive 一律拒绝（不猜）。"""
    if not is_configured():
        raise UpdateError("尚未配置更新地址（UPDATE_PUBLIC_BASE 为空）")
    raw = _http_get(public_base() + "update.json")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as e:
        raise UpdateError("更新清单不是合法 JSON") from e
    if not isinstance(data, dict):
        raise UpdateError("更新清单格式错误")
    version = str(data.get("version") or "").strip()
    archive = str(data.get("archive") or "").strip()
    if not version or not archive:
        raise UpdateError("更新清单缺少 version 或 archive，已拒绝")
    if "/" in archive or "\\" in archive or ".." in archive:
        raise UpdateError("更新清单里的 archive 必须是文件名")
    return {
        "version": version.lstrip("vV"),
        "archive": archive,
        "notes": str(data.get("notes") or ""),
        "published_at": str(data.get("published_at") or ""),
    }


def check() -> dict:
    """{'local','remote','has_update','notes','archive'}"""
    m = fetch_manifest()
    local = local_version()
    return {
        "local": local,
        "remote": m["version"],
        "has_update": is_newer(m["version"], local),
        "notes": m["notes"],
        "archive": m["archive"],
        "published_at": m["published_at"],
    }


def download_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "Pan-Auto-update"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download_archive(
    archive: str,
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
) -> Path:
    """下载 zip 到 %TEMP%\\Pan-Auto-update\\（先写 .part，完成再改名）。返回 zip 路径。"""
    url = public_base() + archive
    dest = download_dir() / archive
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}-updater"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if cancelled and cancelled():
                    raise UpdateError("已取消")
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except urllib.error.HTTPError as e:
        part.unlink(missing_ok=True)
        raise UpdateError(f"下载失败 HTTP {e.code}（包可能还没同步到公开链接，稍后再试）") from e
    except (urllib.error.URLError, OSError) as e:
        part.unlink(missing_ok=True)
        raise UpdateError(f"下载失败：{getattr(e, 'reason', e)}") from e
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    if dest.exists():
        dest.unlink()
    part.rename(dest)
    return dest


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_archive(zip_path: Path, archive: str) -> None:
    """下载同名 .sha256（`hex  文件名` 格式，只取第一个空格前），不一致删 zip 并报错。"""
    raw = _http_get(public_base() + archive + ".sha256")
    expected = raw.decode("ascii", "ignore").strip().split()[0].lower() if raw.strip() else ""
    if len(expected) != 64:
        zip_path.unlink(missing_ok=True)
        raise UpdateError("服务器上的 .sha256 文件格式不对，已拒绝安装")
    actual = sha256_of(zip_path)
    if actual != expected:
        zip_path.unlink(missing_ok=True)
        raise UpdateError("更新包校验失败（SHA-256 不一致），已拒绝安装")


# ---- 安装 ----
def _win_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def kill_main_program() -> None:
    """杀主程序及其会锁文件的子进程（登录子进程也是同一个 exe）。"""
    if sys.platform != "win32":
        return
    for image in (MAIN_EXE_NAME,):
        subprocess.run(
            ["taskkill", "/F", "/IM", image],
            capture_output=True, creationflags=_win_flags(), stdin=subprocess.DEVNULL,
        )


def build_install_bat(zip_path: Path, target_dir: Path) -> str:
    """生成安装脚本内容（CRLF）。

    注意：`for /d %%I` 必须恰好两个 %，`del "%~f0"` 一个 %（照 软件包更新方式.md 6.3）。
    用 str.replace 填占位符，避免 format/百分号转义搞混。
    """
    template = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "echo Pan-Auto - 自动更新安装程序\r\n"
        "echo.\r\n"
        "ping 127.0.0.1 -n 3 >nul\r\n"
        "echo 正在关闭旧进程...\r\n"
        "taskkill /F /IM \"@MAIN_EXE@\" 2>nul\r\n"
        "taskkill /F /IM \"@UPDATER_EXE@\" 2>nul\r\n"
        "ping 127.0.0.1 -n 2 >nul\r\n"
        "echo.\r\n"
        "echo 正在解压更新包...\r\n"
        "set \"WORK_DIR=%TEMP%\\pan-auto-update-work-%RANDOM%\"\r\n"
        "mkdir \"%WORK_DIR%\" 2>nul\r\n"
        "powershell -NoProfile -ExecutionPolicy Bypass -Command \"Expand-Archive -Path '@ZIP@' -DestinationPath '%WORK_DIR%' -Force\" >> \"@APP@\\update.log\" 2>&1\r\n"
        "if errorlevel 1 (\r\n"
        "    echo 解压失败！>> \"@APP@\\update.log\"\r\n"
        "    echo 解压失败，详情见 update.log\r\n"
        "    ping 127.0.0.1 -n 3 >nul\r\n"
        "    exit /b 1\r\n"
        ")\r\n"
        "echo 正在应用更新...\r\n"
        "for /d %%I in (\"%WORK_DIR%\\*\") do (\r\n"
        "    xcopy /Y /E /H /C /I \"%%I\\*\" \"@APP@\\\" >> \"@APP@\\update.log\" 2>&1\r\n"
        ")\r\n"
        "rmdir /S /Q \"%WORK_DIR%\" 2>nul\r\n"
        "echo.\r\n"
        "echo 更新完成！正在启动... >> \"@APP@\\update.log\"\r\n"
        "ping 127.0.0.1 -n 2 >nul\r\n"
        "start \"\" \"@APP@\\@MAIN_EXE@\"\r\n"
        "del \"@ZIP@\" 2>nul\r\n"
        # (goto) 2>nul 让 cmd 干净地退出批处理上下文，再删自己，不会再报 "The batch file cannot be found"
        "(goto) 2>nul & del \"%~f0\"\r\n"
    )
    return (
        template.replace("@ZIP@", str(zip_path))
        .replace("@APP@", str(target_dir).rstrip("\\"))
        .replace("@MAIN_EXE@", MAIN_EXE_NAME)
        .replace("@UPDATER_EXE@", UPDATER_EXE_NAME)
    )


def write_install_bat(zip_path: Path, target_dir: Path) -> Path:
    """写 .bat 到 %TEMP%：UTF-8 **不带 BOM** + 首行 chcp 65001。

    实测（cmd /c 真跑）：带 BOM 时 cmd 把首行读成 "﻿@echo off"，报「不是内部或外部命令」，
    echo 关不掉、所有命令回显；不带 BOM 时 `@echo off` 生效，chcp 65001 之后中文 echo 与
    写入 update.log 都正确（UTF-8）。所以这里与参考实现不同，不写 BOM。
    """
    bat = Path(tempfile.gettempdir()) / f"pan-auto-update-{int(time.time() * 1000)}.bat"
    bat.write_bytes(build_install_bat(zip_path, target_dir).encode("utf-8"))
    return bat


def launch_bat(bat: Path) -> None:
    """★ .bat 不能被 CreateProcess 直接启动，必须经 cmd.exe /c；失败上抛给界面提示。"""
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat)],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            close_fds=True,
            cwd=str(bat.parent),
        )
    except OSError as e:
        raise UpdateError(f"无法启动安装脚本：{e}") from e


def install(zip_path: Path) -> Path:
    """杀主程序 → 写 bat → cmd /c 启动。返回 bat 路径；调用方随后应退出自己。"""
    target = app_dir()
    kill_main_program()
    bat = write_install_bat(zip_path, target)
    launch_bat(bat)
    return bat


# ---- 主程序侧：启动更新器 ----
def launch_updater() -> tuple[bool, str]:
    """主程序「检查更新」按钮只做这一件事：启动旁边的 update.exe（源码版启动 updater_main.py）。"""
    try:
        if getattr(sys, "frozen", False):
            exe = app_dir() / UPDATER_EXE_NAME
            if not exe.exists():
                return False, f"找不到 {UPDATER_EXE_NAME}，请手动下载最新版本覆盖安装"
            subprocess.Popen([str(exe)], cwd=str(app_dir()), close_fds=True)
        else:
            script = app_dir() / "updater_main.py"
            subprocess.Popen([sys.executable, str(script)], cwd=str(app_dir()), close_fds=True)
        return True, ""
    except OSError as e:
        return False, f"启动更新器失败：{e}"
