#!/usr/bin/env python3
"""
make_acrylic_A.py
Shape A (handheld box) as flat panels for a laser cutter: 3 mm acrylic, finger joints, a removable back.

Usage (needs: pip install shapely ezdxf matplotlib):
    python cad/make_acrylic_A.py            # writes cad/acrylic_A/

Box: front panel + 4 walls joined by finger joints (glue them with acrylic cement), a flat back panel, and
4 M3 brass standoffs (length = DEPTH - 2*T) in the inner corners. M3 screws go through the front panel into
the standoffs and through the back panel into them: the back opens for the battery, the box is clamped.
The screen module is screwed behind the front panel (one M3 nut as spacer on each screw) and its glass
passes through the window, standing GLASS_PROUD mm out of the front (resistive touch needs a bare surface).

Outputs (cad/acrylic_A/):
    acrylic_A_all.dxf   every panel, layer CUT = cut lines, layer NOTES = names (do not cut)
    acrylic_A_all.svg   the same cut lines (for shops that want SVG)
    preview.png         a picture of all panels with their names
ALL SIZES ARE IN MM. Measure your screen module and check the numbers marked MEASURE before cutting.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

# ---------------- parameters ----------------
T = 3.0                    # acrylic thickness
KERF = 0.10                # laser kerf (line width); outlines grow and holes shrink by KERF/2
LENGTH, HEIGHT, DEPTH = 118.0, 74.0, 36.0   # outer box size; DEPTH - 2T = standoff length (30 mm)
N_LEN, N_HEI, N_DEP = 11, 7, 3              # finger counts per edge (odd numbers)

MOD_W, MOD_H = 98.3, 56.3  # measured 2026-11-18: screen module board (ILI9488 3.5")
MOD_HOLE_IN_X = 3.1        # measured: hole centre from the SHORT edge (rim 1.60 + radius 1.5)
MOD_HOLE_IN_Y = 3.4        # measured: hole centre from the LONG edge (rim 1.90 + radius 1.5)
MOD_HOLE_D = 3.2           # board holes are 3.0; M3 clearance
# glass measured 85.55 x 55.60, centred on the board. The glass passes THROUGH the window and comes out
# flush with the front: window = glass + 0.3 mm play each side, almost square corners (the glass has square corners)
GLASS_W, GLASS_H = 85.55, 55.60
WIN_PLAY = 0.3
WIN_W, WIN_H = GLASS_W + 2 * WIN_PLAY, GLASS_H + 2 * WIN_PLAY
WIN_R = 0.5
WIN_OFF_X = 0.0            # glass centred on the board
GLASS = 5.8                # measured: glass top above the board
SPACER = 2.4               # between the board and the acrylic: one M3 nut (2.4 mm) per screw
GLASS_PROUD = GLASS - T - SPACER   # how far the glass stands out of the front (0.4 mm)
CORNER_HOLE = 6.2          # standoff holes, distance from the outer edges (M3 hex standoff, 5 mm across flats)
USB_W, USB_H = 9.5, 3.8    # USB-C slot
USB_FROM_BACK = 5.0        # USB-C centre, mm in front of the back panel's inner face
SWITCH_W, SWITCH_L, SWITCH_HOLES = 4.0, 8.5, 15.0   # mini slide switch: slot and its two M2 holes
GAP = 6.0                  # space between panels on the sheet

OUT = Path(__file__).resolve().parent / "acrylic_A"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def fingers(w, h, edges):
    """Panel w x h with finger strips. edges = {'b','r','t','l'}: ('F'|'f', n) or None (plain edge, no strip).
    'F' starts and ends with a finger (out), 'f' is its complement; with odd n both are symmetric."""
    order = ["b", "r", "t", "l"]
    has = {e: edges[e] is not None for e in order}
    x0, y0 = (T if has["l"] else 0), (T if has["b"] else 0)
    x1, y1 = (w - T if has["r"] else w), (h - T if has["t"] else h)
    parts = [box(x0, y0, x1, y1)]
    for e in order:
        if not has[e]:
            continue
        kind, n = edges[e]
        horiz = e in ("b", "t")
        a = (x0 if horiz else y0)
        z = (x1 if horiz else y1)
        s = (z - a) / n
        for k in range(n):
            out = (k % 2 == 0) if kind == "F" else (k % 2 == 1)
            if not out:
                continue
            p, q = a + k * s, a + (k + 1) * s
            parts.append({"b": box(p, 0, q, T), "t": box(p, h - T, q, h),
                          "l": box(0, p, T, q), "r": box(w - T, p, w, q)}[e])
    end_out = lambda e: has[e] and edges[e][0] == "F"
    for (e1, e2), sq in {("b", "l"): box(0, 0, T, T), ("b", "r"): box(w - T, 0, w, T),
                         ("t", "l"): box(0, h - T, T, h), ("t", "r"): box(w - T, h - T, w, h)}.items():
        if end_out(e1) and end_out(e2):
            parts.append(sq)
    return unary_union(parts)


def slot(cx, cy, w, h):
    """Rounded slot w x h centred at (cx, cy)."""
    r = min(w, h) / 2
    return box(cx - w / 2 + r, cy - h / 2 + r, cx + w / 2 - r, cy + h / 2 - r).buffer(r, quad_segs=16)


def hole(cx, cy, d):
    return Point(cx, cy).buffer(d / 2, quad_segs=24)


def rrect(cx, cy, w, h, r):
    return box(cx - w / 2 + r, cy - h / 2 + r, cx + w / 2 - r, cy + h / 2 - r).buffer(r, quad_segs=12)


def build():
    L, H, D = LENGTH, HEIGHT, DEPTH
    WALL = D - T                      # walls run from the front face to the back panel
    corner = [(CORNER_HOLE, CORNER_HOLE), (L - CORNER_HOLE, CORNER_HOLE),
              (CORNER_HOLE, H - CORNER_HOLE), (L - CORNER_HOLE, H - CORNER_HOLE)]
    mx, my = (L - MOD_W) / 2, (H - MOD_H) / 2   # screen board centred in the box
    mod_holes = [(mx + dx, my + dy) for dx in (MOD_HOLE_IN_X, MOD_W - MOD_HOLE_IN_X)
                 for dy in (MOD_HOLE_IN_Y, MOD_H - MOD_HOLE_IN_Y)]

    front = fingers(L, H, {"b": ("F", N_LEN), "t": ("F", N_LEN), "l": ("F", N_HEI), "r": ("F", N_HEI)})
    cuts = [rrect(L / 2 + WIN_OFF_X, H / 2, WIN_W, WIN_H, WIN_R)] + [hole(x, y, MOD_HOLE_D) for x, y in mod_holes]
    cuts += [hole(x, y, 3.2) for x, y in corner]
    front = front.difference(unary_union(cuts))

    back = box(0, 0, L, H)
    vents = [slot(L / 2 + dx, H / 2, 2.5, 22) for dx in (-21, -14, -7, 0, 7, 14, 21)]
    back = back.difference(unary_union([hole(x, y, 3.2) for x, y in corner] + vents))

    # walls: x along the wall, y from the front face (0) to the back panel (WALL); front edge has fingers into
    # the front panel, the back edge is plain (the flat back panel covers it)
    def wall(length, n_len, n_side):
        return fingers(length, WALL, {"b": ("f", n_len), "t": None, "l": ("F", n_side), "r": ("F", n_side)})

    def side(n_side):
        return fingers(H, WALL, {"b": ("f", N_HEI), "t": None, "l": ("f", n_side), "r": ("f", n_side)})

    top = wall(L, N_LEN, N_DEP)
    bottom = wall(L, N_LEN, N_DEP)
    usb_y = WALL - USB_FROM_BACK
    bottom = bottom.difference(unary_union([slot(L / 2, usb_y, USB_W, USB_H), hole(L / 2 + 11, usb_y, 3.0)]))
    left = side(N_DEP)
    right = side(N_DEP)
    sx, sy = H * 0.6, WALL / 2        # switch: along the wall (height), in the middle of the depth
    right = right.difference(unary_union([slot(sx, sy, SWITCH_L, SWITCH_W),
                                          hole(sx - SWITCH_HOLES / 2, sy, 2.2), hole(sx + SWITCH_HOLES / 2, sy, 2.2)]))
    return [("FRONT (screen side)", front), ("BACK (removable)", back), ("TOP wall", top),
            ("BOTTOM wall (USB-C + LED)", bottom), ("LEFT wall", left), ("RIGHT wall (switch)", right)]


def layout(panels):
    """Place panels in three rows (front+back, top+bottom, left+right): fits an A4 sheet.
    Returns [(name, polygon placed)]."""
    from shapely.affinity import translate
    placed, x, y, row_h = [], 0.0, 0.0, 0.0
    for i, (name, p) in enumerate(panels):
        p = p.buffer(KERF / 2, join_style="mitre") if KERF else p
        minx, miny, maxx, maxy = p.bounds
        if i in (2, 4):                                   # next row
            x, y, row_h = 0.0, y + row_h + GAP, 0.0
        placed.append((name, translate(p, x - minx, y - miny)))
        x += (maxx - minx) + GAP
        row_h = max(row_h, maxy - miny)
    return placed


def rings(poly):
    polys = [poly] if isinstance(poly, Polygon) else list(poly.geoms)
    for g in polys:
        yield list(g.exterior.coords)
        for r in g.interiors:
            yield list(r.coords)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    placed = layout(build())
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    doc.layers.add("CUT", color=1)
    doc.layers.add("NOTES", color=5)
    msp = doc.modelspace()
    svg = []
    W = max(p.bounds[2] for _, p in placed) + 2
    Hs = max(p.bounds[3] for _, p in placed) + 2
    for name, p in placed:
        for ring in rings(p):
            msp.add_lwpolyline([(round(a, 4), round(b, 4)) for a, b in ring], close=True, dxfattribs={"layer": "CUT"})
            svg.append('<path d="M ' + " L ".join(f"{a:.3f},{Hs - b:.3f}" for a, b in ring) + ' Z"/>')
        minx, miny, maxx, maxy = p.bounds
        msp.add_text(name, height=3.0, dxfattribs={"layer": "NOTES"}).set_placement((minx, maxy + 1.5))
    dxf = OUT / "acrylic_A_all.dxf"
    doc.saveas(dxf)
    (OUT / "acrylic_A_all.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.1f}mm" height="{Hs:.1f}mm" viewBox="0 0 {W:.3f} {Hs:.3f}">'
        f'<g fill="none" stroke="#ff0000" stroke-width="0.1">{"".join(svg)}</g></svg>', encoding="utf-8")

    fig, ax = plt.subplots(figsize=(11, 7))
    for name, p in placed:
        for ring in rings(p):
            xs, ys = zip(*ring)
            ax.plot(xs, ys, color="#c0392b", lw=0.8)
        minx, miny, maxx, maxy = p.bounds
        ax.text(minx, maxy + 1.5, name, fontsize=8, color="#1d3557")
    ax.set_aspect("equal")
    ax.set_title(f"Shape A - {T:g} mm acrylic, outer {LENGTH:g} x {HEIGHT:g} x {DEPTH:g} mm (sheet {W:.0f} x {Hs:.0f} mm)")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "preview.png", dpi=130)
    plt.close(fig)

    for name, p in placed:
        minx, miny, maxx, maxy = p.bounds
        print(f"{name:<28} {maxx - minx:6.1f} x {maxy - miny:5.1f} mm")
    print(f"sheet needed: {W:.0f} x {Hs:.0f} mm  ->  {dxf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
