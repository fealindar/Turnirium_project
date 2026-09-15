from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SOURCE = ASSETS / "turnirium_icon_source.png"
PNG = ASSETS / "turnirium_icon.png"
ICO = ASSETS / "turnirium.ico"
PREVIEW = ASSETS / "turnirium_icon_preview.png"
WEB_PNG = ROOT / "app" / "static" / "turnirium_icon.png"
OUTPUT_SIZE = 1024
ICO_SIZES = [
    (16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
    (48, 48), (64, 64), (128, 128), (256, 256),
]


def build_icon() -> Image.Image:
    """Формирует Windows-ресурсы из утверждённого изображения Turnirium."""
    if not SOURCE.exists():
        raise FileNotFoundError(f"Approved icon source is missing: {SOURCE}")

    with Image.open(SOURCE) as source:
        source = source.convert("RGBA")
        # Сохраняем утверждённую композицию. ImageOps.fit защищает только от
        # случайной замены на неквадратный исходник, сохраняя центральное кадрирование.
        square = ImageOps.fit(
            source,
            (OUTPUT_SIZE, OUTPUT_SIZE),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        return square


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    icon = build_icon()
    icon.save(PNG, format="PNG", optimize=True)
    icon.save(PREVIEW, format="PNG", optimize=True)
    WEB_PNG.parent.mkdir(parents=True, exist_ok=True)
    icon.save(WEB_PNG, format="PNG", optimize=True)
    icon.save(ICO, format="ICO", sizes=ICO_SIZES)
    print(PNG)
    print(ICO)
    print(WEB_PNG)


if __name__ == "__main__":
    main()
