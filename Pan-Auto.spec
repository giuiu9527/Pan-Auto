# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 构建：主程序 Pan-Auto.exe + 独立更新器 update.exe，共用一个 _internal。

版本号唯一来源：仓库根目录 VERSION（3.0.0）。这里把它写进两个 exe 的 VERSIONINFO，
并随 datas 打进 _internal/VERSION，更新器 / 打包脚本 / update.json 读的都是同一个值。
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip().lstrip("vV")
_nums = [int(x) if x.isdigit() else 0 for x in VERSION.split(".")]
while len(_nums) < 4:
    _nums.append(0)
FILEVERS = tuple(_nums[:4])


def _version_info(exe_name: str, description: str) -> str:
    """生成 PyInstaller 的 VSVersionInfo 文本文件，返回路径。"""
    out = ROOT / "build" / f"version_info_{exe_name}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={FILEVERS}, prodvers={FILEVERS}, mask=0x3f, flags=0x0,\n"
        "                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[\n"
        "    StringFileInfo([StringTable('040904B0', [\n"
        "      StringStruct('CompanyName', 'Pan-Auto'),\n"
        f"      StringStruct('FileDescription', '{description}'),\n"
        f"      StringStruct('FileVersion', '{VERSION}'),\n"
        f"      StringStruct('ProductVersion', '{VERSION}'),\n"
        "      StringStruct('ProductName', 'Pan-Auto'),\n"
        f"      StringStruct('OriginalFilename', '{exe_name}.exe'),\n"
        f"      StringStruct('InternalName', '{exe_name}')])]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])])\n"
        "  ]\n"
        ")\n",
        encoding="utf-8",
    )
    return str(out)


# 收集 pywebview（含其 JS 资源）与 pythonnet（WebView2 后端依赖）
_web_datas, _web_bins, _web_hidden = collect_all("webview")
_clr_datas, _clr_bins, _clr_hidden = collect_all("clr_loader")

EXCLUDES = [
    # 移除内置 Chromium 及其牵连的大模块（登录改用系统 WebView2）
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebChannel",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtQmlModels",
    "PySide6.QtPositioning",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
]
DATAS = [("app/ui/assets", "app/ui/assets"), ("VERSION", ".")]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=_web_bins + _clr_bins,
    datas=DATAS + _web_datas + _clr_datas,
    hiddenimports=["clr"] + _web_hidden + _clr_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Pan-Auto",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app/ui/assets/app.ico",
    version=_version_info("Pan-Auto", "Pan-Auto 网盘自动转存"),
)

# 独立更新器：只依赖 PySide6 + 标准库，和主程序共用 _internal
u = Analysis(
    ["updater_main.py"],
    pathex=[],
    binaries=[],
    datas=DATAS,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
upyz = PYZ(u.pure)
uexe = EXE(
    upyz,
    u.scripts,
    [],
    exclude_binaries=True,
    name="update",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app/ui/assets/app.ico",
    version=_version_info("update", "Pan-Auto 更新器"),
)

coll = COLLECT(
    exe,
    uexe,
    a.binaries,
    a.datas,
    u.binaries,
    u.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Pan-Auto",
)
