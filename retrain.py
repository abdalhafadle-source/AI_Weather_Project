#!/usr/bin/env python3
"""
retrain.py
Weekly self-learning with a safety guard (Hilla, lat 32.48, lon 44.42).

Usage (terminal, inside the folder that contains this file):
    python retrain.py               # update data, train candidates, promote the ones that are not worse
    python retrain.py --dry-run     # same, but models/extended/*.joblib are NOT overwritten
    python retrain.py --skip-download   # reuse the data already on disk (tests)

Steps: 1) update data up to today-7 days (download_data, download_extra, download_metar), then
prepare_data + define_events.  2) HOLDOUT = last 90 days of data.  3) Candidate = RandomForest (same params
as train_models) with the SAME features as the current model; fit on the data before the holdout, threshold =
F1-best on the 365 days before the holdout (fit on the earlier part, choose threshold, then refit on all
pre-holdout rows).  4) Compare candidate vs current model on the holdout with average precision (AP);
promote per target only if candidate AP >= current AP.  A line per target goes to reports/retrain_log.csv.
The raw data folders are only appended to by the download scripts (data/raw, Baghdad, is never touched).

Data: Open-Meteo.com (CC BY 4.0); METAR: Iowa Environmental Mesonet.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

import define_events
import download_data
import download_extra
import download_metar
import prepare_data
from train_models import H, MODELS, TARGETS, best_threshold, build, build_ext, targets

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOLDOUT_DAYS, VAL_DAYS = 90, 365
LOG_COLS = ["date", "target", "current_ap", "candidate_ap", "promoted", "rows_train", "holdout_start",
            "current_unseen_holdout"]


def update_data():
    end = str(date.today() - timedelta(days=7))
    steps = (("download_data", lambda: download_data.main(["--lat", "32.48", "--lon", "44.42", "--out", "data/raw_hilla"])),
             ("download_extra", lambda: download_extra.main(["--end", end])),
             ("download_metar", lambda: download_metar.main([])),
             ("prepare_data", lambda: prepare_data.main([])),
             ("define_events", lambda: define_events.main([])))
    for name, run in steps:
        print(f"\n=== {name} ===")
        if run():
            sys.exit(f"{name} failed - stop (models untouched)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="do everything but do not overwrite the models")
    ap.add_argument("--skip-download", action="store_true", help="reuse the data already on disk")
    args = ap.parse_args()
    if not args.skip_download:
        update_data()

    raw = pd.read_csv("data/processed/hilla_hourly_labeled.csv", parse_dates=["time"])
    X = build(raw)
    X = X.join(build_ext(raw, X))
    Y = targets(raw, "metar_strong_dust" in raw.columns)
    rows, today = [], str(date.today())
    for tg in TARGETS:
        path = Path(f"models/extended/{tg}_model.joblib")
        cur = joblib.load(path)
        feats = cur["features"]
        miss = [f for f in feats if f not in X.columns]
        assert not miss, f"features missing: {miss}"
        keep = (X[feats].notna().all(axis=1) & Y[tg].notna()).to_numpy()
        x, y, t = X.loc[keep, feats], Y.loc[keep, tg].astype(int), raw.loc[keep, "time"]

        # split (the last 6 rows before each boundary are dropped from the earlier set: targets look 6 h ahead)
        hold_start = t.max() - pd.Timedelta(days=HOLDOUT_DAYS)
        val_start = hold_start - pd.Timedelta(days=VAL_DAYS)
        hold = np.flatnonzero(t >= hold_start)
        pre = np.flatnonzero(t < hold_start)[:-H]
        fit = np.flatnonzero(t < val_start)[:-H]
        val = np.flatnonzero((t >= val_start) & (t < hold_start))[:-H]
        assert t.iloc[fit].max() < t.iloc[val].min() and t.iloc[pre].max() < t.iloc[hold].min()

        m = MODELS["RandomForest"]().fit(x.iloc[fit], y.iloc[fit])
        pv = m.predict_proba(x.iloc[val])[:, 1]
        val_ap, th = average_precision_score(y.iloc[val], pv), best_threshold(y.iloc[val], pv)
        m = MODELS["RandomForest"]().fit(x.iloc[pre], y.iloc[pre])
        cand_ap = average_precision_score(y.iloc[hold], m.predict_proba(x.iloc[hold])[:, 1])
        cur_ap = average_precision_score(y.iloc[hold], cur["model"].predict_proba(x.iloc[hold])[:, 1])

        unseen = pd.Timestamp(cur["trained_until"]) < hold_start
        if not unseen:
            print(f"NOTE {tg}: current model was trained until {cur['trained_until']}, which is inside the holdout "
                  f"(starts {hold_start}) - it has seen part of it, so the comparison favours it")
        promote = cand_ap >= cur_ap
        print(f"{tg}: holdout {hold_start:%Y-%m-%d} .. {t.max():%Y-%m-%d} ({len(hold):,} h)   train rows {len(pre):,}   "
              f"val AP {val_ap:.3f}   threshold {th:.3f}   current AP {cur_ap:.3f}   candidate AP {cand_ap:.3f}   "
              f"-> {'PROMOTE' if promote else 'keep current'}{' (dry run, not saved)' if promote and args.dry_run else ''}")
        if promote and not args.dry_run:
            joblib.dump({"model": m, "features": feats, "threshold": th, "algorithm": "RandomForest", "val_ap": val_ap,
                         "trained_until": str(t.iloc[pre].max()), "promoted_at": str(pd.Timestamp.now())},
                        path, compress=3)
        rows.append([today, tg, round(cur_ap, 4), round(cand_ap, 4), "dry-run:" + str(promote) if args.dry_run else promote,
                     len(pre), f"{hold_start:%Y-%m-%d}", unseen])

    log = Path("reports/retrain_log.csv")
    new = not log.exists()
    with open(log, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_COLS)
        w.writerows(rows)
    print(f"\nlog appended to {log}.  Data: Open-Meteo.com (CC BY 4.0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
