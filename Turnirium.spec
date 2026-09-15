# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.lifespan.on',
]
hiddenimports += collect_submodules('websockets')
hiddenimports += collect_submodules('pystray')
hiddenimports += ['tkinter', 'tkinter.ttk', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont', 'psutil']

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[('app/static', 'app/static'), ('branding.json', '.'), ('assets/turnirium_icon.png', 'assets'), ('assets/turnirium.ico', 'assets')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Turnirium',
    icon='assets/turnirium.ico',
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
