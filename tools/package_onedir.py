from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


def make_zip(source_dir: Path, output_zip: Path) -> None:
    source_dir = source_dir.resolve()
    output_zip = output_zip.resolve()

    if not source_dir.is_dir():
        raise SystemExit(f"Onedir source directory does not exist: {source_dir}")
    if output_zip.suffix.lower() != ".zip":
        raise SystemExit(f"Output must be a .zip file: {output_zip}")

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.exists():
        output_zip.unlink()

    # Keep the versioned onedir directory as the archive root. After extraction
    # the user gets one self-contained folder rather than a loose set of files.
    archive_root = source_dir.parent
    with zipfile.ZipFile(
        output_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=False,
    ) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(archive_root))

    print(f"Created {output_zip} ({output_zip.stat().st_size} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Package a PyInstaller onedir build as ZIP")
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output_zip", type=Path)
    args = parser.parse_args()
    make_zip(args.source_dir, args.output_zip)


if __name__ == "__main__":
    main()
