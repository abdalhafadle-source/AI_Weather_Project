#!/usr/bin/env python3
"""
download_metar.py
Download airport weather reports (METAR) near Hilla as free real observations of dust:
Najaf ORNI (~60 km) and Baghdad ORBI (~90 km). Source: Iowa Environmental Mesonet archive.

Usage (terminal, inside the folder that contains this file):
    python download_metar.py
    python download_metar.py --end 2026-10-29

Outputs:
    data/raw_metar/metar_raw.csv         all reports: station, valid (UTC), vsby (miles), wxcodes
    data/raw_hilla_extra/metar.csv       hourly, local time (Asia/Baghdad = UTC+3):
                                         time, any_dust, min_vis_km, available, strong_dust
A report is "dust" if a weather code contains DU, SA, DS, SS or PO, or (HZ and visibility < 5 km).
Per station each hour keeps max dust / min visibility, filled forward at most 2 h; then the
stations are combined (any_dust = max, min_vis_km = min, 10 if no data, available = stations with data).
One year per request is cached in data/raw_metar/_chunks (the current year is always re-downloaded).

Data: Iowa Environmental Mesonet (METAR archive); Open-Meteo.com (CC BY 4.0) for the rest of the project.
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
STATIONS = ("ORNI", "ORBI")
DUST_CODES = ("DU", "SA", "DS", "SS", "PO")
MILE_KM, VIS_CAP = 1.609, 10.0
STRONG_VIS_KM = 2       # dust AND visibility <= this = strong dust (storm-like)


def fetch_year(y0: date, y1: date, retries: int = 6) -> str:
    p = [("station", s) for s in STATIONS] + [("data", "vsby"), ("data", "wxcodes"),
         ("year1", y0.year), ("month1", y0.month), ("day1", y0.day),
         ("year2", y1.year), ("month2", y1.month), ("day2", y1.day),
         ("tz", "Etc/UTC"), ("format", "onlycomma"), ("missing", "M"), ("direct", "no"),
         ("report_type", 3), ("report_type", 4)]
    last = ""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(URL, params=p, timeout=120)
            if r.status_code == 200 and r.text.startswith("station"):
                return r.text
            last = f"HTTP {r.status_code}: {r.text[:100]!r}"
        except requests.RequestException as e:
            last = str(e)
        wait = 5 * attempt
        print(f"   retry {attempt}/{retries - 1} in {wait}s ({last})")
        time.sleep(wait)
    raise RuntimeError(f"gave up: {last}")


def is_dust(code, vis_km):
    toks = str(code).split() if isinstance(code, str) else []
    return any(c in t for t in toks for c in DUST_CODES) or ("HZ" in toks and vis_km < 5)


def to_hourly(reports, start, end):
    """reports: DataFrame (station, valid UTC, vsby miles, wxcodes) -> hourly local-time frame
    (time, any_dust, min_vis_km, available, strong_dust) for start 00:00 .. end 23:00."""
    raw = reports.copy()
    raw["time"] = (pd.to_datetime(raw["valid"]) + pd.Timedelta(hours=3)).dt.floor("h")
    raw["vis_km"] = (raw["vsby"] * MILE_KM).clip(upper=VIS_CAP)
    raw["dust"] = [float(is_dust(c, v)) for c, v in zip(raw["wxcodes"], raw["vis_km"])]
    hours = pd.date_range(f"{start} 00:00", f"{end} 23:00", freq="h")
    dust, vis = {}, {}
    for s in STATIONS:
        g = raw[raw["station"] == s].groupby("time")
        dust[s] = g["dust"].max().reindex(hours).ffill(limit=2)
        vis[s] = g["vis_km"].min().reindex(hours).ffill(limit=2)
    dust, vis = pd.DataFrame(dust), pd.DataFrame(vis)
    m = pd.DataFrame({"time": hours, "any_dust": dust.max(axis=1).fillna(0).astype(int),
                      "min_vis_km": vis.min(axis=1).fillna(VIS_CAP).round(2),
                      "available": dust.notna().sum(axis=1)})
    m["strong_dust"] = ((m["any_dust"] == 1) & (m["min_vis_km"] <= STRONG_VIS_KM)).astype(int)
    assert len(m) == len(hours) and (m["time"].diff().dropna() == pd.Timedelta(hours=1)).all(), "gaps in hourly time"
    assert m["time"].is_unique and m["available"].between(0, 2).all()
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw_metar")
    ap.add_argument("--extra", default="data/raw_hilla_extra")
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--end", default=None, help="last day (default: today)")
    args = ap.parse_args(argv)
    outdir, chunks = Path(args.out), Path(args.out) / "_chunks"
    chunks.mkdir(parents=True, exist_ok=True)
    Path(args.extra).mkdir(parents=True, exist_ok=True)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end) if args.end else date.today()

    parts = []
    for y in range(start.year, end.year + 1):
        f = chunks / f"metar_{y}.csv"
        if not f.exists() or y == date.today().year:
            txt = fetch_year(max(start, date(y, 1, 1)), min(end, date(y, 12, 31)) + timedelta(days=1))  # end day is exclusive
            f.write_text(txt, encoding="utf-8")
            time.sleep(1.5)
        parts.append(pd.read_csv(f, na_values=["M"], keep_default_na=False, dtype={"wxcodes": str}))
        print(f"{y}: {len(parts[-1]):,} reports")
    raw = pd.concat(parts, ignore_index=True)
    raw["wxcodes"] = raw["wxcodes"].replace("", pd.NA)
    raw["vsby"] = pd.to_numeric(raw["vsby"], errors="coerce")
    raw.to_csv(outdir / "metar_raw.csv", index=False)

    m = to_hourly(raw, start, end)
    m.to_csv(Path(args.extra) / "metar.csv", index=False)

    print(f"\nraw reports: {len(raw):,}  ({raw['valid'].min()} .. {raw['valid'].max()} UTC)")
    for s in STATIONS:
        print(f"  {s}: {int((raw['station'] == s).sum()):,} reports")
    print(f"hourly rows: {len(m):,}  any_dust hours: {int(m['any_dust'].sum()):,}  "
          f"strong_dust hours: {int(m['strong_dust'].sum()):,}  "
          f"hours with 0 stations: {int((m['available'] == 0).sum()):,}")
    print("saved", outdir / "metar_raw.csv", "and", Path(args.extra) / "metar.csv")
    print("Data: Iowa Environmental Mesonet METAR archive.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
