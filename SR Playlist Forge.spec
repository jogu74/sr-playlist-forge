# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

project_dir = Path(SPECPATH).resolve().parent
datas = []
hiddenimports = ['modern_gui', 'UnityPy']
datas.extend(collect_data_files('UnityPy'))
tools_dir = project_dir / "tools"
if tools_dir.exists():
    datas.append((str(tools_dir), "tools"))
assets_dir = project_dir / "assets"
if assets_dir.exists():
    datas.append((str(assets_dir), "assets"))

a = Analysis(
    ['synth_playlist_editor.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(project_dir / 'hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'numpy',
        'pandas',
        'scipy',
        'sqlalchemy',
        'PIL._avif',
        'PIL.AvifImagePlugin',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SR Playlist Forge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\icon.ico'],
)
