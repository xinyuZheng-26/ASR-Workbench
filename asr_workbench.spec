# -*- mode: python ; coding: utf-8 -*-
# Build with: pyinstaller --noconfirm --clean asr_workbench.spec

from pathlib import Path
from importlib.util import find_spec

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ
from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH)
runtime_datas = [(str(project_root / "asr_workbench" / "web"), "asr_workbench/web")]
runtime_binaries = []
runtime_hiddenimports = ["multipart", "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto"]

# FunASR and ModelScope load several registries dynamically. Build scripts install the
# inference extra first; collecting these packages keeps those runtime imports in the release.
for runtime_package in ("funasr", "modelscope"):
    if find_spec(runtime_package) is not None:
        package_datas, package_binaries, package_hiddenimports = collect_all(runtime_package)
        runtime_datas += package_datas
        runtime_binaries += package_binaries
        runtime_hiddenimports += package_hiddenimports

a = Analysis(
    [str(project_root / "run_workbench.py")],
    pathex=[str(project_root)],
    binaries=runtime_binaries,
    datas=runtime_datas,
    hiddenimports=runtime_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ASR-Workbench",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
