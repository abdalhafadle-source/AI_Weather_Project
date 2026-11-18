#!/usr/bin/env python3
"""
make_remote_C.py
Shape C (portrait remote with a grip) as a 3D model for Fusion 360 / SolidWorks: STEP files (open in both)
and STL files (for a 3D printer). Two parts: a front shell (screen side) and a back cover, joined by
4 M2.5 screws from the back.

Usage (needs: pip install cadquery matplotlib):
    python cad/make_remote_C.py             # writes cad/remote_C/

Inside: the screen module (portrait) in the upper part behind an open window (resistive touch needs it);
the grip (deeper) holds an 18650 cell, the ESP32 and the USB-C charge module side by side.
Axes: X = width, Y = length (0 = bottom, USB-C end), Z = depth (0 = front face, + towards the back).
ALL SIZES ARE IN MM. Check the numbers marked MEASURE against your parts before printing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cadquery as cq

# ---------------- parameters ----------------
W, LEN = 70.0, 176.0        # outer width and length
D_TOP, D_GRIP = 22.0, 30.0  # depth of the screen part and of the grip
WALL = 2.0
GRIP_Y0, GRIP_Y1 = 4.0, 80.0   # grip (deeper part) along the length
GRIP_W = 64.0
SPLIT_Z = 10.0              # front shell = z < SPLIT_Z, back cover = z > SPLIT_Z
WIN_W, WIN_H = 51.0, 75.5   # MEASURE: visible screen (49.0 x 73.4) + about 1 mm each side
WIN_TOP_MARGIN = 12.0
MOD_W, MOD_H = 56.0, 98.0   # MEASURE: screen module board, portrait
MOD_BELOW_WIN = 14.0        # MEASURE: board edge below the window (pin-header side)
MOD_HOLE_INSET = 3.5        # MEASURE: board corner hole centre from the board edges
GLASS = 4.5                 # MEASURE: glass + touch film height above the board (standoff height)
BUTTON_D = 12.5             # optional quick-wash push button (0 = none)
USB_W, USB_H, USB_Z = 9.5, 3.8, 15.0
SWITCH_W, SWITCH_L, SWITCH_HOLES, SWITCH_Y, SWITCH_Z = 4.0, 8.5, 15.0, 140.0, 6.0
SCREWS = [(-30.5, 120.0), (30.5, 120.0), (-26.5, 12.0), (26.5, 12.0)]   # M2.5 screw posts
BOSS_D, PILOT_D, CLEAR_D = 5.4, 2.2, 2.8

OUT = Path(__file__).resolve().parent / "remote_C"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def rounded_block(w, l, cy, z0, z1, r):
    """Box w x l centred at (0, cy), from z0 to z1, vertical edges rounded r."""
    return (cq.Workplane("XY").workplane(offset=z0).center(0, cy).rect(w, l).extrude(z1 - z0)
            .edges("|Z").fillet(r))


def body():
    top = rounded_block(W, LEN, LEN / 2, 0, D_TOP, 9).faces("<Z").edges().fillet(2.0)
    grip_len = GRIP_Y1 - GRIP_Y0
    grip = rounded_block(GRIP_W, grip_len, GRIP_Y0 + grip_len / 2, D_TOP - 1, D_GRIP, 10).faces(">Z").edges().fillet(3.0)
    outer = top.union(grip)
    top_in = rounded_block(W - 2 * WALL, LEN - 2 * WALL, LEN / 2, WALL, D_TOP - WALL, 7)
    grip_in = rounded_block(GRIP_W - 2 * WALL, grip_len - 2 * WALL, GRIP_Y0 + grip_len / 2, D_TOP - WALL - 0.5,
                            D_GRIP - WALL, 8)
    return outer.cut(top_in.union(grip_in))


def cut_features(shell):
    win_cy = LEN - WIN_TOP_MARGIN - WIN_H / 2
    window = (cq.Workplane("XY").workplane(offset=-1).center(0, win_cy).rect(WIN_W, WIN_H).extrude(WALL + 2)
              .edges("|Z").fillet(2.0))
    shell = shell.cut(window)
    if BUTTON_D:
        shell = shell.cut(cq.Workplane("XY").workplane(offset=-1).center(0, 42).circle(BUTTON_D / 2).extrude(WALL + 2))
    usb = (cq.Workplane("XZ").workplane(offset=1).center(0, USB_Z).slot2D(USB_W, USB_H).extrude(-(WALL + 2)))
    shell = shell.cut(usb)
    sw = (cq.Workplane("YZ").workplane(offset=W / 2 - WALL - 1).center(SWITCH_Y, SWITCH_Z)
          .slot2D(SWITCH_L, SWITCH_W).extrude(WALL + 2))
    for dy in (-SWITCH_HOLES / 2, SWITCH_HOLES / 2):
        sw = sw.union(cq.Workplane("YZ").workplane(offset=W / 2 - WALL - 1).center(SWITCH_Y + dy, SWITCH_Z)
                      .circle(1.1).extrude(WALL + 2))
    return shell.cut(sw), win_cy


def screen_posts(win_cy):
    """Standoffs on the inside of the front face for the screen board (height = GLASS)."""
    y0 = win_cy - WIN_H / 2 - MOD_BELOW_WIN
    pts = [(sx * (MOD_W / 2 - MOD_HOLE_INSET), y) for sx in (-1, 1)
           for y in (y0 + MOD_HOLE_INSET, y0 + MOD_H - MOD_HOLE_INSET)]
    posts = (cq.Workplane("XY").workplane(offset=WALL).pushPoints(pts).circle(3.0).extrude(GLASS)
             .faces(">Z").workplane().pushPoints(pts).hole(PILOT_D, GLASS))
    return posts, y0


def screw_posts(front: bool):
    """Tubes joining the two parts: in the front shell from the front face to SPLIT_Z (pilot hole),
    in the back cover from SPLIT_Z to the back face (clearance hole, screw head from the back)."""
    out = None
    for x, y in SCREWS:
        back_z = D_GRIP - WALL if GRIP_Y0 + 2 < y < GRIP_Y1 - 2 else D_TOP - WALL
        z0, z1 = (WALL, SPLIT_Z) if front else (SPLIT_Z, back_z)
        tube = cq.Workplane("XY").workplane(offset=z0).center(x, y).circle(BOSS_D / 2).extrude(z1 - z0)
        out = tube if out is None else out.union(tube)
    return out


def screw_holes(front: bool):
    out = None
    for x, y in SCREWS:
        back_z = D_GRIP if GRIP_Y0 + 2 < y < GRIP_Y1 - 2 else D_TOP
        if front:
            h = cq.Workplane("XY").workplane(offset=WALL + 1).center(x, y).circle(PILOT_D / 2).extrude(SPLIT_Z)
        else:
            h = (cq.Workplane("XY").workplane(offset=SPLIT_Z - 1).center(x, y).circle(CLEAR_D / 2)
                 .extrude(back_z - SPLIT_Z + 2))
            h = h.union(cq.Workplane("XY").workplane(offset=back_z - 1.6).center(x, y).circle(2.6).extrude(3))
        out = h if out is None else out.union(h)
    return out


def build():
    shell, win_cy = cut_features(body())
    posts, mod_y0 = screen_posts(win_cy)
    big = 400
    front_half = cq.Workplane("XY").workplane(offset=-50).rect(big, big, centered=True).extrude(50 + SPLIT_Z)
    back_half = cq.Workplane("XY").workplane(offset=SPLIT_Z).rect(big, big, centered=True).extrude(100)
    front = shell.intersect(front_half).union(posts).union(screw_posts(True)).cut(screw_holes(True))
    back = shell.intersect(back_half).union(screw_posts(False)).cut(screw_holes(False))
    return front, back, mod_y0


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


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    front, back, mod_y0 = build()
    for name, part in (("remote_C_front", front), ("remote_C_back", back)):
        cq.exporters.export(part, str(OUT / f"{name}.step"))
        cq.exporters.export(part, str(OUT / f"{name}.stl"), tolerance=0.05, angularTolerance=0.2)
        bb = part.val().BoundingBox()
        print(f"{name:<16} {bb.xlen:5.1f} x {bb.ylen:5.1f} x {bb.zlen:4.1f} mm   volume {part.val().Volume() / 1000:5.1f} cm3   valid {part.val().isValid()}")
    cq.exporters.export(cq.Workplane().add(cq.Compound.makeCompound([front.val(), back.val()])),
                        str(OUT / "remote_C_assembly.step"))
    preview((front, back), OUT / "preview.png")
    print(f"screen board from y={mod_y0:.1f} to {mod_y0 + MOD_H:.1f} mm (inner top wall at {LEN - WALL:.1f})")
    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
