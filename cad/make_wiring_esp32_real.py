#!/usr/bin/env python3
"""
make_wiring_esp32_real.py
Printable wiring guide (A4 portrait) drawn on the REAL pin order of the NodeMCU ESP-32S (38 pins, USB-C), seen
from the FRONT (metal can and antenna on top, USB-C at the bottom): every screen wire goes to the real place of
its pin, with the same colour at both ends and the name written at both ends. Pins as in the firmware now
(ui.h, PINS_BREADBOARD 1). Power (TP4056, switch, MT3608) and the ESP32-C3 relay box at the bottom.

Usage (needs: pip install matplotlib arabic-reshaper python-bidi):
    python cad/make_wiring_esp32_real.py        # writes cad/wiring_esp32_real.png and .pdf
"""
import sys
from pathlib import Path

import arabic_reshaper
import matplotlib
from bidi.algorithm import get_display

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

OUT = Path(__file__).resolve().parent / "wiring_esp32_real"
ar = lambda s: get_display(arabic_reshaper.reshape(s))

# front view (chip up, antenna top, USB-C bottom), top to bottom - from the photo of the board (2026-11-23)
LEFT = ["3V3", "EN", "SVP", "SVN", "34", "35", "32", "33", "25", "26", "27", "14", "12", "GND", "13", "SD2", "SD3", "CMD", "5V"]
RIGHT = ["GND", "23", "22", "TX", "RX", "21", "GND", "19", "18", "5", "17", "16", "4", "0", "2", "15", "SD1", "SD0", "CLK"]
SCREEN = ["VCC", "GND", "CS", "RESET", "DC/RS", "SDI(MOSI)", "SCK", "LED", "SDO(MISO)", "T_CLK", "T_CS", "T_DIN", "T_DO", "T_IRQ"]
# screen pin -> (ESP32 side, row index), colour
WIRES = {"VCC": ("L", 0, "#c0392b"), "LED": ("L", 0, "#c0392b"), "GND": ("R", 0, "#111111"),
         "CS": ("R", 15, "#2e7d32"), "RESET": ("R", 12, "#00897b"), "DC/RS": ("R", 14, "#7cb342"),
         "SDI(MOSI)": ("R", 1, "#8e44ad"), "T_DIN": ("R", 1, "#8e44ad"), "SCK": ("R", 8, "#1e63d6"),
         "T_CLK": ("R", 8, "#1e63d6"), "T_DO": ("R", 7, "#e67e22"), "T_CS": ("R", 9, "#d81b60"),
         "T_IRQ": ("L", 4, "#6d4c41")}

X_L, X_R, Y0, P = 46.0, 112.0, 262.0, 7.4      # ESP32 pin rows and the top pin; pitch on paper
SX, SY0, SP = 176.0, 250.0, 8.6               # screen header


def ey(i):
    return Y0 - i * P


def main() -> int:
    fig, ax = plt.subplots(figsize=(8.27, 11.69))
    plt.rcParams["font.family"] = "DejaVu Sans"
    ax.set_xlim(0, 210); ax.set_ylim(0, 297); ax.set_aspect("equal"); ax.axis("off")
    ax.text(105, 290, ar("توصيل الشاشة مع ESP32 (الترتيب الحقيقي للأطراف، من الأمام)"), ha="center", fontsize=13,
            fontweight="bold")
    ax.text(105, 284, ar("كل سلك بلون واحد من طرفيه، واسمه مكتوب عند الطرفين"), ha="center", fontsize=9.5, color="#555")

    # ESP32 board, front view
    ax.add_patch(FancyBboxPatch((X_L - 8, ey(18) - 14), X_R - X_L + 16, 18 * P + 34, boxstyle="round,pad=0,rounding_size=3",
                                fc="#1b1f24", ec="#000"))
    ax.add_patch(Rectangle((X_L + 8, Y0 + 3), X_R - X_L - 16, 9, fc="#2b2f36", ec="#555"))
    ax.text((X_L + X_R) / 2, Y0 + 7.5, ar("الهوائي"), ha="center", va="center", fontsize=8, color="#bbb")
    ax.add_patch(Rectangle((X_L + 19, Y0 - 38), X_R - X_L - 38, 30, fc="#b9bec5", ec="#777"))
    ax.text((X_L + X_R) / 2, Y0 - 23, "ESP-32\n(metal can)", ha="center", va="center", fontsize=8)
    ax.add_patch(Rectangle(((X_L + X_R) / 2 - 7, ey(18) - 18), 14, 7, fc="#c9c9c9", ec="#555"))
    ax.text((X_L + X_R) / 2, ey(18) - 22, "USB-C", ha="center", va="top", fontsize=8)
    ax.text(X_L + 3, ey(18) - 9, "EN", fontsize=6.5, color="#ddd"); ax.text(X_R - 3, ey(18) - 9, "IO0", fontsize=6.5, color="#ddd", ha="right")
    for side, names, x in (("L", LEFT, X_L), ("R", RIGHT, X_R)):
        for i, n in enumerate(names):
            used = any(w[0] == side and w[1] == i for w in WIRES.values()) or (side == "L" and n in ("5V", "GND"))
            ax.add_patch(plt.Circle((x, ey(i)), 2.0, fc="#e0b84a" if used else "#777", ec="#000", lw=0.6))
            lab = n if not n.isdigit() else f"G{n}"
            ax.text(x + (5 if side == "L" else -5), ey(i), lab, va="center", ha="left" if side == "L" else "right",
                    fontsize=7.5, color="white", fontweight="bold" if used else "normal")

    # screen header
    ax.add_patch(FancyBboxPatch((SX - 4, SY0 - 13 * SP - 6), 30, 13 * SP + 12, boxstyle="round,pad=0,rounding_size=2",
                                fc="#fde8e8", ec="#c0392b"))
    ax.text(SX + 11, SY0 + 9, ar("الشاشة (14 دبوس)"), ha="center", fontsize=10, fontweight="bold")
    lanes = {}
    for k, name in enumerate(SCREEN):
        y = SY0 - k * SP
        ax.add_patch(Rectangle((SX - 1.6, y - 1.6), 3.2, 3.2, fc="#e0b84a", ec="#000", lw=0.6))
        ax.text(SX + 4, y, f"{k + 1}  {name}", va="center", fontsize=8, family="monospace")
        if name not in WIRES:
            ax.text(SX - 4, y, ar("لا يوصل"), va="center", ha="right", fontsize=7.5, color="#b4531a")
            continue
        side, i, col = WIRES[name]
        gp = (LEFT if side == "L" else RIGHT)[i]
        tag = gp if not gp.isdigit() else f"GPIO {gp}"
        ax.text(SX - 4, y + 2.2, tag, va="center", ha="right", fontsize=6.5, color=col, fontweight="bold")
        if side == "R":                                   # straight-ish wire to the right column
            lx = lanes.setdefault((side, i), 118 + 4.6 * len(lanes))
            ax.plot([X_R + 2, lx, lx, SX - 1.6], [ey(i), ey(i), y, y], color=col, lw=1.6)
        else:                                             # left column: tag only (the wire goes round the board)
            ax.plot([SX - 1.6, SX - 30], [y, y], color=col, lw=1.6)
            ax.plot(SX - 30, y, marker="<", color=col, ms=5)
    # tags on the ESP32 pins for the left-column wires and the right-column ones
    tags = {}
    for name, (side, i, col) in WIRES.items():
        tags.setdefault((side, i, col), []).append(name)
    for (side, i, col), names in tags.items():
        if side == "L":
            ax.text(X_L - 4, ey(i), ar("إلى الشاشة: ") + " + ".join(names) if False else " + ".join(names) + "  ←",
                    va="center", ha="right", fontsize=7, color=col, fontweight="bold")
    ax.text(X_L - 4, ey(18), "MT3608 VOUT+  ←", va="center", ha="right", fontsize=7, color="#e67e22", fontweight="bold")
    ax.text(X_L - 10, ey(13), ar("كل السوالب") + "  ←", va="center", ha="right", fontsize=7, color="#111", fontweight="bold")
    ax.text(X_L - 4, ey(0) - 3.5, ar("(سلكان: VCC و LED)"), va="center", ha="right", fontsize=6.5, color="#c0392b")
    ax.text(160, SY0 - 13 * SP - 20, ar("الأسهم ← تعني: السلك يذهب لطرف في العمود الأيسر للوحة"), ha="center",
            fontsize=7, color="#555")

    # power
    by = 52
    ax.text(105, by + 22, ar("الكهرباء"), ha="center", fontsize=11, fontweight="bold")
    blocks = [(8, ar("البطارية"), ["+", "-"]), (52, "TP4056", ["B+ / B-", "IN+ / IN-", "OUT+ / OUT-"]),
              (104, ar("مفتاح"), ["", ""]), (138, "MT3608 5.0V", ["VIN+ / VIN-", "VOUT+ / VOUT-"])]
    for x, t, rows in blocks:
        ax.add_patch(FancyBboxPatch((x, by - 8), 40 if x != 104 else 22, 22, boxstyle="round,pad=0,rounding_size=2",
                                    fc="#f4f6f8", ec="#333"))
        ax.text(x + (20 if x != 104 else 11), by + 10, t, ha="center", fontsize=9, fontweight="bold")
        for j, r in enumerate(rows):
            ax.text(x + (20 if x != 104 else 11), by + 3 - j * 5, r, ha="center", fontsize=7.5)
    steps = [ar("1) البطارية ← B+ و B- في الشاحن"), ar("2) منفذ Type-C المنفصل ← IN+ و IN- في الشاحن"),
             ar("3) OUT+ ← المفتاح ← VIN+ في رافع الجهد"),
             ar("4) VOUT+ ← 5V في ESP32 - اضبطه على 5.0 فولت قبل التوصيل"),
             ar("5) كل السوالب معاً: OUT- و VIN- و VOUT- و GND - ما عدا B-")]
    for j, t in enumerate(steps):
        ax.text(200, by - 14 - j * 5.6, t, ha="right", fontsize=8.5)

    # relay box
    ax.add_patch(FancyBboxPatch((8, 4), 68, 20, boxstyle="round,pad=0,rounding_size=2", fc="#eef3fb", ec="#2f6fde"))
    ax.text(42, 20, ar("عند الألواح: ESP32-C3"), ha="center", fontsize=8.5, fontweight="bold", color="#2f6fde")
    for j, t in enumerate(["GPIO 4 -> IN1 (pump)", "GPIO 5 -> IN2 (brush)", "5V / GND -> relay VCC / GND"]):
        ax.text(11, 15 - j * 4.5, t, fontsize=7.5, family="monospace")
    fig.savefig(OUT.with_suffix(".png"), dpi=200)
    fig.savefig(OUT.with_suffix(".pdf"))
    plt.close(fig)
    print(f"saved {OUT}.png / .pdf")
    return 0


if __name__ == "__main__":
    sys.exit(main())
