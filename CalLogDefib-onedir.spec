# -*- mode: python ; coding: utf-8 -*-
# Onedir build for the Inno Setup installer (see installer.iss, which
# expects dist\CalLogDefib\*). For the portable single-file exe, see
# CalLogDefib.spec instead.

import os

block_cipher = None

EXCLUDE_BINARIES = {
    "opengl32sw.dll",
    "Qt6Quick.dll",
    "Qt6Qml.dll",
    "Qt6QmlModels.dll",
    "Qt6OpenGL.dll",
    "Qt6OpenGLWidgets.dll",
    "Qt6VirtualKeyboard.dll",
    "QtOpenGL.pyd",
    "QtOpenGLWidgets.pyd",
    "QtQml.pyd",
    "QtQuick.pyd",
    "QtQuickWidgets.pyd",
}

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

a.binaries = [b for b in a.binaries if os.path.basename(b[0]) not in EXCLUDE_BINARIES]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CalLogDefib",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name="CalLogDefib",
)
