#!/usr/bin/env python3
"""
download_data.py
Download weather + dust data from Open-Meteo for the AI solar-panel-cleaning project.

Usage (terminal, inside the folder that contains this file):
    python download_data.py --lat 33.3152 --lon 44.3661

Outputs (default folder: data/raw):
    era5_weather.csv      hourly ERA5 reanalysis (rain, wind, pressure, ...)    ~10 years
    air_quality.csv       hourly CAMS air quality (PM10, dust, ...)             as far back as the server has it
    forecast_archive.csv  hourly archived FORECASTS (what the live system will
                          actually receive at run time)                         from 2022
    meta.json             grid cell each dataset really used
    download_log.txt      everything that happened, including failed chunks

The script is resumable: finished chunks are cached in data/raw/_chunks, so if it
stops (internet drop, rate limit) just run the same command again.

Data: Open-Meteo.com (CC BY 4.0) - cite it in the report.
"""
from __future__ import annotations

import argparse
import json
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

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
FORECAST_ARCHIVE_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"

ERA5_VARS = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m",
    "precipitation", "rain",
    "pressure_msl", "surface_pressure", "cloud_cover",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
]
AIR_VARS = ["pm10", "pm2_5", "dust", "aerosol_optical_depth"]
FORECAST_VARS = [
    "temperature_2m", "relative_humidity_2m", "precipitation",
    "pressure_msl", "cloud_cover",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
]


class ApiError(Exception):
    pass


class Logger:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')}  {msg}"
        print(line, flush=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def fetch(url: str, params: dict, log: Logger, retries: int = 6) -> dict:
    """GET with retries. HTTP 400 is not retried (bad request / date out of range)."""
    wait = 5
    last = ""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, timeout=90)
        except requests.RequestException as e:
            last = f"network error: {type(e).__name__}: {e}"
        else:
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    last = "response was not valid JSON"
            elif r.status_code == 400:
                raise ApiError(f"HTTP 400 (bad request): {r.text[:300]}")
            elif r.status_code == 429:
                last = "HTTP 429 (rate limit)"
                wait = max(wait, 65)
            else:
                last = f"HTTP {r.status_code}: {r.text[:150]}"
        if attempt < retries:
            log(f"   retry {attempt}/{retries - 1} in {wait}s ({last})")
            time.sleep(wait)
            wait = min(wait * 2, 300)
    raise ApiError(f"gave up after {retries} attempts ({last})")


def chunks(start: date, end: date, days: int):
    cur = start
    while cur <= end:
        e = min(cur + timedelta(days=days - 1), end)
        yield cur, e
        cur = e + timedelta(days=1)


def hourly_to_df(js: dict) -> pd.DataFrame:
    if "hourly" not in js:
        raise ApiError("response has no 'hourly' block")
    df = pd.DataFrame(js["hourly"])
    df["time"] = pd.to_datetime(df["time"])
    return df


def download_dataset(name, url, base_params, start, end, step_days, outdir, log, cache_before):
    cache_dir = outdir / "_chunks"
    cache_dir.mkdir(parents=True, exist_ok=True)
    frames, failed, meta = [], [], {}
    pieces = list(chunks(start, end, step_days))
    log(f"[{name}] {start} -> {end}  ({len(pieces)} requests)")
    for i, (s, e) in enumerate(pieces, 1):
        # location in the name so a run for another point never reuses these chunks
        cache = cache_dir / f"{name}_{base_params['latitude']}_{base_params['longitude']}_{s}_{e}.csv"
        if cache.exists():
            frames.append(pd.read_csv(cache, parse_dates=["time"]))
            log(f"   {i}/{len(pieces)} {s}..{e}  (cached)")
            continue
        params = dict(base_params, start_date=s.isoformat(), end_date=e.isoformat())
        try:
            js = fetch(url, params, log)
            df = hourly_to_df(js)
        except ApiError as ex:
            log(f"   {i}/{len(pieces)} {s}..{e}  FAILED: {ex}")
            failed.append({"start": str(s), "end": str(e), "reason": str(ex)})
            continue
        if not meta:
            meta = {
                "grid_lat": js.get("latitude"), "grid_lon": js.get("longitude"),
                "elevation": js.get("elevation"), "timezone": js.get("timezone"),
            }
        if e < cache_before:  # only cache chunks that are final
            df.to_csv(cache, index=False)
        frames.append(df)
        log(f"   {i}/{len(pieces)} {s}..{e}  ok ({len(df)} rows)")
        time.sleep(1.5)
    if not frames:
        log(f"[{name}] NO DATA downloaded")
        return None, meta, failed
    full = (pd.concat(frames, ignore_index=True)
              .drop_duplicates("time").sort_values("time").reset_index(drop=True))
    full.to_csv(outdir / f"{name}.csv", index=False)
    return full, meta, failed


def summarize(name, df, log):
    log(f"[{name}] rows={len(df):,}  from {df['time'].min()}  to {df['time'].max()}")
    for c in df.columns:
        if c == "time":
            continue
        nn = int(df[c].isna().sum())
        first = df.loc[df[c].notna(), "time"]
        log(f"   {c:<24} nulls={nn:>7} ({100 * nn / len(df):5.2f}%)  first valid: "
            f"{first.min() if len(first) else '-'}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, required=True, help="latitude of the panels, e.g. 33.3152")
    ap.add_argument("--lon", type=float, required=True, help="longitude of the panels, e.g. 44.3661")
    ap.add_argument("--years", type=int, default=10, help="calendar years of ERA5 weather (default 10)")
    ap.add_argument("--air-start", default=None,
                    help="first date to try for air quality (default: same start as the ERA5 weather; "
                         "whatever the server really has is kept, the rest is reported)")
    ap.add_argument("--air-domains", default=None, choices=["auto", "cams_europe", "cams_global"],
                    help="force a CAMS domain for air quality (default: let the server choose)")
    ap.add_argument("--fc-start", default="2022-01-01", help="first date to try for the forecast archive")
    ap.add_argument("--timezone", default="Asia/Baghdad")
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--skip-forecast-archive", action="store_true")
    args = ap.parse_args(argv)

    if not (-90 <= args.lat <= 90 and -180 <= args.lon <= 180):
        ap.error("lat must be in [-90, 90] and lon in [-180, 180]")

    outdir = Path(args.out)
    log = Logger(outdir / "download_log.txt")
    log(f"=== download started, location lat={args.lat} lon={args.lon}, tz={args.timezone} ===")

    end = date.today() - timedelta(days=7)           # ERA5 lags ~5 days
    era5_start = date(end.year - args.years, 1, 1)
    air_start = date.fromisoformat(args.air_start) if args.air_start else era5_start
    fc_start = date.fromisoformat(args.fc_start)
    cache_before = date.today() - timedelta(days=15)

    common = {"latitude": args.lat, "longitude": args.lon, "timezone": args.timezone}
    all_meta, all_failed = {}, {}

    # 1) ERA5 weather (long history)
    p = dict(common, hourly=",".join(ERA5_VARS), wind_speed_unit="kmh", precipitation_unit="mm")
    era5, m, f = download_dataset("era5_weather", ARCHIVE_URL, p, era5_start, end, 365, outdir, log, cache_before)
    all_meta["era5_weather"], all_failed["era5_weather"] = m, f
    if era5 is not None:
        summarize("era5_weather", era5, log)

    # 2) Air quality / dust (short history; early chunks may be refused - that is tolerated)
    p = dict(common, hourly=",".join(AIR_VARS))
    if args.air_domains:
        p["domains"] = args.air_domains
    air, m, f = download_dataset("air_quality", AIR_URL, p, air_start, end, 90, outdir, log, cache_before)
    all_meta["air_quality"], all_failed["air_quality"] = m, f
    if air is not None:
        summarize("air_quality", air, log)

    # 3) Archived forecasts = the inputs the live system will really see
    if not args.skip_forecast_archive:
        p = dict(common, hourly=",".join(FORECAST_VARS), wind_speed_unit="kmh", precipitation_unit="mm")
        fc, m, f = download_dataset("forecast_archive", FORECAST_ARCHIVE_URL, p, fc_start, end, 180,
                                    outdir, log, cache_before)
        all_meta["forecast_archive"], all_failed["forecast_archive"] = m, f
        if fc is not None:
            summarize("forecast_archive", fc, log)

    for k, m in all_meta.items():
        m["requested_lat"], m["requested_lon"] = args.lat, args.lon
        m["failed_chunks"] = all_failed.get(k, [])
    (outdir / "meta.json").write_text(json.dumps(all_meta, indent=2, ensure_ascii=False), encoding="utf-8")

    nfail = sum(len(v) for v in all_failed.values())
    log(f"=== done. failed chunks: {nfail} (details in meta.json / download_log.txt) ===")
    log("Data: Open-Meteo.com (CC BY 4.0) - cite in the report.")
    if era5 is None:
        log("ERROR: no ERA5 weather downloaded. Check your internet connection and run again.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
