from pathlib import Path

from PIL import Image

from app.desktop import _resource_path
from tools.package_onedir import make_zip


def _app_version(root: Path) -> str:
    version = (root / "app" / "version.py").read_text(encoding="utf-8")
    match = __import__("re").search(r'APP_VERSION\s*=\s*["\']([^"\']+)', version)
    assert match is not None
    return match.group(1)


def test_turnirium_icon_assets_are_present_and_multisize():
    source = _resource_path("assets", "turnirium_icon_source.png")
    png = _resource_path("assets", "turnirium_icon.png")
    ico = _resource_path("assets", "turnirium.ico")
    web_png = Path(__file__).resolve().parents[1] / "app" / "static" / "turnirium_icon.png"
    assert source.exists()
    assert png.exists()
    assert ico.exists()
    assert web_png.exists()

    with Image.open(png) as image:
        assert image.size == (1024, 1024)
        assert image.mode == "RGBA"
        # Текущий фирменный стиль: красный сверху слева, светло-серый снизу справа.
        upper_left = image.getpixel((180, 180))
        lower_right = image.getpixel((820, 820))
        assert upper_left[0] > upper_left[1] * 3 / 2
        assert abs(lower_right[0] - lower_right[1]) < 20
        assert 120 <= lower_right[0] <= 180
        # Финальный вариант использует чёрную готическую монограмму TR.
        letter_t = image.getpixel((350, 400))
        letter_r = image.getpixel((690, 420))
        assert max(letter_t[:3]) < 50
        assert max(letter_r[:3]) < 50

    with Image.open(ico) as image:
        sizes = image.ico.sizes()
        assert (16, 16) in sizes
        assert (32, 32) in sizes
        assert (48, 48) in sizes
        assert (256, 256) in sizes


def test_pyinstaller_specs_use_turnirium_icon_and_versioned_name():
    root = Path(__file__).resolve().parents[1]
    for spec_name in ("Turnirium.spec", "Turnirium_onedir.spec"):
        text = (root / spec_name).read_text(encoding="utf-8")
        assert "BUILD_NAME = f'Turnirium_v{APP_VERSION}'" in text
        assert "name=BUILD_NAME" in text
        assert "icon='assets/turnirium.ico'" in text
        assert "('assets/turnirium_icon.png', 'assets')" in text
        assert "('assets/turnirium.ico', 'assets')" in text
        assert "version='version_info.txt'" in text
        assert "upx=False" in text
        assert "runtime_hooks=[]" in text
        assert "uac_admin=False" in text
        assert "uac_uiaccess=False" in text


def test_web_headers_use_the_turnirium_icon_asset():
    root = Path(__file__).resolve().parents[1]
    static_dir = root / "app" / "static"
    js_source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(static_dir.glob("*.js")))
    index_html = (static_dir / "index.html").read_text(encoding="utf-8")
    assert '/static/turnirium_icon.png' in js_source
    assert 'brandIconHtml()' in js_source
    assert '/static/turnirium_icon.png' in index_html


def test_pyinstaller_release_has_onefile_and_onedir_noarchive_variants():
    root = Path(__file__).resolve().parents[1]
    onefile = (root / "Turnirium.spec").read_text(encoding="utf-8")
    onedir = (root / "Turnirium_onedir.spec").read_text(encoding="utf-8")

    assert "noarchive=False" in onefile
    assert "COLLECT(" not in onefile
    assert "a.binaries" in onefile
    assert "a.datas" in onefile
    assert "exclude_binaries=True" not in onefile

    assert "noarchive=True" in onedir
    assert "exclude_binaries=True" in onedir
    assert "COLLECT(" in onedir
    assert "a.binaries" in onedir
    assert "a.datas" in onedir

    for text in (onefile, onedir):
        assert "collect_submodules" not in text
        assert "'websockets'" not in text
        assert "collect_submodules('pystray')" not in text
        assert "'pystray._win32'" in text
        assert "'psutil'" not in text
        assert "'tkinter'" not in text
        assert "runtime_tmpdir=" not in text


def test_windows_version_info_matches_application_version_and_artifact_name():
    root = Path(__file__).resolve().parents[1]
    app_version = _app_version(root)
    version_info = (root / "version_info.txt").read_text(encoding="utf-8")
    assert f"StringStruct('FileVersion', '{app_version}')" in version_info
    assert f"StringStruct('ProductVersion', '{app_version}')" in version_info
    assert "StringStruct('ProductName', 'Turnirium')" in version_info
    assert f"StringStruct('OriginalFilename', 'Turnirium_v{app_version}.exe')" in version_info
    assert "StringStruct('CompanyName', 'Клуб РЕЙД, г. Донецк (https://vk.ru/hema_dn)')" in version_info
    assert "StringStruct('FileDescription', 'Простая система для проведения ХЕМА турниров, и не только')" in version_info


def test_release_build_produces_versioned_exe_and_onedir_zip():
    root = Path(__file__).resolve().parents[1]
    build = (root / "build_windows.bat").read_text(encoding="utf-8")
    lower = build.lower()

    assert "set \"ARTIFACT_BASENAME=Turnirium_v%BUILD_VERSION%\"" in build
    assert "Turnirium.spec" in build
    assert "Turnirium_onedir.spec" in build
    assert "tools\\package_onedir.py" in build
    assert "dist\\%ARTIFACT_BASENAME%.exe" in build
    assert "dist\\%ARTIFACT_BASENAME%.zip" in build
    assert "build\\onedir-dist" in build
    assert "tools\\sign_windows_artifact.bat" in build
    assert "--noupx" not in lower  # release specs own the upx=False setting
    assert "--key" not in lower


def test_optional_signing_uses_authenticode_sha256_without_embedded_secret():
    root = Path(__file__).resolve().parents[1]
    signing = (root / "tools" / "sign_windows_artifact.bat").read_text(encoding="utf-8")
    lower = signing.lower()

    assert "turnirium_sign_cert_sha1" in lower
    assert "turnirium_timestamp_url" in lower
    assert "signtool" in lower
    assert " sign /fd sha256 " in lower
    assert " /td sha256 " in lower
    assert " verify /pa /v " in lower
    assert " /p " not in lower
    assert ".pfx" not in lower


def test_onedir_packager_preserves_versioned_top_level_directory(tmp_path):
    source = tmp_path / "Turnirium_v9.8.7"
    internal = source / "_internal"
    internal.mkdir(parents=True)
    (source / "Turnirium_v9.8.7.exe").write_bytes(b"exe")
    (internal / "module.pyc").write_bytes(b"pyc")
    output = tmp_path / "dist" / "Turnirium_v9.8.7.zip"

    make_zip(source, output)

    import zipfile

    with zipfile.ZipFile(output) as zf:
        assert zf.namelist() == [
            "Turnirium_v9.8.7/Turnirium_v9.8.7.exe",
            "Turnirium_v9.8.7/_internal/module.pyc",
        ]


def test_windows_build_has_no_psutil_and_debug_build_uses_noarchive():
    root = Path(__file__).resolve().parents[1]
    requirements = (root / 'requirements.txt').read_text(encoding='utf-8').lower()
    network_source = (root / 'app' / 'network.py').read_text(encoding='utf-8').lower()
    debug_build = (root / 'build_debug_windows.bat').read_text(encoding='utf-8').lower()

    assert 'psutil' not in requirements
    assert 'import psutil' not in network_source
    assert '--debug noarchive' in debug_build
    assert '--noupx' in debug_build
