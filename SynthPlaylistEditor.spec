# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

project_dir = Path(SPECPATH).resolve().parent

a = Analysis(
    ['synth_playlist_editor.py'],
    pathex=[],
    binaries=[],
    datas=collect_data_files('UnityPy'),
    hiddenimports=['modern_gui', 'UnityPy'],
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
    name='SynthPlaylistEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
app = BUNDLE(
    exe,
    name='SynthPlaylistEditor.app',
    icon=None,
    bundle_identifier=None,
)
