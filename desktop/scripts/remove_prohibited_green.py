#!/usr/bin/env python
"""Remove prohibited green/teal raster hues without changing geometry or alpha."""

from __future__ import annotations

import colorsys
import sys
from pathlib import Path

from PIL import Image


def is_prohibited(r: int, g: int, b: int, alpha: int) -> bool:
    if alpha == 0:
        return False
    hue, saturation, value = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return 60 <= hue * 360 < 200 and saturation >= 0.01 and value >= 0.01


def recolor(path: Path) -> int:
    image = Image.open(path).convert("RGBA")
    original_size = image.size
    changed = 0
    output = []
    for r, g, b, alpha in image.get_flattened_data():
        hue, saturation, value = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if alpha and saturation < 0.05:
            gray = round(value * 255)
            normalized = (gray, gray, gray, alpha)
            output.append(normalized)
            changed += int(normalized != (r, g, b, alpha))
        elif is_prohibited(r, g, b, alpha):
            red, green, blue = colorsys.hsv_to_rgb(220 / 360, saturation, value)
            output.append((round(red * 255), round(green * 255), round(blue * 255), alpha))
            changed += 1
        else:
            output.append((r, g, b, alpha))
    image.putdata(output)
    if image.size != original_size:
        raise RuntimeError("image dimensions changed")
    suffix = path.suffix.lower()
    if suffix == ".ico":
        image.save(path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    elif suffix == ".icns":
        image.save(path, format="ICNS")
    else:
        image.save(path, format="PNG", optimize=True)
    return changed


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: remove_prohibited_green.py <image> [<image> ...]")
    for raw_path in sys.argv[1:]:
        path = Path(raw_path).resolve()
        if not path.is_file():
            raise SystemExit(f"missing image: {path}")
        changed = recolor(path)
        print(f"[no-green-raster] recolored {changed} prohibited pixels in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
