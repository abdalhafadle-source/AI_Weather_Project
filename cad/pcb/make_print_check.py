#!/usr/bin/env python3
"""
make_print_check.py
The board seen from the PARTS side at 1:1 (not mirrored) as a DXF, to print on paper and lay the real parts on it:
copper outlines, every hole, the ESP32 / screen header / TP4056 / MT3608 outlines, the names, and a 100 mm ruler
(measure it on the paper: it must be exactly 100 mm, or the print is not 1:1).

Usage:  python cad/pcb/make_print_check.py      -> cad/pcb/out/print_parts_side_1to1.dxf
"""
import sys
from pathlib import Path

import ezdxf
from shapely.geometry import Polygon
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_pcb as P  # noqa: E402

OUT = P.OUT / "print_parts_side_1to1.dxf"


def main() -> int:
    P.build()
    copper = unary_union([g for gs in P.nets.values() for g in gs])
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    for name, col in (("BOARD", 7), ("COPPER", 7), ("HOLES", 7), ("PARTS", 7), ("TEXT", 7)):
        doc.layers.add(name, color=col)

    msp.add_lwpolyline([(0, 0), (P.W, 0), (P.W, P.L), (0, P.L)], close=True, dxfattribs={"layer": "BOARD", "lineweight": 50})
    for poly in (copper.geoms if hasattr(copper, "geoms") else [copper]):
        for ring in [poly.exterior, *poly.interiors]:
            msp.add_lwpolyline(list(ring.coords), close=True, dxfattribs={"layer": "COPPER", "lineweight": 13})
    for x, y, _, _ in P.pads:
        msp.add_circle((x, y), P.HOLE_D / 2, dxfattribs={"layer": "HOLES"})
    for x, y in P.MOUNT:
        msp.add_circle((x, y), P.MOUNT_D / 2, dxfattribs={"layer": "HOLES"})

    def rect(x0, y0, w, h, label, ty=None):
        msp.add_lwpolyline([(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)], close=True,
                           dxfattribs={"layer": "PARTS", "linetype": "DASHED", "ltscale": 0.15})
        if label:
            msp.add_text(label, height=2.2, dxfattribs={"layer": "TEXT"}).set_placement(
                (x0 + w / 2, ty if ty is not None else y0 + h / 2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    rect(P.XL - 2.4, P.YB - 3.0, P.ROW + 4.8, 18 * P.PITCH + 6.0, "ESP32 (USB up)", P.YB + 20)
    rect(P.jx(1) - 1.4, P.YJ - 1.3, 13 * P.PITCH + 2.8, 2.6, None)
    rect(P.MT_X0, P.MT_Y0, P.MT_W, P.MT_L, "MT3608")
    rect(P.TP_X0, P.TP_Y0, P.TP_W, P.TP_L, "TP4056")
    for i, n in enumerate(P.SCREEN, 1):
        t = msp.add_text(n, height=1.3, rotation=90, dxfattribs={"layer": "TEXT"})
        t.set_placement((P.jx(i), P.YJ + 4.2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_LEFT)
    for x, y, _, lab in P.pads:
        if lab and x not in (P.XL, P.XR) and y != P.YJ:
            msp.add_text(lab, height=1.1, dxfattribs={"layer": "TEXT"}).set_placement(
                (x, y - 2.6), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    # 100 mm ruler + title, beside the board
    rx = P.W + 12
    msp.add_line((rx, 10), (rx, 110), dxfattribs={"layer": "BOARD", "lineweight": 35})
    for k in range(11):
        msp.add_line((rx, 10 + 10 * k), (rx + (4 if k % 5 == 0 else 2), 10 + 10 * k), dxfattribs={"layer": "BOARD"})
    t = msp.add_text("100 mm - measure this", height=2.5, rotation=90, dxfattribs={"layer": "TEXT"})
    t.set_placement((rx + 8, 60), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    msp.add_text(f"Board {P.W:g} x {P.L:g} mm, parts side, 1:1", height=3,
                 dxfattribs={"layer": "TEXT"}).set_placement((0, P.L + 4))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(OUT)
    print(f"written {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
