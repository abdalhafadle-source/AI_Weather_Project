#!/usr/bin/env python3
"""
make_fonts.py
Turns the Inter font (esp32/fonts/, SIL Open Font License) into smooth (anti-aliased) VLW fonts for the screen
and writes them as C arrays to esp32/pv_cleaner_client/fonts_inter.h. LovyanGFX draws VLW fonts with soft edges,
so text stays clean at every size (the old bitmap FreeSans was shrunk by fractions and its letters overlapped).

VLW layout (Processing format, big-endian int32): header [count, 11, size, 0, ascent, descent], then 7 ints per glyph
[unicode, height, width, xAdvance, dY (top above baseline), dX, 0], then the 8-bit alpha bitmaps in the same order.

Usage (needs Pillow):  python esp32/make_fonts.py
"""
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "pv_cleaner_client" / "fonts_inter.h"
ASCII = "".join(chr(c) for c in range(0x20, 0x7F))
BIG = " 0123456789:-ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # the 28 px font: ring words, timer, splash only
# (C name, ttf, pixel size, characters)
FONTS = [("INTER_R13", "inter-400.ttf", 13, ASCII), ("INTER_R15", "inter-400.ttf", 15, ASCII),
         ("INTER_R19", "inter-400.ttf", 19, ASCII), ("INTER_B13", "inter-700.ttf", 13, ASCII),
         ("INTER_B15", "inter-700.ttf", 15, ASCII), ("INTER_B19", "inter-700.ttf", 19, ASCII),
         ("INTER_B28", "inter-700.ttf", 28, BIG)]


def vlw(ttf: Path, size: int, chars: str) -> bytes:
    f = ImageFont.truetype(str(ttf), size)
    asc = -f.getbbox("d", anchor="ls")[1]
    desc = f.getbbox("p", anchor="ls")[3]
    meta, bits = [], []
    for ch in sorted(set(chars)):
        x0, y0, x1, y1 = f.getbbox(ch, anchor="ls")
        w, h = max(0, x1 - x0), max(0, y1 - y0)
        if w and h:
            im = Image.new("L", (w, h), 0)
            ImageDraw.Draw(im).text((-x0, -y0), ch, font=f, fill=255, anchor="ls")
            bits.append(im.tobytes())
        else:
            w = h = 0
            bits.append(b"")
        meta.append(struct.pack(">7i", ord(ch), h, w, round(f.getlength(ch)), -y0 if h else 0, x0 if w else 0, 0))
    return struct.pack(">6i", len(meta), 11, size, 0, asc, desc) + b"".join(meta) + b"".join(bits)


def main() -> int:
    lines = ["// fonts_inter.h - made by esp32/make_fonts.py from Inter (SIL Open Font License 1.1, esp32/fonts/OFL.txt).",
             "// Smooth VLW fonts for LovyanGFX. Do not edit: run the script again.", "#pragma once", "#include <stdint.h>", ""]
    total = 0
    for name, ttf, size, chars in FONTS:
        data = vlw(HERE / "fonts" / ttf, size, chars)
        total += len(data)
        lines.append(f"static const uint8_t {name}[{len(data)}] = {{")
        for i in range(0, len(data), 24):
            lines.append("  " + ",".join(str(b) for b in data[i:i + 24]) + ",")
        lines.append("};")
        print(f"{name}: {len(data)} bytes")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"saved {OUT} ({total} bytes of font data)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
