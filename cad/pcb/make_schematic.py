#!/usr/bin/env python3
"""
make_schematic.py
Connection diagram (schematic) of the single-sided carrier board: ESP32 NodeMCU-32S (38 pins), the 14-pin
header for the 3.5" ILI9488 touch screen, the TP4056 USB-C charge module, a boost module to 5 V, the on/off
switch, solder pads for the battery and for a separate USB-C socket, and an optional relay connector.

Usage (needs: pip install matplotlib>=3.11):
    python cad/pcb/make_schematic.py        # writes cad/pcb/schematic.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parent / "schematic.png"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def ar(s):  # matplotlib 3.11 shapes and orders Arabic itself (reshaping again reversed it)
    return s


# screen header, in the order printed on the screen board (top to bottom), and where each pin goes
# pins as on the carrier board (2026-11-19): screen on its own bus, touch on its own bus, RESET on 3V3
SCREEN = [("T_IRQ", "21"), ("T_DO", "19"), ("T_DIN", "18"), ("T_CS", "5"), ("T_CLK", "17"), ("SDO(MISO)", None),
          ("LED", "3V3"), ("SCK", "16"), ("SDI(MOSI)", "4"), ("DC/RS", "2"), ("RESET", "3V3"), ("CS", "15"),
          ("GND", "GND"), ("VCC", "3V3")]
ESP = ["3V3", "GND", "5V", "2", "4", "5", "15", "16", "17", "18", "19", "21"]
COL = {"3V3": "#c0392b", "GND": "#111111", "5V": "#e67e22", "16": "#2f6fde", "4": "#8e44ad", "17": "#16a085",
       "18": "#16a085", "19": "#16a085", "21": "#16a085", "2": "#2e7d32", "5": "#16a085", "15": "#2e7d32"}


def block(ax, x, y, w, h, title, fc, ec="#1b2733", dashed=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.5", fc=fc, ec=ec, lw=1.6,
                                ls="--" if dashed else "-"))
    ax.text(x + w / 2, y + h + 2.2, title, ha="center", va="bottom", fontsize=11, fontweight="bold", color="#1b2733")


def main() -> int:
    fig, ax = plt.subplots(figsize=(16, 10.5))
    plt.rcParams["font.family"] = "DejaVu Sans"
    ax.set_xlim(0, 172); ax.set_ylim(-36, 104); ax.set_aspect("equal"); ax.axis("off")

    # screen header
    sx, sy0, step = 6, 92, 5.6
    block(ax, sx, sy0 - step * 13 - 3, 26, step * 13 + 6, ar("رأس الشاشة 14 دبوس (أنثى ملحوم)"), "#eaf1fb")
    spin = {}
    for k, (name, _) in enumerate(SCREEN):
        y = sy0 - k * step
        ax.text(sx + 2, y, f"{14 - k:>2}  {name}", va="center", fontsize=9, family="monospace")
        ax.plot(sx + 26, y, "o", ms=5, color="#1b2733")
        spin[k] = (sx + 26, y)

    # ESP32
    ex, ey0, estep = 92, 96, 6.2
    block(ax, ex, ey0 - estep * 12 - 3, 22, estep * 12 + 6, "ESP32 NodeMCU-32S (38 pin) - new pins", "#e8f6ef")
    epin = {}
    for k, name in enumerate(ESP):
        y = ey0 - k * estep
        label = name if not name.isdigit() else f"GPIO {name}"
        ax.text(ex + 4, y, label, va="center", fontsize=9, family="monospace")
        ax.plot(ex, y, "o", ms=5, color="#1b2733")
        epin[name] = (ex, y)

    # wires screen -> ESP32 (orthogonal, one bus column per ESP pin)
    cols = {name: 40 + i * 3.6 for i, name in enumerate(["3V3", "GND", "2", "4", "5", "15", "16", "17", "18", "19", "21"])}
    for k, (name, to) in enumerate(SCREEN):
        x0, y0 = spin[k]
        if to is None:
            ax.text(x0 + 2, y0, ar("لا يُوصل (يشوّش اللمس)"), va="center", fontsize=8.5, color="#b4531a")
            continue
        cx = cols[to]
        x1, y1 = epin[to]
        c = COL.get(to, "#555")
        ax.plot([x0, cx, cx, x1], [y0, y0, y1, y1], color=c, lw=1.4, alpha=0.9)
        ax.plot(cx, y0, "o", ms=2.5, color=c)

    # power chain
    block(ax, 130, -28, 26, 26, "TP4056 USB-C", "#e6f4f1")
    tp = {"IN+": (130, -6), "IN-": (130, -12), "B+": (156, -6), "B-": (156, -12), "OUT+": (156, -20), "OUT-": (130, -24)}
    for name, (x, y) in tp.items():
        ax.plot(x, y, "s", ms=6, color="#1b2733")
        ax.text(x + (2 if x == 130 else -2), y, name, va="center", ha="left" if x == 130 else "right", fontsize=9)

    block(ax, 92, -24, 22, 14, "MT3608  5.0V", "#fff3e0", ec="#e67e22")
    mt = {"VIN+": (114, -13), "VIN-": (114, -21), "VOUT+": (92, -13), "VOUT-": (92, -21)}
    for name, (x, y) in mt.items():
        ax.plot(x, y, "s", ms=6, color="#1b2733")
        ax.text(x + (-2 if x == 114 else 2), y, name, va="center", ha="right" if x == 114 else "left", fontsize=8.5)

    # switch between OUT+ and VIN+
    ax.plot([156, 162, 162, 127], [-20, -20, 4, 4], color="#c0392b", lw=1.6)
    ax.add_patch(FancyBboxPatch((119, 1), 8, 6, boxstyle="round,pad=0.2", fc="#ffffff", ec="#c0392b", lw=1.6))
    ax.text(123, 8.5, ar("مفتاح تشغيل"), ha="center", fontsize=9, color="#c0392b")
    ax.plot([119, 116, 116, 114], [4, 4, -13, -13], color="#c0392b", lw=1.6)
    # boost out -> ESP32 5V, grounds
    ax.plot([92, 86, 86, epin["5V"][0]], [-13, -13, epin["5V"][1], epin["5V"][1]], color="#e67e22", lw=1.8)
    ax.plot([92, 84, 84, epin["GND"][0]], [-21, -21, epin["GND"][1], epin["GND"][1]], color="#111", lw=1.4)
    ax.plot([114, 118, 118, 130], [-21, -21, -24, -24], color="#111", lw=1.4)

    # external pads
    def pads(x, y, title, labels, side):
        ax.text(x, y + 9, title, ha="center", fontsize=9.5, fontweight="bold", color="#1b2733")
        for i, lb in enumerate(labels):
            ax.add_patch(plt.Rectangle((x - 3, y - i * 7), 6, 5, fc="#d4a017", ec="#7a5c00"))
            ax.text(x + (5 if side == "r" else -5), y - i * 7 + 2.5, lb, va="center",
                    ha="left" if side == "r" else "right", fontsize=9)
    pads(165, -6, ar("باد البطارية"), ["B+", "B-"], "r")
    ax.plot([156, 162], [-6, -3.5], color="#c0392b", lw=1.4); ax.plot([156, 162], [-12, -10.5], color="#111", lw=1.4)
    pads(122, 26, ar("باد Type-C منفصل"), ["USB+", "USB-"], "l")
    ax.plot([125, 128, 128, 130], [28.5, 28.5, -6, -6], color="#e67e22", lw=1.4)
    ax.plot([125, 126.5, 126.5, 130], [21.5, 21.5, -12, -12], color="#111", lw=1.4)

    notes = [ar("! أضفنا رافع جهد، لأن جهد البطارية وحده لا يكفي اللوحة"),
             ar("! أضفنا مفتاح تشغيل بين الشاحن ورافع الجهد")]
    for i, n in enumerate(notes):
        ax.text(80, -10 - i * 6, n, ha="right", fontsize=10, color="#b4531a" if i < 2 else "#1b2733")
    ax.text(80, -30, ar("رسم توصيل للمراجعة، وليس رسم المسارات النهائي على البورد"), ha="right", fontsize=9, color="#5b6875")
    fig.tight_layout()
    fig.savefig(OUT, dpi=110)
    plt.close(fig)
    print(f"saved {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
