from pathlib import Path

from PIL import Image

from app.desktop import _resource_path


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


def test_pyinstaller_spec_uses_turnirium_icon():
    spec = Path(__file__).resolve().parents[1] / "Turnirium.spec"
    text = spec.read_text(encoding="utf-8")
    assert "icon='assets/turnirium.ico'" in text
    assert "('assets/turnirium_icon.png', 'assets')" in text
    assert "('assets/turnirium.ico', 'assets')" in text


def test_web_headers_use_the_turnirium_icon_asset():
    root = Path(__file__).resolve().parents[1]
    static_dir = root / "app" / "static"
    js_source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(static_dir.glob("*.js")))
    index_html = (static_dir / "index.html").read_text(encoding="utf-8")
    assert '/static/turnirium_icon.png' in js_source
    assert 'brandIconHtml()' in js_source
    assert '/static/turnirium_icon.png' in index_html
