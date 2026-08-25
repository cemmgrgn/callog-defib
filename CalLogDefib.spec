# -*- mode: python ; coding: utf-8 -*-
# Onefile portable build. For the installer's onedir build, see
# CalLogDefib-onedir.spec.

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
    a.binaries,
    a.datas,
    [],
    name="CalLogDefib",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
