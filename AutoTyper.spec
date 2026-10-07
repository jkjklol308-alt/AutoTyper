# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the AutoTyper executable.

Produces the single-file ``dist/AutoTyper.exe`` that GitHub Releases ships and
that the in-app updater downloads. Build it with::

    pyinstaller AutoTyper.spec --noconfirm

The updater only ever accepts a file that starts with the Windows "MZ" header,
so a build produced by this recipe is exactly what ``--check-update`` and the
Settings window's "Download latest AutoTyper.exe" button expect to find
attached to a release.
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH)
VERSION_FILE = ROOT / "build" / "version_info.txt"

hiddenimports = []
if sys.platform == "win32":
    # pynput picks its backend at import time; name them explicitly so the
    # packaged build can actually type into other applications.
    hiddenimports = ["pynput.keyboard._win32", "pynput.mouse._win32"]

a = Analysis(
    [str(ROOT / "auto_typer.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing in the shipped app needs the test tooling.
    excludes=["pytest", "unittest", "test_auto_typer", "test_custom_colours",
              "test_update_checker"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AutoTyper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,           # GUI application: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(VERSION_FILE) if VERSION_FILE.is_file() else None,
    icon=None,
)
