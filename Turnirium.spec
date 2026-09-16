# -*- mode: python ; coding: utf-8 -*-

# One-file release build.
# Keep the bundle as close as possible to the stock PyInstaller layout:
# - no UPX;
# - no custom runtime hooks;
# - no forced runtime_tmpdir;
# - only imports that are genuinely selected dynamically at runtime.
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
    # In onefile mode keep pure Python modules in the normal PYZ archive.
    # noarchive=True would turn them into many individual files that still
    # have to be embedded and extracted by the onefile bootloader.
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

# For onefile the binaries and data are passed directly to EXE and there is
# intentionally no separate collection stage. At runtime PyInstaller extracts the
# bundled dependencies to its temporary _MEI... directory.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Turnirium',
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
    # Do not set runtime_tmpdir: the stock temporary-directory behavior is
    # safer and avoids stale extracted DLLs between application versions.
)
