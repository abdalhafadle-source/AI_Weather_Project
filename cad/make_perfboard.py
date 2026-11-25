#!/usr/bin/env python3
"""
make_perfboard.py
1:1 layout for a ready-made perfboard (holes every 2.54 mm), printed on A4 at 100 %:
  top    = PARTS side (place the ESP32 and the 14-pin female header for the screen)
  bottom = SOLDER side, mirrored: cut it out, glue it on the back of the board, follow the wires hole by hole.
Pins = the firmware now (ui.h, PINS_BREADBOARD 1). ESP32 = NodeMCU ESP-32S 38 pins (rows 9 holes apart = 22.86 mm).
Wires: thin INSULATED wire (they cross). Power: the MT3608 5V and GND wires come to the 5V / GND marks.

Usage:  python cad/make_perfboard.py      -> cad/perfboard_1to1.png and .pdf (A4, print at 100 %)
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent / "perfboard_1to1"
ar = lambda s: s  # matplotlib 3.11 shapes and orders Arabic itself (reshaping again reversed it)
PITCH = 2.54
COLS, ROWS = 30, 24          # 7 x 9 cm perfboard, used sideways

LEFT = ["3V3", "EN", "SVP", "SVN", "34", "35", "32", "33", "25", "26", "27", "14", "12", "GND", "13", "SD2", "SD3", "CMD", "5V"]
RIGHT = ["GND", "23", "22", "TX", "RX", "21", "GND", "19", "18", "5", "17", "16", "4", "0", "2", "15", "SD1", "SD0", "CLK"]
SCREEN = ["VCC", "GND", "CS", "RESET", "DC", "SDI", "SCK", "LED", "SDO", "T_CLK", "T_CS", "T_DIN", "T_DO", "T_IRQ"]
CL, CR, R0 = 2, 11, 3        # ESP32 left / right pin columns, top pin row (hole grid, row 0 = top)
CH, RH = 23, 4               # screen header column, its pin 1 row
# nets: (esp side, esp row index, screen pins, colour, lane column)
NETS = [("R", 0, ["GND"], "#111111", 13), ("R", 1, ["SDI", "T_DIN"], "#8e44ad", 14), ("R", 7, ["T_DO"], "#e67e22", 15),
        ("R", 8, ["SCK", "T_CLK"], "#1e63d6", 16), ("R", 9, ["T_CS"], "#d81b60", 17), ("R", 12, ["RESET"], "#00897b", 18),
        ("R", 14, ["DC"], "#7cb342", 19), ("R", 15, ["CS"], "#2e7d32", 20),
        ("L", 0, ["VCC", "LED"], "#c0392b", 21), ("L", 4, ["T_IRQ"], "#6d4c41", 22)]


def hole(c, r):
    return c * PITCH, -r * PITCH


def draw(ax, ox, oy, mirror, title):
    def P(c, r):
        x, y = hole(c, r)
        return (ox + ((COLS - 1) * PITCH - x if mirror else x), oy + y)

    W, H = (COLS - 1) * PITCH, (ROWS - 1) * PITCH
    ax.add_patch(plt.Rectangle((ox - 2, oy - H - 2), W + 4, H + 4, fc="#f3efe3", ec="#999", lw=0.5))
    for c in range(COLS):
        for r in range(ROWS):
            ax.add_patch(plt.Circle(P(c, r), 0.45, fc="white", ec="#aaa", lw=0.3))
    for c in range(0, COLS, 5):
        ax.text(*P(c, -1.2), str(c + 1), ha="center", fontsize=4, color="#888")
    for r in range(0, ROWS, 5):
        x, y = P(-1.3 if not mirror else COLS + 0.3, r)
        ax.text(x, y, str(r + 1), va="center", ha="center", fontsize=4, color="#888")
    # ESP32 outline and pins
    a, b = P(CL - 1.2, R0 - 4), P(CR + 1.2, R0 + 18 + 2.5)
    ax.add_patch(plt.Rectangle((min(a[0], b[0]), b[1]), abs(b[0] - a[0]), a[1] - b[1], fill=False, ec="#1d3557",
                               lw=0.8, ls="--"))
    x, y = P((CL + CR) / 2, R0 - 2.6)
    ax.text(x, y, ar("الهوائي") + " ↑", ha="center", fontsize=4.5, color="#1d3557")
    x, y = P((CL + CR) / 2, R0 + 19.6)
    ax.text(x, y, "USB-C ↓", ha="center", fontsize=4.5, color="#1d3557")
    for col, names in ((CL, LEFT), (CR, RIGHT)):
        for i, n in enumerate(names):
            x, y = P(col, R0 + i)
            ax.add_patch(plt.Circle((x, y), 0.9, fc="#e0b84a", ec="#7a5c00", lw=0.4))
            inward = (col == CL) != mirror
            ax.text(x + (1.4 if inward else -1.4), y, n, va="center", ha="left" if inward else "right", fontsize=3.4)
    # screen header
    for k, n in enumerate(SCREEN):
        x, y = P(CH, RH + k)
        ax.add_patch(plt.Rectangle((x - 0.95, y - 0.95), 1.9, 1.9, fc="#e8a0a0", ec="#7a1c1c", lw=0.4))
        out = not mirror
        ax.text(x + (1.5 if out else -1.5), y, f"{k + 1} {n}", va="center", ha="left" if out else "right", fontsize=3.4)
    x, y = P(CH, RH - 1.6)
    ax.text(x, y, ar("رأس الشاشة"), ha="center", fontsize=4.5, color="#7a1c1c")
    # wires
    top = 0  # row used for the wires that go over the top of the ESP32
    for side, i, pins, col, lane in NETS:
        r = R0 + i
        if side == "R":
            path = [(CR, r), (lane, r)]
        else:  # left pin: out to the left, up over the board, across to its lane
            up = top + (0 if i == 0 else 1)
            path = [(CL, r), (CL - 1 - (i > 0), r), (CL - 1 - (i > 0), up), (lane, up)]
        rows = [RH + SCREEN.index(p) for p in pins]
        path.append((lane, max(rows + [path[-1][1]]) if path[-1][1] < max(rows) else min(rows)))
        pts = [P(c, rr) for c, rr in path]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=col, lw=1.1, solid_capstyle="round")
        lo, hi = min(rows + [path[-1][1], path[-2][1]]), max(rows + [path[-1][1], path[-2][1]])
        a, b = P(lane, lo), P(lane, hi)
        ax.plot([a[0], b[0]], [a[1], b[1]], color=col, lw=1.1)
        for rr in rows:
            a, b = P(lane, rr), P(CH, rr)
            ax.plot([a[0], b[0]], [a[1], b[1]], color=col, lw=1.1)
            ax.plot(*P(lane, rr), "o", ms=2, color=col)
    # power marks next to 5V and GND (left column)
    for i, lab, col in ((18, "5V  MT3608 VOUT+", "#e67e22"), (13, "GND  " + ar("كل السوالب"), "#111")):
        a = P(CL, R0 + i)
        b = P(CL - 2, R0 + i)
        ax.plot([a[0], b[0]], [a[1], b[1]], color=col, lw=1.1)
        ax.text(b[0] + (1 if mirror else -1), b[1], lab, va="center", ha="left" if mirror else "right", fontsize=3.6,
                color=col)
    ax.text(ox + W / 2, oy + 6, title, ha="center", fontsize=8.5, fontweight="bold")


def main() -> int:
    fig = plt.figure(figsize=(210 / 25.4, 297 / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 210); ax.set_ylim(0, 297); ax.set_aspect("equal"); ax.axis("off")
    W = (COLS - 1) * PITCH
    ox = (210 - W) / 2
    ax.text(105, 288, ar("بورد مثقّب 7 × 9 سم (بالعرض) - مقاس حقيقي 1:1 - اطبع بنسبة 100%"), ha="center",
            fontsize=10, fontweight="bold")
    draw(ax, ox, 268, False, ar("1) جهة القطع - من الأعلى: ضع الـ ESP32 ورأس الشاشة هنا"))
    draw(ax, ox, 168, True, ar("2) جهة اللحام (مقلوبة) - قصّها والصقها خلف البورد واتبع الأسلاك"))
    notes = [ar("• استعمل سلكاً رفيعاً معزولاً: الأسلاك تتقاطع"),
             ar("• النقطة الملوّنة = لحام السلك بدبوس الشاشة، الخط = مسار السلك"),
             ar("• SDO (دبوس 9) لا يوصل"),
             ar("• الشاحن والبطارية والمفتاح ورافع الجهد خارج البورد: سلكان فقط إلى 5V و GND"),
             ar("• المسطرة يجب أن تكون 50 مم بالضبط، وإلا فالطباعة ليست 1:1")]
    for j, t in enumerate(notes):
        ax.text(200, 95 - j * 6, t, ha="right", fontsize=8)
    ax.plot([10, 60], [20, 20], color="black", lw=1)
    for k in range(6):
        ax.plot([10 + 10 * k] * 2, [20, 22.5 if k % 5 == 0 else 21.5], color="black", lw=0.8)
    ax.text(35, 24, "50 mm", ha="center", fontsize=8)
    fig.savefig(OUT.with_suffix(".png"), dpi=300)
    # the PDF is made from the picture: Arabic stored as PDF text shows reversed in some viewers
    from PIL import Image
    Image.open(OUT.with_suffix(".png")).convert("RGB").save(OUT.with_suffix(".pdf"), resolution=300)
    plt.close(fig)
    print(f"saved {OUT}.png / .pdf")
    return 0


if __name__ == "__main__":
    sys.exit(main())
