#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def build_windows_ico(src_png: Path, out_ico: Path) -> None:
    img = load_square_icon(src_png)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    out_ico.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_ico, format="ICO", sizes=sizes)


def build_macos_icns(src_png: Path, out_icns: Path) -> None:
    img = load_square_icon(src_png)
    sizes = [(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)]
    out_icns.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_icns, format="ICNS", sizes=sizes)


def load_square_icon(src_png: Path):
    from PIL import Image, ImageOps

    with Image.open(src_png) as source:
        img = source.convert("RGBA")
    if img.width == img.height:
        return img

    canvas_size = max(img.width, img.height)
    contained = ImageOps.contain(img, (canvas_size, canvas_size), Image.Resampling.LANCZOS)
    square = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    square.paste(contained, ((canvas_size - contained.width) // 2, (canvas_size - contained.height) // 2), contained)
    return square


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate app icon formats from icon.png")
    parser.add_argument("--input", default="icon.png", help="Source PNG file (default: icon.png)")
    parser.add_argument("--mac", action="store_true", help="Generate macOS .icns")
    parser.add_argument("--windows", action="store_true", help="Generate Windows .ico")
    args = parser.parse_args()

    src_png = Path(args.input)
    if not src_png.exists():
        raise SystemExit(f"Missing source image: {src_png}")

    if not args.mac and not args.windows:
        args.mac = True
        args.windows = True

    assets_dir = Path("assets")
    if args.windows:
        build_windows_ico(src_png, assets_dir / "icon.ico")
        print(f"Generated {assets_dir / 'icon.ico'}")

    if args.mac:
        build_macos_icns(src_png, assets_dir / "icon.icns")
        print(f"Generated {assets_dir / 'icon.icns'}")


if __name__ == "__main__":
    main()
