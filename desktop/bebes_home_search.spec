# PyInstaller spec for Bebe's Home Search. Build with desktop/build.ps1.
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "desktop" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "dashboard" / "index.html"), "dashboard")],
    # Imported lazily; listed so the phone-app sync works from the exe.
    hiddenimports=["firebase_admin", "firebase_admin.firestore", "google.cloud.firestore"],
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "pytest", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Bebe's Home Search",
    icon=str(ROOT / "desktop" / "icon.ico"),
    version=str(ROOT / "desktop" / "version_info.txt"),
    console=False,
    upx=False,
)
