# -*- mode: python ; coding: utf-8 -*-

# One-file release build.
# Keep the bundle close to the stock PyInstaller layout. In particular:
# - no UPX or third-party executable packer;
# - no custom runtime hooks;
# - no forced runtime_tmpdir;
# - only imports that are genuinely selected dynamically at runtime.
#
# The versioned artifact name is derived from app/version.py so the file on disk,
# PE VERSIONINFO and application version cannot drift independently.
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
    # Onefile keeps normal pure-Python modules in PyInstaller's standard PYZ.
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

# Onefile passes binaries/data directly to EXE. PyInstaller extracts these to its
# standard temporary _MEI directory at runtime. Do not replace this with a custom
# extraction scheme; the stock bootloader is both simpler and easier to audit.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
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
