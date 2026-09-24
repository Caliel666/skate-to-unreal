# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('C:/Users/Demuriel/Documents/my-apps/skate-to-unreal/big_to_skate', 'big_to_skate'), ('C:/Users/Demuriel/Documents/my-apps/skate-to-unreal/skate_to_unreal', 'skate_to_unreal')]
binaries = []
hiddenimports = ['numpy', 'PIL', 'PIL.Image']
tmp_ret = collect_all('numpy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:/Users/Demuriel/Documents/my-apps/skate-to-unreal/skate_map_gui/app.py'],
    pathex=['C:/Users/Demuriel/Documents/my-apps/skate-to-unreal/skate_map_gui'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SkateMapToUnreal',
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
    name='SkateMapToUnreal',
)
