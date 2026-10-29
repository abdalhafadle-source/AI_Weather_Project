#!/usr/bin/env python3
"""
check_data.py
Quality checks for the files produced by download_data.py.

Usage:
    python check_data.py                # reads data/raw
    python check_data.py --dir data/raw

Prints a report and saves it to <dir>/quality_report.txt
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

RANGES = {
    "temperature_2m": (-30, 60), "relative_humidity_2m": (0, 100), "dew_point_2m": (-40, 40),
    "precipitation": (0, 100), "rain": (0, 100),
    "pressure_msl": (950, 1060), "surface_pressure": (700, 1100), "cloud_cover": (0, 100),
    "wind_speed_10m": (0, 150), "wind_gusts_10m": (0, 250), "wind_direction_10m": (0, 360),
    "pm10": (0, 10000), "pm2_5": (0, 5000), "dust": (0, 10000), "aerosol_optical_depth": (0, 10),
}


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["time"])
    return df.sort_values("time").reset_index(drop=True)


def regular(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop_duplicates("time").set_index("time").asfreq("h")


def basic_checks(name, df, P, warn):
    P(f"\n=== {name} ===")
    P(f"rows: {len(df):,}   from {df['time'].min()}   to {df['time'].max()}")
    dup = int(df["time"].duplicated().sum())
    expected = pd.date_range(df["time"].min(), df["time"].max(), freq="h")
    missing = expected.difference(pd.DatetimeIndex(df["time"].drop_duplicates()))
    pct = 100 * len(missing) / len(expected)
    P(f"expected hourly rows: {len(expected):,}   missing hours: {len(missing):,} ({pct:.2f}%)   duplicate timestamps: {dup}")
    if dup:
        warn(f"{name}: {dup} duplicate timestamps")
    if pct > 0.5:
        warn(f"{name}: {pct:.2f}% of hours are missing")
    if len(missing):
        s = pd.Series(missing)
        grp = (s.diff() != pd.Timedelta(hours=1)).cumsum()
        runs = s.groupby(grp).agg(["first", "last", "count"]).sort_values("count", ascending=False)
        P("largest gaps (hours):")
        for _, r in runs.head(5).iterrows():
            P(f"   {r['first']} -> {r['last']}  ({int(r['count'])} h)")
        if int(runs["count"].iloc[0]) > 48:
            warn(f"{name}: a gap longer than 48 hours exists")

    cols = [c for c in df.columns if c != "time"]
    P(f"\n{'column':<24}{'nulls':>8}{'null%':>8}   first valid           last valid")
    for c in cols:
        nn = int(df[c].isna().sum())
        v = df.loc[df[c].notna(), "time"]
        P(f"{c:<24}{nn:>8}{100 * nn / len(df):>8.2f}   "
          f"{str(v.min()) if len(v) else '-':<20}  {str(v.max()) if len(v) else '-'}")
        if nn / len(df) > 0.02:
            warn(f"{name}.{c}: {100 * nn / len(df):.1f}% null (first valid: {v.min() if len(v) else 'never'})")

    P("\nplausibility ranges:")
    bad_any = False
    for c in cols:
        if c in RANGES:
            lo, hi = RANGES[c]
            s = df[c].dropna()
            nbad = int(((s < lo) | (s > hi)).sum())
            if nbad:
                bad_any = True
                P(f"   {c}: {nbad} values outside [{lo}, {hi}]  (min {s.min():.2f}, max {s.max():.2f})")
                warn(f"{name}.{c}: {nbad} implausible values")
    if not bad_any:
        P("   all values inside plausible ranges")

    reg = regular(df)
    for c, thr in (("pressure_msl", 5.0), ("temperature_2m", 12.0)):
        if c in reg:
            nj = int((reg[c].diff().abs() > thr).sum())
            P(f"   hourly jumps of {c} > {thr}: {nj}")
            if nj > 5:
                warn(f"{name}.{c}: {nj} suspicious hourly jumps")


def seasonality(era5, P):
    P("\n=== ERA5 seasonality (does it look like your climate?) ===")
    reg = regular(era5)
    rows = []
    if "precipitation" in reg:
        m = reg["precipitation"].resample("MS").agg(["sum", "count"])
        m["expected"] = m.index.days_in_month * 24
        m = m[m["count"] >= 0.9 * m["expected"]]
        rain = m.groupby(m.index.month)["sum"].mean()
    else:
        rain = pd.Series(dtype=float)
    gust = reg["wind_gusts_10m"].resample("D").max().groupby(lambda t: t.month).mean() if "wind_gusts_10m" in reg else pd.Series(dtype=float)
    temp = reg["temperature_2m"].groupby(reg.index.month).mean() if "temperature_2m" in reg else pd.Series(dtype=float)
    P(f"{'month':>5} {'rain mm/month':>14} {'mean daily max gust km/h':>26} {'mean temp C':>12}")
    for mo in range(1, 13):
        P(f"{mo:>5} {rain.get(mo, float('nan')):>14.1f} {gust.get(mo, float('nan')):>26.1f} {temp.get(mo, float('nan')):>12.1f}")
    if len(rain):
        P(f"yearly rain (average over complete months): ~{rain.sum():.0f} mm")


def dust_report(air, era5, P):
    P("\n=== Dust / PM10 ===")
    if "pm10" not in air or air["pm10"].notna().sum() == 0:
        P("no PM10 values")
        return
    reg = regular(air)
    s = reg["pm10"].dropna()
    q = s.quantile([0.5, 0.9, 0.95, 0.99])
    P(f"PM10 ug/m3: median {q[0.5]:.0f}   p90 {q[0.9]:.0f}   p95 {q[0.95]:.0f}   p99 {q[0.99]:.0f}   max {s.max():.0f}")
    daily = reg["pm10"].resample("D").max()
    P(f"\n{'month':>5} {'mean PM10':>10} {'p95':>8} {'days max>150':>14} {'days max>300':>14} {'days of data':>13}")
    for mo in range(1, 13):
        sm = reg["pm10"][reg.index.month == mo].dropna()
        dm = daily[daily.index.month == mo].dropna()
        if len(sm):
            P(f"{mo:>5} {sm.mean():>10.0f} {sm.quantile(0.95):>8.0f} {int((dm > 150).sum()):>14} {int((dm > 300).sum()):>14} {len(dm):>13}")

    d = daily.dropna().sort_values(ascending=False)
    picked = []
    for t, v in d.items():
        if all(abs((t - p).days) > 2 for p, _ in picked):
            picked.append((t, v))
        if len(picked) == 10:
            break
    ereg = regular(era5) if era5 is not None else None
    P("\nTop dust days (check them against storms you remember):")
    P(f"{'date':<12}{'max PM10':>10}{'max gust km/h':>15}{'min pressure':>14}{'rain mm':>9}")
    for t, v in picked:
        g = pr = rn = float("nan")
        if ereg is not None:
            day = ereg.loc[t:t + pd.Timedelta(hours=23)]
            if len(day):
                g = day["wind_gusts_10m"].max() if "wind_gusts_10m" in day else g
                pr = day["pressure_msl"].min() if "pressure_msl" in day else pr
                rn = day["precipitation"].sum() if "precipitation" in day else rn
        P(f"{str(t.date()):<12}{v:>10.0f}{g:>15.0f}{pr:>14.1f}{rn:>9.1f}")


def cross_check(era5, fc, P):
    P("\n=== ERA5 vs archived forecasts (how good are the inputs we will really get?) ===")
    m = era5.merge(fc, on="time", suffixes=("_era5", "_fc"))
    if m.empty:
        P("no overlapping period")
        return
    P(f"overlap: {m['time'].min()} -> {m['time'].max()}  ({len(m):,} hours)")
    mi = m.set_index("time")
    for v, agg in (("wind_speed_10m", "mean"), ("wind_gusts_10m", "max"), ("pressure_msl", "mean"),
                   ("temperature_2m", "mean"), ("precipitation", "sum")):
        a, b = f"{v}_era5", f"{v}_fc"
        if a in mi and b in mi:
            h = mi[[a, b]].dropna().corr().iloc[0, 1]
            dly = mi[[a, b]].resample("D").agg(agg).dropna().corr().iloc[0, 1]
            P(f"   {v:<18} correlation hourly {h:5.2f}   daily({agg}) {dly:5.2f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/raw")
    args = ap.parse_args()
    d = Path(args.dir)
    out, warns = [], []

    def P(s=""):
        out.append(s)
        print(s)

    def warn(s):
        warns.append(s)

    files = {n: d / f"{n}.csv" for n in ("era5_weather", "air_quality", "forecast_archive")}
    data = {n: load(p) for n, p in files.items() if p.exists()}
    if not data:
        print(f"No CSV files found in {d}. Run download_data.py first.")
        return 1

    meta_p = d / "meta.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        P("=== grid cell used by each dataset ===")
        for n, m in meta.items():
            if m.get("grid_lat") is not None:
                dist = haversine_km(m["requested_lat"], m["requested_lon"], m["grid_lat"], m["grid_lon"])
                P(f"{n:<18} requested ({m['requested_lat']}, {m['requested_lon']})  grid ({m['grid_lat']}, {m['grid_lon']})  "
                  f"distance {dist:.1f} km  elevation {m.get('elevation')} m")
            nf = len(m.get("failed_chunks", []))
            if nf:
                P(f"   {nf} chunk(s) failed in {n}:")
                for fc in m["failed_chunks"][:5]:
                    P(f"      {fc['start']} -> {fc['end']}: {fc['reason'][:120]}")
                warn(f"{n}: {nf} chunks failed to download")

    for n, df in data.items():
        basic_checks(n, df, P, warn)

    if "era5_weather" in data:
        seasonality(data["era5_weather"], P)
    if "air_quality" in data:
        dust_report(data["air_quality"], data.get("era5_weather"), P)
    if "era5_weather" in data and "forecast_archive" in data:
        cross_check(data["era5_weather"], data["forecast_archive"], P)

    P("\n=== SUMMARY ===")
    if warns:
        P(f"{len(warns)} warning(s):")
        for w in warns:
            P(f"   - {w}")
    else:
        P("no warnings")
    P("Manual checks left for you: do the rainy months match reality? do the top dust days match storms you remember?")

    (d / "quality_report.txt").write_text("\n".join(out), encoding="utf-8")
    print(f"\nreport saved to {d / 'quality_report.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
