"""Generate TreadLab's PWA icons -- stdlib only (zlib + struct write the PNGs).

    python-embed\\python.exe tools\\make_icons.py

Draws the same mountain glyph as the in-app logo, antialiased by 4x
supersampling, full-bleed so it works as a maskable icon.
"""

import os
import struct
import sys
import zlib

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "treadlab", "static")

BG = (0x1C, 0x21, 0x29)      # --panel
FG = (0xFF, 0x6B, 0x35)      # --accent
GLYPH = [(2, 26), (14, 8), (20, 17), (24, 12), (30, 26)]  # 32-unit design grid
SS = 4                        # supersampling factor
SIZES = {"icon-192.png": 192, "icon-512.png": 512, "apple-touch-icon.png": 180}


def write_png(path, size, rows):
    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in rows)

    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit truecolour
    blob = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(blob)
    return len(blob)


def inside(poly, x, y):
    """Ray-casting point-in-polygon."""
    hit = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xt = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < xt:
                hit = not hit
    return hit


def render(size):
    # scale the glyph to ~66 % of the canvas and centre its bounding box
    xs = [p[0] for p in GLYPH]
    ys = [p[1] for p in GLYPH]
    gw, gh = max(xs) - min(xs), max(ys) - min(ys)
    scale = size * 0.66 / gw
    ox = (size - gw * scale) / 2 - min(xs) * scale
    oy = (size - gh * scale) / 2 - min(ys) * scale
    poly = [(x * scale + ox, y * scale + oy) for x, y in GLYPH]

    rows = []
    step = 1.0 / SS
    for py in range(size):
        row = []
        for px in range(size):
            hits = 0
            for sy in range(SS):
                for sx in range(SS):
                    if inside(poly, px + (sx + 0.5) * step, py + (sy + 0.5) * step):
                        hits += 1
            a = hits / (SS * SS)
            row.append(tuple(round(BG[i] + (FG[i] - BG[i]) * a) for i in range(3)))
        rows.append(row)
    return rows


def main():
    for name, size in SIZES.items():
        n = write_png(os.path.join(OUT, name), size, render(size))
        print("  %-22s %4dx%-4d %6d bytes" % (name, size, size, n))
    print("\nicons -> %s" % OUT)


if __name__ == "__main__":
    sys.exit(main())
