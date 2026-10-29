#!/usr/bin/env python3
"""
prepare_data.py
Merge the three raw files into one hourly table (one row per hour).

Usage:
    python prepare_data.py                  # reads data/raw_hilla, writes data/processed
    python prepare_data.py --dir data/raw_hilla --out data/processed --extra data/raw_hilla_extra

Column prefixes:
    fc_   what the forecast said        (forecast_archive.csv)
    obs_  what actually happened (ERA5) (era5_weather.csv)
    aq_   dust / PM10                   (air_quality.csv)
    fcx_, gfs_, ukmo_, jma_, metar_  extra tables (<extra>/<name>.csv, optional, left-joined;
                             columns that are 100% null are dropped)

Outputs: <out>/hilla_hourly.csv and <out>/prepare_report.txt
The raw folder is only read, never changed.

Data: Open-Meteo.com (CC BY 4.0) - cite it in the report.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FILES = (("forecast_archive", "fc_"), ("era5_weather", "obs_"), ("air_quality", "aq_"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/raw_hilla")
    ap.add_argument("--out", default="data/processed")
    ap.add_argument("--extra", default="data/raw_hilla_extra", help="optional extra forecasts (skipped if missing)")
    args = ap.parse_args(argv)
    d, outdir = Path(args.dir), Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    out = []

    def P(s=""):
        out.append(s)
        print(s)

    df, n_fc = None, 0
    for name, prefix in FILES:
        x = pd.read_csv(d / f"{name}.csv", parse_dates=["time"])
        if name == "forecast_archive":
            n_fc = len(x)
        x = x.rename(columns={c: prefix + c for c in x.columns if c != "time"})
        df = x if df is None else df.merge(x, on="time", how="inner")
    for name in ("fcx", "gfs", "ukmo", "jma", "metar"):
        f = Path(args.extra) / f"{name}.csv"
        if not f.exists():
            continue
        x = pd.read_csv(f, parse_dates=["time"]).dropna(axis=1, how="all")
        x = x.rename(columns={c: f"{name}_{c}" for c in x.columns if c != "time"})
        df = df.merge(x, on="time", how="left")
    df = df.sort_values("time").reset_index(drop=True)

    # self-check (aq_dust and aq_aerosol_optical_depth are allowed to have nulls)
    assert df["time"].is_unique, "duplicate times"
    assert (df["time"].diff().dropna() == pd.Timedelta(hours=1)).all(), "gaps in hourly time"
    assert len(df) == n_fc, f"rows {len(df)} != forecast_archive rows {n_fc}"
    fo = [c for c in df.columns if c.startswith(("fc_", "obs_"))]
    assert df[fo].notna().all().all(), "nulls in fc_/obs_ columns"

    df.to_csv(outdir / "hilla_hourly.csv", index=False)

    P("=== prepare_data report ===")
    P(f"rows: {len(df):,}   from {df['time'].min()}   to {df['time'].max()}")
    P("columns: " + ", ".join(df.columns))
    P(f"\n{'column':<30}{'nulls':>8}{'null%':>8}")
    for c in df.columns:
        nn = int(df[c].isna().sum())
        P(f"{c:<30}{nn:>8}{100 * nn / len(df):>8.2f}")
    P("\nchecks passed. Data: Open-Meteo.com (CC BY 4.0)")

    (outdir / "prepare_report.txt").write_text("\n".join(out), encoding="utf-8")
    print(f"\nreport saved to {outdir / 'prepare_report.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
