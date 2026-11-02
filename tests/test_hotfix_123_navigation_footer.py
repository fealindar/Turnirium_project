"""Проверки хотфикса интерфейса 1.2.3 без изменения версии сборки."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.version import APP_VERSION


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_branding_endpoint_supplies_real_release_version():
    with TestClient(app) as client:
        data = client.get("/api/branding").json()
        assert data["version"] == APP_VERSION == "1.2.3"
        assert data["app_name"]
        assert "developer_club_name" in data


def test_secretary_navigation_order_and_brand_position():
    script = (STATIC / "secretary.js").read_text(encoding="utf-8")
    layout = script.split("$('#app').innerHTML=", 1)[1].split(";", 1)[0]
    assert layout.index('class="brand secretary-brand"') < layout.index('class="board-mirror-control"')
    assert layout.index('class="board-mirror-control"') < layout.index('class="secretary-topbar-links"')
    assert layout.index('id="secretaryHotkeysButton"') < layout.index('href="/admin"')
    assert layout.index('href="/admin"') < layout.index('href="/board/${areaId}"')


def test_hotkeys_close_button_is_svg_with_accessible_label():
    script = (STATIC / "secretary-hotkeys.js").read_text(encoding="utf-8")
    assert 'class="secretary-shortcut-close" aria-label="Закрыть окно"' in script
    assert 'viewBox="0 0 24 24"' in script
    assert 'class="secretary-shortcut-close" aria-label="Закрыть">×' not in script


def test_toasts_clear_footer_using_measured_height():
    common = (STATIC / "common.js").read_text(encoding="utf-8")
    stylesheet = (STATIC / "public-screen.css").read_text(encoding="utf-8")
    assert "footer.getBoundingClientRect().top" in common
    assert "window.addEventListener('resize',updateToastClearance)" in common
    assert "updateToastClearance();\n  const el = $('#toast')" in common
    assert "bottom:var(--toast-bottom-clearance,16px)" in stylesheet
    assert "z-index:600" in stylesheet


def test_footer_shows_version_with_or_without_club():
    source = (STATIC / "common.js").read_text(encoding="utf-8")
    assert 'class="brand-version"' in source
    assert "BRANDING.show_footer_branding" in source
    assert "!BRANDING.developer_club_name" not in source
