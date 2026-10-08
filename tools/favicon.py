#!/usr/bin/env python3
"""Draw favicon.png and apple-touch-icon.png to match favicon.svg. Needs Pillow."""
import pathlib

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
BG, DIM, LIT = "#0f1a33", "#56617d", "#a59bf7"


def draw(size, name, corner):
    s = size * 4
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    u = s / 32
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=corner * u, fill=BG)
    for row in range(3):
        for col in range(3):
            x, y = (5 + 8 * col) * u, (5 + 8 * row) * u
            d.rounded_rectangle([x, y, x + 6 * u, y + 6 * u], radius=1.2 * u, fill=LIT if (row, col) == (0, 0) else DIM)
    im.resize((size, size), Image.LANCZOS).save(ROOT / name)
    print(name, size)


draw(32, "favicon.png", 6)
draw(180, "apple-touch-icon.png", 0)
