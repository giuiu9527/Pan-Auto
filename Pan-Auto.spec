# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# 收集 pywebview（含其 JS 资源）与 pythonnet（WebView2 后端依赖）
_web_datas, _web_bins, _web_hidden = collect_all('webview')
_clr_datas, _clr_bins, _clr_hidden = collect_all('clr_loader')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_web_bins + _clr_bins,
    datas=[('app/ui/assets', 'app/ui/assets')] + _web_datas + _clr_datas,
    hiddenimports=['clr'] + _web_hidden + _clr_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 移除内置 Chromium 及其牵连的大模块（登录改用系统 WebView2）
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebChannel',
        'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',
        'PySide6.QtQml',
        'PySide6.QtQmlModels',
        'PySide6.QtPositioning',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Pan-Auto',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Pan-Auto',
)
