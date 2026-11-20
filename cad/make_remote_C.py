#!/usr/bin/env python3
"""
make_remote_C.py
Shape C (portrait handheld with a sloped grip) as a 3D model for Fusion 360 / SolidWorks: STEP files (open in both)
and STL files (for a 3D printer). Two parts: a front shell (screen side) and a back cover, joined by
4 M2.5 screws from the back.

Usage (needs: pip install cadquery matplotlib shapely):
    python cad/make_remote_C.py             # writes cad/remote_C/

Outside: a thin head (screen) and a deeper grip below it with a sloped step between them (option 2,
chosen 2026-11-21, cad/grip_options_C.png). Inside, from the front to the back:
    screen module (glass rests on the window rim) -> carrier board cad/pcb (plugged into the screen header,
    screwed to 2 posts) -> flat LiPo battery 60 x 130 x 12 in the grip, behind the board (soft foam pad behind it).
USB-C socket and on/off switch in the bottom end wall.
Axes: X = width, Y = length (0 = bottom end), Z = depth (0 = front face, + towards the back).
ALL SIZES ARE IN MM. Check the numbers marked MEASURE against your parts before printing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cadquery as cq

sys.path.insert(0, str(Path(__file__).resolve().parent / "pcb"))
import make_pcb as pcb  # noqa: E402  (board size, header row and mounting holes stay in step with the board)

# ---------------- parameters ----------------
WALL = 2.0
BATT_W, BATT_L, BATT_T = 60.0, 130.0, 12.0   # battery with margin (user, 2026-11-21)
IN_W = BATT_W + 2.0            # inner width (board 56 and screen 56.3 fit too)
LEN = 180.0                    # same length as the first design
W, IN_L = IN_W + 2 * WALL, LEN - 2 * WALL
GRIP_Y1, SLOPE_END = 136.0, 166.0   # grip full depth up to GRIP_Y1, then the slope up to the head
BATT_Y0 = WALL + 2.0           # battery at the bottom of the grip
R_OUT = 9.0
# stack from the inner front face
GLASS = 5.8                    # measured: glass top above the screen board
MOD_T = 1.6                    # screen board thickness
MALE_HDR = 2.5                 # MEASURE: plastic of the screen's male header
FEMALE_HDR = 8.5               # MEASURE: height of the female header on our board
TAILS = 1.5                    # solder joints under the board
PCB_T = 1.6
Z_PCB = WALL + GLASS + MOD_T + MALE_HDR + FEMALE_HDR      # parts side of the board
D_HEAD = Z_PCB + PCB_T + TAILS + 0.5 + WALL      # head: screen + board (26)
D = Z_PCB + PCB_T + TAILS + BATT_T + 0.5 + WALL   # grip: + battery (38)
SPLIT_Z = Z_PCB + PCB_T        # front shell holds screen + board; back cover holds the battery
# screen module (measured 2026-11-18)
MOD_W, MOD_H = 56.3, 98.3
HDR_EDGE = 2.5                 # MEASURE: header row centre from the screen board's short edge
MOD_HOLE_IN_X, MOD_HOLE_IN_Y = 3.4, 3.1   # hole centres from the long / short edges
WIN_W, WIN_H = 52.5, 79.0      # smaller than the glass 55.6 x 85.55 (it rests on the rim), larger than the picture
USB_W, USB_H = 9.5, 3.8
SWITCH_W, SWITCH_L, SWITCH_HOLES = 4.0, 8.5, 15.0
Z_PORTS = WALL + 8.0           # USB-C and switch height in the bottom wall (free space in front of the board)
BOSS_D, PILOT_D, CLEAR_D = 5.0, 2.2, 2.8

Y_PCB = LEN - WALL - 1.0 - pcb.L   # board y = 0 (its bottom edge); the header end near the top
SCREWS = [(sx * (IN_W / 2 - 3.0), y) for sx in (-1, 1) for y in (WALL + 3.5, LEN - WALL - 3.5)]

OUT = Path(__file__).resolve().parent / "remote_C"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def bx(px):
    """Board x (parts-side drawing) -> box X. Seen from the front the parts side faces you, and +X points left."""
    return pcb.W / 2 - px


def rounded_block(w, l, cy, z0, z1, r):
    return (cq.Workplane("XY").workplane(offset=z0).center(0, cy).rect(w, l).extrude(z1 - z0)
            .edges("|Z").fillet(r))


def grip_solid(prof, w, l, r, round_edges):
    """Side profile (y, z) extruded across the width, trimmed to the rounded plan outline w x l."""
    g = cq.Workplane("YZ").polyline(prof).close().extrude(w / 2 + 1, both=True)
    if round_edges:
        try:
            g = g.edges("|X").fillet(round_edges)
        except Exception:
            pass
    return g.intersect(rounded_block(w, l, LEN / 2, -5, D + 5, r))


def body():
    from shapely.geometry import Polygon
    prof = [(0, 12), (0, D), (GRIP_Y1, D), (SLOPE_END, D_HEAD), (SLOPE_END + 4, 12)]
    head = rounded_block(W, LEN, LEN / 2, 0, D_HEAD, R_OUT).faces("<Z").edges().fillet(2.0)
    outer = head.union(grip_solid(prof, W, LEN, R_OUT, 6.0))
    inner_prof = list(Polygon(prof).buffer(-WALL, join_style=2).exterior.coords)[:-1]
    inner = rounded_block(IN_W, IN_L, LEN / 2, WALL, D_HEAD - WALL, R_OUT - WALL).union(
        grip_solid(inner_prof, IN_W, IN_L, R_OUT - WALL, 4.0))
    return outer.cut(inner)


def back_z(y):
    """Inner back face at length y (for the screw posts)."""
    return D - WALL if y < GRIP_Y1 else D_HEAD - WALL


def screen_box():
    """Screen board: its header row sits over the board's header row (pcb.YJ)."""
    top = Y_PCB + pcb.YJ + HDR_EDGE
    return top - MOD_H, top          # y0, y1


def cut_features(shell):
    y0, y1 = screen_box()
    win_cy = (y0 + y1) / 2           # glass centred on the screen board
    window = (cq.Workplane("XY").workplane(offset=-1).center(0, win_cy).rect(WIN_W, WIN_H).extrude(WALL + 2)
              .edges("|Z").fillet(2.0))
    shell = shell.cut(window)
    usb = cq.Workplane("XZ").workplane(offset=1).center(-12, Z_PORTS).slot2D(USB_W, USB_H).extrude(-(WALL + 2))
    sw = cq.Workplane("XZ").workplane(offset=1).center(12, Z_PORTS).slot2D(SWITCH_L, SWITCH_W).extrude(-(WALL + 2))
    for dx in (-SWITCH_HOLES / 2, SWITCH_HOLES / 2):
        sw = sw.union(cq.Workplane("XZ").workplane(offset=1).center(12 + dx, Z_PORTS).circle(1.1).extrude(-(WALL + 2)))
    return shell.cut(usb).cut(sw)


def posts():
    """Screen standoffs (height GLASS) and the two board posts (up to the board), with pilot holes."""
    y0, _ = screen_box()
    spts = [(sx * (MOD_W / 2 - MOD_HOLE_IN_X), y) for sx in (-1, 1)
            for y in (y0 + MOD_HOLE_IN_Y, y0 + MOD_H - MOD_HOLE_IN_Y)]
    s = (cq.Workplane("XY").workplane(offset=WALL).pushPoints(spts).circle(3.0).extrude(GLASS)
         .faces(">Z").workplane().pushPoints(spts).hole(PILOT_D, GLASS))
    bpts = [(bx(x), Y_PCB + y) for x, y in pcb.MOUNT]
    b = (cq.Workplane("XY").workplane(offset=WALL).pushPoints(bpts).circle(2.8).extrude(Z_PCB - WALL)
         .faces(">Z").workplane().pushPoints(bpts).hole(PILOT_D, 8))
    return s.union(b)


def screw_posts(front: bool):
    out = None
    for x, y in SCREWS:
        z0, z1 = (WALL, SPLIT_Z) if front else (SPLIT_Z, back_z(y))
        t = cq.Workplane("XY").workplane(offset=z0).center(x, y).circle(BOSS_D / 2).extrude(z1 - z0)
        out = t if out is None else out.union(t)
    return out


def screw_holes(front: bool):
    out = None
    for x, y in SCREWS:
        if front:
            h = cq.Workplane("XY").workplane(offset=WALL + 1).center(x, y).circle(PILOT_D / 2).extrude(SPLIT_Z)
        else:
            h = cq.Workplane("XY").workplane(offset=SPLIT_Z - 1).center(x, y).circle(CLEAR_D / 2).extrude(D)
            h = h.union(cq.Workplane("XY").workplane(offset=back_z(y) + WALL - 1.6).center(x, y).circle(2.6).extrude(3))
        out = h if out is None else out.union(h)
    return out


def build():
    shell = cut_features(body())
    big = 400
    front_half = cq.Workplane("XY").workplane(offset=-50).rect(big, big).extrude(50 + SPLIT_Z)
    back_half = cq.Workplane("XY").workplane(offset=SPLIT_Z).rect(big, big).extrude(100)
    front = shell.intersect(front_half).union(posts()).union(screw_posts(True)).cut(screw_holes(True))
    back = shell.intersect(back_half).union(screw_posts(False)).cut(screw_holes(False))
    return front, back


def preview(parts, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    fig = plt.figure(figsize=(12, 6))
    views = [("front shell (from the front)", parts[0], (20, -60)), ("back cover (from the back)", parts[1], (200, -60)),
             ("assembly", None, (25, 35))]
    for k, (title, part, (azim, elev)) in enumerate(views):
        ax = fig.add_subplot(1, 3, k + 1, projection="3d")
        for p, col in ([(part, "#9fb3c8")] if part is not None else [(parts[0], "#9fb3c8"), (parts[1], "#e8742c")]):
            verts, tris = p.val().tessellate(0.3, 0.3)
            pts = [(v.x, v.y, v.z) for v in verts]
            ax.add_collection3d(Poly3DCollection([[pts[i] for i in t] for t in tris], facecolor=col,
                                                 edgecolor="none", alpha=0.9))
        ax.set_xlim(-60, 60); ax.set_ylim(0, LEN); ax.set_zlim(-50, 70)
        ax.set_box_aspect((120, LEN, 120))
        ax.view_init(elev=elev if part is not None else 25, azim=azim)
        ax.set_title(title, fontsize=9)
        ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def section(path):
    """Side cut through the middle: what sits where in the depth (checks the stack at a glance)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    y0, y1 = screen_box()
    z_glass, z_mod = WALL, WALL + GLASS
    z_b = Z_PCB + PCB_T + TAILS
    items = [(0, LEN, 0, WALL, "#9fb3c8", "front"),
             (y0 + (MOD_H - 85.55) / 2, y1 - (MOD_H - 85.55) / 2, z_glass, z_mod, "#9ad1ff", "glass"),
             (y0, y1, z_mod, z_mod + MOD_T, "#c0392b", "screen board"),
             (Y_PCB + pcb.YJ - 1.3, Y_PCB + pcb.YJ + 1.3, z_mod + MOD_T, Z_PCB, "#222", "header"),
             (Y_PCB, Y_PCB + pcb.L, Z_PCB, Z_PCB + PCB_T, "#2b6e3f", "our board"),
             (Y_PCB + 52, Y_PCB + 104, Z_PCB - 7.6, Z_PCB, "#1d3557", "ESP32"),
             (Y_PCB + 11, Y_PCB + 47, Z_PCB - 8.0, Z_PCB, "#555", "MT3608"),
             (BATT_Y0, BATT_Y0 + BATT_L, z_b, z_b + BATT_T, "#d4a017", "battery 60x130x12")]
    fig, ax = plt.subplots(figsize=(12, 4))
    for a, b, c, d, col, name in items:
        ax.add_patch(plt.Rectangle((a, c), b - a, d - c, fc=col, ec="black", lw=0.5, alpha=0.85))
        if name not in ("front", "back"):
            ax.text((a + b) / 2, (c + d) / 2, name, ha="center", va="center", fontsize=7,
                    color="white" if col in ("#222", "#1d3557", "#2b6e3f", "#555", "#c0392b") else "black")
    ax.add_patch(plt.Polygon([(0, 0), (LEN, 0), (LEN, D_HEAD), (SLOPE_END, D_HEAD), (GRIP_Y1, D), (0, D)],
                             closed=True, fill=False, ec="black", lw=1.5))
    ax.set_xlim(-5, LEN + 5); ax.set_ylim(D + 3, -3); ax.set_aspect("equal")
    ax.set_xlabel("length (mm), 0 = bottom end with USB-C and switch"); ax.set_ylabel("depth (mm), 0 = front")
    ax.set_title(f"Shape C - side cut: {W:g} x {LEN:g} mm, depth {D_HEAD:.0f} (head) / {D:.0f} (grip) mm", fontsize=10)
    fig.tight_layout(); fig.savefig(path, dpi=120); plt.close(fig)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    front, back = build()
    for name, part in (("remote_C_front", front), ("remote_C_back", back)):
        cq.exporters.export(part, str(OUT / f"{name}.step"))
        cq.exporters.export(part, str(OUT / f"{name}.stl"), tolerance=0.05, angularTolerance=0.2)
        bb = part.val().BoundingBox()
        print(f"{name:<16} {bb.xlen:5.1f} x {bb.ylen:5.1f} x {bb.zlen:4.1f} mm   volume {part.val().Volume() / 1000:5.1f} cm3   valid {part.val().isValid()}")
    cq.exporters.export(cq.Workplane().add(cq.Compound.makeCompound([front.val(), back.val()])),
                        str(OUT / "remote_C_assembly.step"))
    preview((front, back), OUT / "preview.png")
    section(OUT / "section.png")
    y0, y1 = screen_box()
    print(f"outer {W:g} x {LEN:g} mm, depth {D_HEAD:.1f} / {D:.1f}; screen board y {y0:.1f}..{y1:.1f}; board parts side at z={Z_PCB:.1f}")
    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
