# -*- mode: python ; coding: utf-8 -*-

# Defender-friendly release alternative: onedir + noarchive.
# Python modules are stored as individual files instead of a PYZ archive, and the
# executable does not need the onefile self-extraction path at startup.
from pathlib import Path


ROOT = Path(SPECPATH)
version_scope = {}
exec((ROOT / 'app' / 'version.py').read_text(encoding='utf-8'), version_scope)
APP_VERSION = version_scope['APP_VERSION']
BUILD_NAME = f'Turnirium_v{APP_VERSION}'

hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops.auto',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan.on',
    'pystray._win32',
]

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('app/static', 'app/static'),
        ('branding.json', '.'),
        ('assets/turnirium_icon.png', 'assets'),
        ('assets/turnirium.ico', 'assets'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=True,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=BUILD_NAME,
    icon='assets/turnirium.ico',
    version='version_info.txt',
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
    uac_admin=False,
    uac_uiaccess=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=BUILD_NAME,
)
