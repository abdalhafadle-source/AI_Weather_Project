#!/usr/bin/env python3
"""
make_pcb.py
Single-sided carrier board (one copper side, no jumper wires) for the handheld controller:
ESP32 NodeMCU-32S soldered directly, a 14-pin female header for the 3.5" screen, solder pads for the
TP4056 USB-C charger, the MT3608 boost (set to 5.0 V), the on/off switch, the battery and a separate USB-C socket.

The screen pins were re-assigned (firmware ui.h, 2026-11-19) so that no two traces cross:
    screen CS->15  DC->2  MOSI->4  SCK->16 | touch T_CLK->17  T_CS->5  T_DIN->18  T_DO->19  T_IRQ->21
    VCC, LED and RESET -> 3V3 (software reset); SDO not connected.

Usage (needs: pip install shapely matplotlib ezdxf):
    python cad/pcb/make_pcb.py            # writes cad/pcb/out/

Outputs (cad/pcb/out/):
    preview_parts_side.png   the board seen from the parts side, with names (check this first)
    laser_copper_side.svg    for the CO2 laser: BLACK = burn the paint away (copper will be etched there);
                             already MIRRORED, because the laser works on the copper side. Size 1:1, mm.
    laser_copper_side.png    the same as a 1000 dpi picture (for laser software that wants a raster image)
    drill.png                hole positions (each pad has a small etched pit in its centre to guide the drill)
A design-rule check runs every time: different nets must stay CLEAR mm apart, and every net must be one
connected piece of copper. The script stops if either fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.path import Path as MPath
from matplotlib.textpath import TextPath
from shapely.affinity import scale as sscale, translate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OUT = Path(__file__).resolve().parent / "out"

# ---------------- board and parts (mm, seen from the PARTS side, origin bottom-left) ----------------
W, L = 56.0, 106.0           # board size
PITCH = 2.54
ROW = 22.85                  # measured: ESP32 row centre to row centre
PAD_D, HOLE_D = 1.9, 0.9     # header / ESP32 pads
SIG, PWR = 0.8, 1.3          # trace widths
CLEAR = 0.5                  # minimum copper gap between different nets
PIT = 0.5                    # etched pit in each pad centre (drill guide)

CX = W / 2
XL, XR = CX - ROW / 2, CX + ROW / 2      # ESP32 left / right pin rows
YJ = L - 6.0                             # screen header row
YT = YJ - 18.0                           # ESP32 top pin (USB end towards the screen header)
YB = YT - 18 * PITCH                     # ESP32 bottom pin

# ESP32 NodeMCU-32S placed with the USB end up (towards the screen header), parts side up.
LEFT = ["CLK", "SD0", "SD1", "15", "2", "0", "4", "16", "17", "5", "18", "19", "GND", "21", "RX", "TX", "22", "23", "GND"]
RIGHT = ["5V", "CMD", "SD3", "SD2", "13", "GND", "12", "14", "27", "26", "25", "33", "32", "35", "34", "SVN", "SVP", "EN", "3V3"]
SCREEN = ["VCC", "GND", "CS", "RESET", "DC", "SDI", "SCK", "LED", "SDO", "T_CLK", "T_CS", "T_DIN", "T_DO", "T_IRQ"]
TO_GPIO = {"CS": "15", "DC": "2", "SDI": "4", "SCK": "16", "T_CLK": "17", "T_CS": "5", "T_DIN": "18", "T_DO": "19", "T_IRQ": "21"}


def jx(i):   # screen header pin i (1..14), x
    return CX - 6.5 * PITCH + (i - 1) * PITCH


def ly(i):   # ESP32 pin row index (0 = top), y
    return YT - i * PITCH


nets: dict[str, list] = {}       # net -> list of shapely geometries (copper)
pads: list[tuple] = []           # (x, y, d or (w,h), net, label)


def add(net, geom):
    nets.setdefault(net, []).append(geom)


def trace(net, pts, w=SIG):
    add(net, LineString(pts).buffer(w / 2, cap_style="round", join_style="round"))


def pad(net, x, y, d=PAD_D, label=None, square=False, size=None):
    if size:
        g = box(x - size[0] / 2, y - size[1] / 2, x + size[0] / 2, y + size[1] / 2)
    elif square:
        g = box(x - d / 2, y - d / 2, x + d / 2, y + d / 2)
    else:
        g = Point(x, y).buffer(d / 2, quad_segs=16)
    add(net, g)
    pads.append((x, y, net, label))


def build():
    # screen header (pin 1 square)
    for i, name in enumerate(SCREEN, 1):
        net = "3V3" if name in ("VCC", "LED", "RESET") else "GND" if name == "GND" else \
            "NC_SDO" if name == "SDO" else "G" + TO_GPIO[name]
        pad(net, jx(i), YJ, square=(i == 1), label=name)
    # ESP32 pins
    for i, n in enumerate(LEFT):
        pad("GND" if n == "GND" else "G" + n if n.isdigit() else "NC_L" + n + str(i), XL, ly(i), label=n)
    for i, n in enumerate(RIGHT):
        pad(n if n in ("5V", "3V3") else "NC_R" + n + str(i), XR, ly(i), label=n)   # right GND pin: joined inside the ESP32 board

    # 3V3: arch above the header joins VCC(1), RESET(4), LED(8), then down the right edge to the ESP32 3V3 pin
    ya = YJ + 3.0
    for i in (1, 4, 8):
        trace("3V3", [(jx(i), YJ), (jx(i), ya)], PWR)
    xr = W - 3.0
    trace("3V3", [(jx(1), ya), (xr, ya), (xr, ly(18)), (XR, ly(18))], PWR)

    # GND: header pin 2 straight down outside the left ESP32 row, into both left GND pins, on to the power area
    xg = jx(2)
    trace("GND", [(jx(2), YJ), (xg, 5.0)], PWR)
    for i in (12, 18):
        trace("GND", [(xg, ly(i)), (XL, ly(i))], PWR)

    # signals: fan out under the header, then lanes between the ESP32 rows, into the left row from inside
    order = ["15", "2", "4", "16", "17", "5", "18", "19", "21"]          # top to bottom on the left row
    lane = {g: XL + 2.1 + k * 1.5 for k, g in enumerate(order)}
    jog = {"15": YJ - 2.4}
    for k, g in enumerate(order[1:]):
        jog[g] = YJ - 3.6 - 1.4 * k
    for i, name in enumerate(SCREEN, 1):
        if name not in TO_GPIO:
            continue
        g = TO_GPIO[name]
        row = LEFT.index(g)
        trace("G" + g, [(jx(i), YJ), (jx(i), jog[g]), (lane[g], jog[g]), (lane[g], ly(row)), (XL, ly(row))])

    # power area ---------------------------------------------------------------
    x5 = XR - 2.6                                   # 5V lane, inside the right row
    yM = YB - 10.0                                  # MT3608 pad row
    trace("5V", [(XR, ly(0)), (x5, ly(0)), (x5, yM)], PWR)
    # MT3608: VOUT+ / VOUT- under the ESP32, VIN+ / VIN- to the right
    pad("5V", x5, yM, size=(3.0, 3.0), label="VOUT+")
    pad("GND", x5 - 6.0, yM, size=(3.0, 3.0), label="VOUT-")
    trace("GND", [(xg, 5.0), (x5 - 6.0, 5.0)], PWR)
    trace("GND", [(x5 - 6.0, 5.0), (x5 - 6.0, yM)], PWR)
    xa, xb = x5 + 7.0, x5 + 13.0
    pad("VIN", xa, yM, size=(3.0, 3.0), label="VIN+")
    pad("NC_VIN-", xb, yM, size=(3.0, 3.0), label="VIN-")
    # switch: SW2 -> VIN+, SW1 <- TP4056 OUT+
    yS = yM - 7.0
    pad("VIN", xa, yS, size=(3.0, 3.0), label="SW")
    pad("OUT", xb, yS, size=(3.0, 3.0), label="SW")
    trace("VIN", [(xa, yS), (xa, yM)], PWR)
    # TP4056: OUT+ / OUT- / B+ / B- / IN+ / IN-
    yT = yS - 7.0
    pad("OUT", xb, yT, size=(3.0, 3.0), label="OUT+")
    trace("OUT", [(xb, yT), (xb, yS)], PWR)
    pad("GND", xa, yT, size=(3.0, 3.0), label="OUT-")
    trace("GND", [(xa, yT), (xa, 5.0), (x5 - 6.0, 5.0)], PWR)
    # battery and USB-C: external solder pads at the left edge, the TP4056 wire pads beside them (left of the GND trunk)
    yP, xe, xm = yM, 4.0, 10.0
    for net, y, ext, mod in (("BAT+", yP, "BAT+", "B+"), ("BAT-", yP - 6.0, "BAT-", "B-"), ("USB+", yP - 13.0, "USB+", "IN+")):
        pad(net, xe, y, size=(3.5, 3.0), label=ext)
        pad(net, xm, y, size=(3.0, 3.0), label=mod)
        trace(net, [(xe, y), (xm, y)], PWR)
    pad("GND", xe, yP - 19.0, size=(3.5, 3.0), label="USB-")
    trace("GND", [(xe, yP - 19.0), (xg, yP - 19.0)], PWR)


def drc():
    """Different nets at least CLEAR apart; each net one connected piece. Returns the merged copper per net."""
    merged = {n: unary_union(g) for n, g in nets.items()}
    names = sorted(merged)
    bad = []
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            d = merged[names[a]].distance(merged[names[b]])
            if d < CLEAR - 1e-6:
                bad.append(f"{names[a]} <-> {names[b]}: {d:.2f} mm")
    pieces = [f"{n} ({len(g.geoms)} pieces)" for n, g in merged.items()
              if not n.startswith("NC") and g.geom_type == "MultiPolygon"]
    edge = [n for n, g in merged.items() if not box(0.6, 0.6, W - 0.6, L - 0.6).contains(g)]
    return merged, bad, pieces, edge


def text_poly(s, x, y, h=1.4, anchor="c"):
    tp = TextPath((0, 0), s, size=h, prop=FontProperties(family="DejaVu Sans", weight="bold"))
    polys = [Polygon(p) for p in tp.to_polygons() if len(p) > 2]
    # even-odd fill: letters with holes
    g = None
    for p in polys:
        g = p if g is None else g.symmetric_difference(p)
    if g is None:
        return None
    minx, miny, maxx, maxy = g.bounds
    dx = {"c": -(minx + maxx) / 2, "l": -minx, "r": -maxx}[anchor]
    g = translate(g, x + dx, y - (miny + maxy) / 2)
    # copper text is read from the COPPER side, which is the mirror of this parts-side drawing: pre-mirror it
    return sscale(g, xfact=-1, yfact=1, origin=(x + dx + (minx + maxx) / 2, y))


def main() -> int:
    build()
    merged, bad, pieces, edge = drc()
    print(f"board {W:g} x {L:g} mm, {len(pads)} pads, {len(merged)} nets")
    if bad or pieces or edge:
        for b in bad:
            print("CLEARANCE:", b)
        for p in pieces:
            print("NOT CONNECTED:", p)
        for e in edge:
            print("TOO CLOSE TO THE EDGE:", e)
        return 1
    print(f"DRC passed: every gap >= {CLEAR} mm, every net is one piece")

    copper = unary_union(list(merged.values()))
    labels = {"VCC": "1", "BAT+": "BAT+", "BAT-": "BAT-", "USB+": "USB+", "USB-": "USB-"}
    marks = []
    for x, y, net, lab in pads:      # copper text next to the external pads (readable from the copper side)
        if lab in labels and lab != "VCC":
            t = text_poly(lab, x, y + 2.7, h=1.5)
            marks.append(t)
    pin1 = text_poly("1", jx(1), YJ - 2.4, h=1.6)
    marks.append(pin1)
    marks = [m for m in marks if m is not None and m.distance(copper) >= CLEAR]
    copper_all = unary_union([copper] + marks)
    pits = unary_union([Point(x, y).buffer(PIT / 2, quad_segs=8) for x, y, _, _ in pads])
    board = box(0, 0, W, L)
    burn = board.difference(copper_all).union(pits)          # laser burns the paint here

    OUT.mkdir(parents=True, exist_ok=True)
    # ---------- preview from the parts side ----------
    fig, ax = plt.subplots(figsize=(7.5, 13))
    def fill(g, **kw):
        for p in (g.geoms if hasattr(g, "geoms") else [g]):
            ax.fill(*p.exterior.xy, **kw)
            for r in p.interiors:
                ax.fill(*r.xy, color="white")
    ax.add_patch(plt.Rectangle((0, 0), W, L, fc="#2b6e3f", ec="black"))
    fill(copper, color="#d9a441", alpha=0.75)
    for x, y, _, _ in pads:
        ax.add_patch(plt.Circle((x, y), HOLE_D / 2, color="#222"))
    ax.add_patch(plt.Rectangle((XL - 2.4, YB - 3.0), ROW + 4.8, 18 * PITCH + 6.0, fill=False, ec="#1d3557", lw=2, ls="--"))
    ax.text(CX, YB - 4.6, "ESP32 (USB up, antenna down)", ha="center", fontsize=8, color="white")
    ax.add_patch(plt.Rectangle((jx(1) - 1.4, YJ - 1.3), 13 * PITCH + 2.8, 2.6, fill=False, ec="#e8742c", lw=2))
    for i, n in enumerate(SCREEN, 1):
        ax.text(jx(i), YJ + 4.6 if i % 2 else YJ + 6.4, n, ha="center", fontsize=5.5, color="white", rotation=90)
    for x, y, net, lab in pads:
        if lab and len(lab) <= 5 and (x in (XL, XR)) and not lab.startswith("SD") and lab not in ("CLK", "CMD"):
            ax.text(x + (-1.6 if x == XL else 1.6), y, lab, ha="right" if x == XL else "left", va="center", fontsize=5, color="white")
        elif lab and x not in (XL, XR) and y != YJ:
            ax.text(x, y - 2.6, lab, ha="center", fontsize=5.5, color="white")
    ax.set_xlim(-2, W + 2); ax.set_ylim(-2, L + 2); ax.set_aspect("equal")
    ax.set_title(f"Parts side (copper shown through the board), {W:g} x {L:g} mm", fontsize=9)
    ax.axis("off")
    fig.tight_layout(); fig.savefig(OUT / "preview_parts_side.png", dpi=170); plt.close(fig)

    # ---------- laser file: copper side = mirror of the parts side ----------
    burn_m = sscale(burn, xfact=-1, yfact=1, origin=(W / 2, L / 2))
    def svg_path(g):
        d = []
        for p in (g.geoms if hasattr(g, "geoms") else [g]):
            for ring in [p.exterior, *p.interiors]:
                xs, ys = ring.xy
                d.append("M " + " L ".join(f"{x:.3f},{L - y:.3f}" for x, y in zip(xs, ys)) + " Z")
        return " ".join(d)
    (OUT / "laser_copper_side.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{L}mm" viewBox="0 0 {W} {L}">'
        f'<path d="{svg_path(burn_m)}" fill="#000" fill-rule="evenodd"/>'
        f'<rect x="0" y="0" width="{W}" height="{L}" fill="none" stroke="#f00" stroke-width="0.1"/></svg>',
        encoding="utf-8")
    dpi = 1000
    fig = plt.figure(figsize=(W / 25.4, L / 25.4), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(0, L); ax.axis("off")
    for p in (burn_m.geoms if hasattr(burn_m, "geoms") else [burn_m]):
        verts, codes = [], []
        for ring in [p.exterior, *p.interiors]:
            xs, ys = ring.xy
            pts = list(zip(xs, ys))
            verts += pts
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(pts) - 2) + [MPath.CLOSEPOLY]
        ax.add_patch(matplotlib.patches.PathPatch(MPath(verts, codes), fc="black", ec="none"))
    fig.savefig(OUT / "laser_copper_side.png", dpi=dpi); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 11))
    ax.add_patch(plt.Rectangle((0, 0), W, L, fill=False))
    for x, y, _, _ in pads:
        ax.plot(W - x, y, "k+", ms=4)
    ax.set_aspect("equal"); ax.set_title(f"Drill {len(pads)} holes, 0.9-1.0 mm (copper side view)", fontsize=9)
    fig.tight_layout(); fig.savefig(OUT / "drill.png", dpi=150); plt.close(fig)
    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
