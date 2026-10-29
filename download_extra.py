#!/usr/bin/env python3
"""
download_extra.py
Download EXTRA archived forecasts for Hilla: more variables from best_match (fcx) and
second opinions from other weather centres (gfs, ukmo, jma).

Usage (terminal, inside the folder that contains this file):
    python download_extra.py
    python download_extra.py --lat 32.48 --lon 44.42 --out data/raw_hilla_extra

Outputs (default folder: data/raw_hilla_extra):
    fcx.csv   best_match: weather_code, cape, showers, visibility, dew_point_2m, ...
    gfs.csv   NOAA GFS      precipitation, cloud_cover, wind_gusts_10m, ...
    ukmo.csv  UK Met Office (starts 2022-04)
    jma.csv   Japan Met Agency
    download_log.txt        everything that happened
Column names are plain (the model-name suffix Open-Meteo may add is removed).
Finished chunks are cached in <out>/_chunks, so the script is resumable.

Data: Open-Meteo.com (CC BY 4.0) - cite it in the report.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from download_data import FORECAST_ARCHIVE_URL, Logger, download_dataset, summarize

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FCX_VARS = ["weather_code", "cape", "showers", "visibility", "dew_point_2m",
            "soil_moisture_0_to_1cm", "lifted_index", "wind_speed_80m"]
CENTRE_VARS = ["precipitation", "cloud_cover", "wind_gusts_10m", "wind_speed_10m", "pressure_msl"]
DATASETS = (("fcx", "best_match", FCX_VARS), ("gfs", "gfs_seamless", CENTRE_VARS),
            ("ukmo", "ukmo_seamless", CENTRE_VARS), ("jma", "jma_seamless", CENTRE_VARS))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, default=32.48)
    ap.add_argument("--lon", type=float, default=44.42)
    ap.add_argument("--out", default="data/raw_hilla_extra")
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--end", default="2026-10-21", help="same end as data/raw_hilla")
    ap.add_argument("--timezone", default="Asia/Baghdad")
    args = ap.parse_args(argv)

    outdir = Path(args.out)
    log = Logger(outdir / "download_log.txt")
    log(f"=== extra download started, lat={args.lat} lon={args.lon}, tz={args.timezone} ===")
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    cache_before = date.today() - timedelta(days=15)
    common = {"latitude": args.lat, "longitude": args.lon, "timezone": args.timezone,
              "wind_speed_unit": "kmh", "precipitation_unit": "mm"}

    nfail, empty = 0, []
    for name, model, hourly in DATASETS:
        p = dict(common, models=model, hourly=",".join(hourly))
        df, _, failed = download_dataset(name, FORECAST_ARCHIVE_URL, p, start, end, 180, outdir, log, cache_before)
        nfail += len(failed)
        if df is None:
            continue
        # single model: columns may be called e.g. precipitation_gfs_seamless -> strip the suffix
        df = df.rename(columns={c: c.removesuffix("_" + model) for c in df.columns})
        assert df["time"].is_unique and len(df.columns) == len(set(df.columns)), f"{name}: bad columns"
        df.to_csv(outdir / f"{name}.csv", index=False)
        summarize(name, df, log)
        empty += [f"{name}.{c}" for c in df.columns if c != "time" and df[c].isna().all()]

    log(f"=== done. failed chunks: {nfail}. all-null columns: {empty or 'none'} ===")
    log("Data: Open-Meteo.com (CC BY 4.0) - cite in the report.")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
