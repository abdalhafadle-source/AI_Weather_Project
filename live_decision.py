#!/usr/bin/env python3
"""
live_decision.py
Run ONCE PER HOUR (later by the server): fetch LIVE data, run the two models + decision.step(),
and write a JSON command for the ESP32 that drives the cleaning pump (Hilla, lat 32.48, lon 44.42).

Usage (terminal, inside the folder that contains this file):
    python live_decision.py                       # decide for the current hour (Asia/Baghdad)
    python live_decision.py --at "2026-10-29 07:00"   # test: evaluate a past hour, temporary fresh state,
                                                      # does NOT touch state/ ; files go to output/test/

Inputs: Open-Meteo forecast (best_match, best_match extra, gfs, ukmo, jma) + air quality, last 2 days and next
2 days; airport reports (METAR ORNI, ORBI) of the last 48 h from aviationweather.gov. Features are built exactly
like train_models.py --extended; models: models/extended/{rain,dust}_model.joblib.
Hours missed since the last run (at most 48 h) are replayed with can_clean=False, so only the current hour
can issue a clean. If METAR is down, the run continues with "no dust, visibility 10 km, 0 stations".

Outputs:
    state/decision_state.json   the decision state (the server must keep this file between runs)
    output/command.json         the command for the ESP32 (rewritten, not recomputed, if run twice in one hour)
    output/decision_log.csv     one line per run
ESP32 contract: execute only when action == "clean", command_id was not executed before, and now < valid_until;
never run the pump longer than max_duration_min (the ESP32 enforces its own 30-min cap anyway).

Data: Open-Meteo.com (CC BY 4.0); METAR: aviationweather.gov.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import requests

from decision import HOUR, new_state, step
from download_data import AIR_URL, AIR_VARS, FORECAST_VARS, fetch
from download_extra import CENTRE_VARS, FCX_VARS
from download_metar import to_hourly
from train_models import build, build_ext

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
METAR_URL = "https://aviationweather.gov/api/data/metar"
LAT, LON = 32.48, 44.42
MAX_BACK_H = 48
MAX_DURATION_MIN = 30
SOURCE = "Open-Meteo.com (CC BY 4.0); METAR: aviationweather.gov"
LOG_COLS = ["command_id", "action", "reason", "p_rain", "p_dust", "pm10", "metar_strong", "metar_haze", "metar_min_vis_km"]


def get_frame(url, hourly, prefix, model=None):
    p = {"latitude": LAT, "longitude": LON, "hourly": ",".join(hourly), "past_days": 2, "forecast_days": 2,
         "timezone": "Asia/Baghdad", "wind_speed_unit": "kmh", "precipitation_unit": "mm"}
    if model:
        p["models"] = model
    js = fetch(url, p, print)
    df = pd.DataFrame(js["hourly"])
    df["time"] = pd.to_datetime(df["time"])
    df = df.rename(columns={c: c.removesuffix("_" + model) if model else c for c in df.columns})
    return df.rename(columns={c: prefix + c for c in df.columns if c != "time"})


def get_metar(start, end):
    # returns (hourly frame, ok); on any problem: no dust, visibility 10, available 0
    try:
        r = requests.get(METAR_URL, params={"ids": "ORNI,ORBI", "hours": 48, "format": "json"}, timeout=60)
        r.raise_for_status()
        js = r.json()
        assert isinstance(js, list) and js, "no reports"
        rep = pd.DataFrame({"station": [x["icaoId"] for x in js],
                            "valid": pd.to_datetime([x["reportTime"] for x in js], utc=True).tz_localize(None),
                            "vsby": pd.to_numeric([str(x.get("visib")).rstrip("+") for x in js], errors="coerce"),
                            "wxcodes": [x.get("wxString") or pd.NA for x in js]})
        return to_hourly(rep, start, end), True
    except Exception as e:
        print(f"METAR failed ({type(e).__name__}: {e}) -> continuing without airport data")
        return to_hourly(pd.DataFrame({"station": [], "valid": pd.to_datetime([]), "vsby": [], "wxcodes": []}), start, end), False


def num(x, nd=3):
    return None if pd.isna(x) else round(float(x), nd)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--at", default=None, help='evaluate this past hour instead, e.g. "2026-10-29 07:00" (test)')
    ap.add_argument("--state", default="state/decision_state.json")
    ap.add_argument("--out", default="output")
    args = ap.parse_args()

    now = (pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=3)).tz_localize(None)     # Asia/Baghdad = UTC+3
    t = pd.Timestamp(args.at).floor("h") if args.at else now.floor("h")
    iso = lambda x: x.isoformat() + "+03:00"
    out = Path(args.out) / "test" if args.at else Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    spath = Path(args.state)

    # state (a test run never reads or writes it)
    state, last = new_state(), t - 24 * HOUR
    if not args.at and spath.exists():
        js = json.loads(spath.read_text(encoding="utf-8"))
        last = pd.Timestamp(js.pop("last_hour"))
        state = {k: (set(v) if k == "pending" else [datetime.fromisoformat(c) for c in v] if k == "cleans"
                     else datetime.fromisoformat(v) if v and k in ("event_end", "last_end", "pending_since") else v)
                 for k, v in js.items()}
        if last == t:                                    # already decided this hour: repeat the same command
            cmd = json.loads((out / "command.json").read_text(encoding="utf-8"))
            assert cmd["command_id"] == iso(t), "state is at this hour but command.json is for another hour"
            print("already decided for this hour - same command:")
            print(json.dumps(cmd, indent=2, ensure_ascii=False))
            return 0

    # data
    df = get_frame(FORECAST_URL, FORECAST_VARS, "fc_", "best_match")
    for prefix, model, hourly in (("fcx_", "best_match", FCX_VARS), ("gfs_", "gfs_seamless", CENTRE_VARS),
                                  ("ukmo_", "ukmo_seamless", CENTRE_VARS), ("jma_", "jma_seamless", CENTRE_VARS)):
        df = df.merge(get_frame(FORECAST_URL, hourly, prefix, model), on="time", how="left")
    df = df.merge(get_frame(AIR_URL, AIR_VARS, "aq_"), on="time", how="left")
    met, metar_ok = get_metar(df["time"].min().date(), df["time"].max().date())
    df = df.merge(met.rename(columns={c: "metar_" + c for c in met.columns if c != "time"}), on="time", how="left")
    df = df.sort_values("time").reset_index(drop=True)
    assert df["time"].is_unique and (df["time"].diff().dropna() == HOUR).all(), "gaps in hourly time"
    assert t in set(df["time"]), f"hour {t} is outside the downloaded data {df['time'].min()} .. {df['time'].max()}"

    # features + models
    X = build(df)
    X = X.join(build_ext(df, X))
    mr, md = joblib.load("models/extended/rain_model.joblib"), joblib.load("models/extended/dust_model.joblib")
    for m in (mr, md):
        miss = [f for f in m["features"] if f not in X.columns]
        assert not miss, f"features missing in live data: {miss}"
    ok = X[mr["features"]].notna().all(axis=1) & X[md["features"]].notna().all(axis=1)
    p_rain, p_dust = pd.Series(np.nan, index=df.index), pd.Series(np.nan, index=df.index)
    p_rain[ok] = mr["model"].predict_proba(X.loc[ok, mr["features"]])[:, 1]
    p_dust[ok] = md["model"].predict_proba(X.loc[ok, md["features"]])[:, 1]
    th_r, th_d = mr["threshold"], md["threshold"]

    # airport inputs exactly as in simulate_decisions
    strong = df["metar_strong_dust"].fillna(0) == 1
    dust_ob = strong & strong.shift(1, fill_value=False)
    haze_ob = (df["metar_any_dust"].fillna(0) == 1) & ~dust_ob

    # replay missed hours (cannot clean), then the current hour
    first = max(last + HOUR, t - (MAX_BACK_H - 1) * HOUR)
    assert first <= t, "state is ahead of the requested hour"
    for i in df.index[(df["time"] >= first) & (df["time"] <= t)]:
        h = df["time"][i]
        rain, pm = df["fc_precipitation"][i], df["aq_pm10"][i]
        if pd.isna(rain) or pd.isna(pm):
            print(f"warning: missing rain/pm10 at {h} (treated as 0)")
        safe = bool(ok[i] and p_rain[i] < th_r and p_dust[i] < th_d)
        action, reason = step(state, h.to_pydatetime(), 0 if pd.isna(rain) else rain, 0 if pd.isna(pm) else pm, safe,
                              dust_obs=bool(dust_ob[i]), haze=bool(haze_ob[i]), can_clean=h == t)
    i = df.index[df["time"] == t][0]

    cmd = {"command_id": iso(t), "generated_at": iso(now.floor("s")), "valid_until": iso(t + HOUR),
           "action": action, "pump": action == "clean", "max_duration_min": MAX_DURATION_MIN, "reason": reason,
           "p_rain": num(p_rain[i]), "p_dust": num(p_dust[i]), "thresholds": {"rain": num(th_r), "dust": num(th_d)},
           "now": {"rain_mm": num(df["fc_precipitation"][i]), "pm10": num(df["aq_pm10"][i], 1),
                   "metar_strong_dust": bool(strong[i]), "metar_haze": bool(haze_ob[i]),
                   "metar_min_vis_km": num(df["metar_min_vis_km"][i], 2), "metar_ok": metar_ok},
           "pending": sorted(state["pending"]), "model_trained_until": mr["trained_until"], "source": SOURCE}
    (out / "command.json").write_text(json.dumps(cmd, indent=2, ensure_ascii=False), encoding="utf-8")
    log = out / "decision_log.csv"
    new = not log.exists()
    with open(log, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_COLS)
        n = cmd["now"]
        w.writerow([cmd["command_id"], action, reason, cmd["p_rain"], cmd["p_dust"], n["pm10"],
                    n["metar_strong_dust"], n["metar_haze"], n["metar_min_vis_km"]])

    if not args.at:
        spath.parent.mkdir(parents=True, exist_ok=True)
        js = {k: (sorted(v) if k == "pending" else [c.isoformat() for c in v] if k == "cleans"
                  else v.isoformat() if isinstance(v, datetime) else v) for k, v in state.items()}
        js["last_hour"] = t.isoformat()
        spath.write_text(json.dumps(js, indent=2), encoding="utf-8")

    print(json.dumps(cmd, indent=2, ensure_ascii=False))
    print(f"saved {out / 'command.json'}   (METAR ok: {metar_ok})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
