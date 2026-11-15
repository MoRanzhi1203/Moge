# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

# 基于 spec 所在目录解析，避免硬编码绝对路径
_spec_dir = Path(SPECPATH)

a = Analysis(
    [str(_spec_dir / 'main.py')],
    pathex=[str(_spec_dir.parent), str(_spec_dir)],
    binaries=[],
    datas=[(str(_spec_dir / 'assets'), 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 代码中未使用、且体积较大的依赖，避免误打包
        'tkinter',
        'matplotlib',
        'pandas',
        'seaborn',
        'scipy',
        'sklearn',
        'pyqtgraph',
        'qdarkstyle',
        'requests',
        'dotenv',
        'pytest',
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
    name='Moge',
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
    name='Moge',
)
