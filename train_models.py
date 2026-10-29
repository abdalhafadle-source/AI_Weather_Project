#!/usr/bin/env python3
"""
train_models.py
Train two classifiers for Hilla (rain / dust in the next 6 hours) with three
algorithms (RandomForest, HistGradientBoosting, XGBoost) and compare them fairly.

Usage:
    python train_models.py                  # reads data/processed/hilla_hourly_labeled.csv
    python train_models.py --dir data/processed
    python train_models.py --extended       # adds extra forecast features, separate outputs

Features use only what is known live at hour t (forecast + current air quality).
Targets look at hours t+1..t+6:  y_rain = any obs_precipitation >= 0.1,  y_dust = any aq_pm10 >= 150
(--extended with METAR columns: or any metar_strong_dust == 1).
Split by time (train 2022-23, val 2024, test 2025+). Winner = best VAL average precision.
--extended adds features from the extra forecasts (fcx_, gfs_, ukmo_, jma_ columns made by
prepare_data.py); extended features with >5% NaN in the test period are dropped. Outputs get an
"_extended" suffix (models go to models/extended/) and the report compares base vs extended.

Outputs: models/rain_model.joblib, models/dust_model.joblib, reports/model_comparison.csv,
         <dir>/train_report.txt, reports/charts/pr_curves_*.png, feature_importance_*.png
         (--extended: reports/model_comparison_extended.csv, <dir>/train_report_extended.txt,
          *_extended.png, models/extended/*_model.joblib)
Only hilla_hourly_labeled.csv is read; the raw folders are never touched.

Data: Open-Meteo.com (CC BY 4.0) - cite it in the report.
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import (accuracy_score, average_precision_score, f1_score, precision_recall_curve,
                             precision_score, recall_score, roc_auc_score)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SEED = 42
H = 6                    # hours ahead
RAIN_MM = 0.1            # rainy hour
DUST_PM10 = 150          # dusty hour
TRAIN_END, VAL_END = "2024-01-01", "2025-01-01"   # first timestamp of val / test
TARGETS = ("rain", "dust")
FC = ["temperature_2m", "relative_humidity_2m", "precipitation", "pressure_msl", "cloud_cover",
      "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"]
MODELS = {
    "RandomForest": lambda: RandomForestClassifier(n_estimators=300, min_samples_leaf=10, n_jobs=-1,
                                                   random_state=SEED),
    "GradientBoosting": lambda: HistGradientBoostingClassifier(max_iter=400, learning_rate=0.05,
                                                               early_stopping=False, random_state=SEED),
    "XGBoost": lambda: __import__("xgboost").XGBClassifier(n_estimators=400, learning_rate=0.05, max_depth=6, subsample=0.8,
                                     colsample_bytree=0.8, tree_method="hist", n_jobs=-1,
                                     random_state=SEED, eval_metric="logloss"),
}
COLS = ["target", "method", "val_ap", "threshold", "accuracy", "precision", "recall", "f1", "roc_auc",
        "avg_precision", "fit_time_s", "predict_ms_per_1000", "model_size_bytes"]


def fwd(x, op):
    # aggregate over hours t+1..t+6 (window ending at t+6, moved back to row t)
    return getattr(x.rolling(H), op)().shift(-H)


def back(x, op):
    # aggregate over hours t-5..t
    return getattr(x.rolling(H), op)()


def build(df):
    f = pd.DataFrame(index=df.index)
    c = {k: df["fc_" + k] for k in FC}
    for k in FC:
        if k != "wind_direction_10m":
            f["now_" + k] = c[k]
    rad = np.deg2rad(c["wind_direction_10m"])
    f["now_wind_dir_sin"], f["now_wind_dir_cos"] = np.sin(rad), np.cos(rad)
    f["next_precip_sum"] = fwd(c["precipitation"], "sum")
    f["next_precip_max"] = fwd(c["precipitation"], "max")
    f["next_gust_max"] = fwd(c["wind_gusts_10m"], "max")
    f["next_wind_mean"] = fwd(c["wind_speed_10m"], "mean")
    f["next_rh_max"] = fwd(c["relative_humidity_2m"], "max")
    f["next_cloud_mean"] = fwd(c["cloud_cover"], "mean")
    f["next_pressure_min"] = fwd(c["pressure_msl"], "min")
    f["next_temp_mean"] = fwd(c["temperature_2m"], "mean")
    f["trend_pressure_fwd6"] = c["pressure_msl"].shift(-H) - c["pressure_msl"]
    f["trend_pressure_back3"] = c["pressure_msl"] - c["pressure_msl"].shift(3)
    f["trend_gust_max_minus_now"] = f["next_gust_max"] - c["wind_gusts_10m"]
    f["recent_precip_sum"] = back(c["precipitation"], "sum")
    f["pm10_now"] = df["aq_pm10"]
    f["recent_pm10_max"] = back(df["aq_pm10"], "max")
    f["pm10_change_3h"] = df["aq_pm10"] - df["aq_pm10"].shift(3)
    f["dust_now"] = df["aq_dust"]
    hr = df["time"].dt.hour
    doy = df["time"].dt.dayofyear
    f["hour_sin"], f["hour_cos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    f["doy_sin"], f["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    return f


def build_ext(df, f):
    # extra features, all from hour t and t+1..t+6 of FORECASTS (never obs_*)
    g = lambda c: df[c] if c in df.columns else None
    e = pd.DataFrame(index=df.index)
    if g("fcx_weather_code") is not None:
        e["fcx_weather_code_max6"] = fwd(df["fcx_weather_code"], "max")
        e["fcx_cape_max6"] = fwd(df["fcx_cape"], "max")
        e["fcx_showers_sum6"] = fwd(df["fcx_showers"], "sum")
        e["fcx_visibility_now"] = df["fcx_visibility"]
        e["fcx_visibility_min6"] = fwd(df["fcx_visibility"], "min")
        e["fcx_dewpoint_depression"] = df["fc_temperature_2m"] - df["fcx_dew_point_2m"]
        e["fcx_soil_moisture_now"] = df["fcx_soil_moisture_0_to_1cm"]
        e["fcx_lifted_index_min6"] = fwd(df["fcx_lifted_index"], "min")
        e["fcx_wind80_max6"] = fwd(df["fcx_wind_speed_80m"], "max")
    if g("metar_any_dust") is not None:
        # airport observations at <= t (allowed: they are already known at hour t)
        e["metar_dust_now"] = df["metar_any_dust"]
        e["metar_dust_back6"] = back(df["metar_any_dust"], "max")
        e["metar_vis_now"] = df["metar_min_vis_km"]
        e["metar_vis_min_back6"] = back(df["metar_min_vis_km"], "min")
        e["metar_available"] = df["metar_available"]
        e["metar_strong_now"] = df["metar_strong_dust"]
        e["metar_strong_back6"] = back(df["metar_strong_dust"], "max")
    psum, gmax = {"fc": f["next_precip_sum"]}, {"fc": f["next_gust_max"]}
    for m in ("gfs", "ukmo", "jma"):
        if g(m + "_precipitation") is None:
            continue
        psum[m] = e[m + "_precip_sum6"] = fwd(df[m + "_precipitation"], "sum")
        if g(m + "_wind_gusts_10m") is not None:
            gmax[m] = e[m + "_gust_max6"] = fwd(df[m + "_wind_gusts_10m"], "max")
        if g(m + "_cloud_cover") is not None:
            e[m + "_cloud_mean6"] = fwd(df[m + "_cloud_cover"], "mean")
    if len(psum) > 1:
        ps = pd.DataFrame(psum)
        e["n_sources_available"] = ps.notna().sum(axis=1)
        e["n_sources_rain"] = (ps.fillna(0) >= RAIN_MM).sum(axis=1)
        e["sources_precip_mean"], e["sources_precip_max"] = ps.mean(axis=1), ps.max(axis=1)
        gs = pd.DataFrame(gmax)
        e["sources_gust_spread"] = gs.max(axis=1) - gs.min(axis=1)
    return e


def metrics(y, pred, prob=None):
    m = {"accuracy": accuracy_score(y, pred), "precision": precision_score(y, pred, zero_division=0),
         "recall": recall_score(y, pred, zero_division=0), "f1": f1_score(y, pred, zero_division=0)}
    if prob is not None:
        m["roc_auc"], m["avg_precision"] = roc_auc_score(y, prob), average_precision_score(y, prob)
    return m


def best_threshold(y, prob):
    p, r, th = precision_recall_curve(y, prob)
    f1 = 2 * p[:-1] * r[:-1] / np.maximum(p[:-1] + r[:-1], 1e-12)
    return float(th[np.argmax(f1)])


def targets(raw, metar_t):
    # y_rain / y_dust for hours t+1..t+6 (NaN where the window runs past the end)
    mx_rain, mx_dust = fwd(raw["obs_precipitation"], "max"), fwd(raw["aq_pm10"], "max")
    dust_pos = mx_dust >= DUST_PM10
    if metar_t:   # extended + METAR: dust also means strong airport dust in t+1..t+6
        dust_pos = dust_pos | (fwd(raw["metar_strong_dust"], "max") >= 1)
    return pd.DataFrame({"rain": (mx_rain >= RAIN_MM).astype(float).where(mx_rain.notna()),
                         "dust": dust_pos.astype(float).where(mx_dust.notna())})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/processed")
    ap.add_argument("--extended", action="store_true", help="add extra forecast features")
    args = ap.parse_args()
    d = Path(args.dir)
    sfx = "_extended" if args.extended else ""
    chart_dir, model_dir = Path("reports/charts"), Path("models/extended" if args.extended else "models")
    chart_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    out = []

    def P(s=""):
        out.append(s)
        print(s)

    raw = pd.read_csv(d / "hilla_hourly_labeled.csv", parse_dates=["time"])
    X = build(raw)
    dropped, n_base = [], X.shape[1]
    if args.extended:
        E = build_ext(raw, X)
        test_rows = (raw["time"] >= VAL_END).to_numpy()
        pct = E[test_rows].isna().mean() * 100
        dropped = [(c, pct[c]) for c in E.columns if pct[c] > 5]
        X = pd.concat([X, E.drop(columns=[c for c, _ in dropped])], axis=1)
    feats = list(X.columns)
    assert not any(c.startswith(("obs_", "is_")) for c in feats), "forbidden column used as feature"

    # targets (NaN where the 6-hour window runs past the end)
    metar_t = args.extended and "metar_strong_dust" in raw.columns
    Y = targets(raw, metar_t)
    base_sum = X["next_precip_sum"]   # kept for the forecast baseline

    # self-check: manual slicing for a few random rows
    rng = np.random.default_rng(SEED)
    ok = X.dropna().index.intersection(Y.dropna().index)
    for i in rng.choice(ok, 5, replace=False):
        w = raw.iloc[i + 1:i + H + 1]
        assert np.isclose(X.loc[i, "next_precip_sum"], w["fc_precipitation"].sum()), f"fwd sum wrong at {i}"
        assert Y.loc[i, "rain"] == float((w["obs_precipitation"] >= RAIN_MM).any()), f"y_rain wrong at {i}"
        d_ok = (w["aq_pm10"] >= DUST_PM10).any() or (metar_t and (w["metar_strong_dust"] == 1).any())
        assert Y.loc[i, "dust"] == float(d_ok), f"y_dust wrong at {i}"

    keep = X.notna().all(axis=1) & Y.notna().all(axis=1)
    X, Y, t, base_sum = X[keep], Y[keep].astype(int), raw.loc[keep, "time"], base_sum[keep]
    pm_now = X["pm10_now"]

    # split by time; drop the last 6 rows before each boundary from the earlier set
    def part(lo, hi):
        pos = np.flatnonzero(((t >= lo) if lo else True) & (t < hi if hi else True))
        return pos[:-H] if hi else pos
    sp = {"train": part(None, TRAIN_END), "val": part(TRAIN_END, VAL_END), "test": part(VAL_END, None)}
    assert t.iloc[sp["train"]].max() < t.iloc[sp["val"]].min() - pd.Timedelta(hours=H - 1)
    assert t.iloc[sp["val"]].max() < t.iloc[sp["test"]].min() - pd.Timedelta(hours=H - 1)
    tv = np.concatenate([sp["train"], sp["val"]])
    Xte = X.iloc[sp["test"]]

    P("=== train_models report ===")
    if args.extended:
        P(f"extended features kept: {len(feats) - n_base}")
        P("dropped (>5% NaN in test): " + (", ".join(f"{c} ({v:.1f}%)" for c, v in dropped) or "none"))
    if metar_t:
        P("DUST TARGET CHANGED: y_dust = aq_pm10 >= 150 OR metar_strong_dust == 1 in t+1..t+6 (v1 used PM10 only)")
    P(f"features: {len(feats)}   models: {', '.join(MODELS)}   seed: {SEED}")
    P(f"\n{'split':<8}{'rows':>8}{'rain+ %':>10}{'dust+ %':>10}   period")
    for k, pos in sp.items():
        P(f"{k:<8}{len(pos):>8,}{100 * Y['rain'].iloc[pos].mean():>10.2f}{100 * Y['dust'].iloc[pos].mean():>10.2f}"
          f"   {t.iloc[pos].min():%Y-%m-%d} .. {t.iloc[pos].max():%Y-%m-%d}")

    rows, winners = [], {}
    for tg in TARGETS:
        y = Y[tg]
        ytr, yva, yte = y.iloc[sp["train"]], y.iloc[sp["val"]], y.iloc[sp["test"]]
        res, probs, fitted = [], {}, {}
        for name, make in MODELS.items():
            # 1. validation: fit on train, pick threshold on val
            m = make().fit(X.iloc[sp["train"]], ytr)
            pv = m.predict_proba(X.iloc[sp["val"]])[:, 1]
            val_ap, th = average_precision_score(yva, pv), best_threshold(yva, pv)
            # 2. final: refit on train+val, score on test
            t1 = time.time()
            m = make().fit(X.iloc[tv], y.iloc[tv])
            fit_s = time.time() - t1
            t1 = time.time()
            pt = m.predict_proba(Xte)[:, 1]
            pred_ms = (time.time() - t1) * 1000 / len(Xte) * 1000
            buf = io.BytesIO()
            joblib.dump(m, buf)
            r = {"target": tg, "method": name, "val_ap": val_ap, "threshold": th,
                 **metrics(yte, (pt >= th).astype(int), pt),
                 "fit_time_s": fit_s, "predict_ms_per_1000": pred_ms, "model_size_bytes": buf.getbuffer().nbytes}
            res.append(r)
            probs[name], fitted[name] = pt, m
            print(f"   {tg} / {name}: val AP {val_ap:.3f}, test AP {r['avg_precision']:.3f}, fit {fit_s:.1f}s")

        # 3. winner by VAL average precision
        win = max(res, key=lambda r: r["val_ap"])
        winners[tg] = win
        joblib.dump({"model": fitted[win["method"]], "features": feats, "threshold": win["threshold"],
                     "algorithm": win["method"], "val_ap": win["val_ap"], "trained_until": str(t.iloc[tv].max())},
                    model_dir / f"{tg}_model.joblib", compress=3)

        # 4. baselines
        bases = {"AlwaysNo": np.zeros(len(yte), dtype=int)}
        if tg == "rain":
            bases["OpenMeteoForecast"] = (base_sum.iloc[sp["test"]].to_numpy() >= RAIN_MM).astype(int)
        else:
            bases["Persistence"] = (pm_now.iloc[sp["test"]].to_numpy() >= DUST_PM10).astype(int)
        for name, pred in bases.items():
            res.append({"target": tg, "method": name, **metrics(yte, pred)})
        rows += res

        # charts: PR curves on test
        fig, ax = plt.subplots(figsize=(7, 5))
        for name, pt in probs.items():
            p, rc, _ = precision_recall_curve(yte, pt)
            ax.plot(rc, p, label=f"{name} (AP = {average_precision_score(yte, pt):.3f})")
        for (name, pred), mk in zip(bases.items(), ("x", "o")):
            ax.plot(recall_score(yte, pred, zero_division=0), precision_score(yte, pred, zero_division=0),
                    mk, ms=9, label=f"{name} (single point)")
        ax.set_xlabel("Recall (share of real events caught)")
        ax.set_ylabel("Precision (share of alarms that were right)")
        ax.set_title(f"Hilla {tg}: precision-recall on test (2025+), next {H} h")
        ax.set_xlim(0, 1.02)
        ax.set_ylim(0, 1.02)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(chart_dir / f"pr_curves_{tg}{sfx}.png", dpi=120)
        plt.close(fig)

        # charts: permutation importance of the winner on a 5000-row test sample
        smp = np.random.default_rng(SEED).choice(len(Xte), min(5000, len(Xte)), replace=False)
        pi = permutation_importance(fitted[win["method"]], Xte.iloc[smp], yte.iloc[smp],
                                    scoring="average_precision", n_repeats=5, random_state=SEED)
        top = pd.Series(pi.importances_mean, index=feats).sort_values().tail(15)
        err = pd.Series(pi.importances_std, index=feats)[top.index]
        fig, ax = plt.subplots(figsize=(8, 5.5))
        ax.barh(top.index, top.values, xerr=err.values, color="tab:blue")
        ax.set_xlabel("Drop in average precision when the feature is shuffled")
        ax.set_title(f"Hilla {tg}: top 15 features ({win['method']}, test sample of {len(smp):,} h)")
        fig.tight_layout()
        fig.savefig(chart_dir / f"feature_importance_{tg}{sfx}.png", dpi=120)
        plt.close(fig)

    cmp = pd.DataFrame(rows, columns=COLS)
    cmp.to_csv(f"reports/model_comparison{sfx}.csv", index=False)

    show = ["method", "val_ap", "threshold", "accuracy", "precision", "recall", "f1", "roc_auc",
            "avg_precision", "fit_time_s", "predict_ms_per_1000", "model_size_bytes"]
    for tg in TARGETS:
        P(f"\n=== {tg}: test results (2025+), threshold chosen on val ===")
        P(cmp[cmp["target"] == tg][show].to_string(index=False, na_rep="", float_format=lambda v: f"{v:.3f}"))
    P("\n=== winners (highest validation average precision, not test) ===")
    for tg, w in winners.items():
        P(f"{tg}: {w['method']}   val AP {w['val_ap']:.3f}   threshold {w['threshold']:.3f}   "
          f"saved to {model_dir}/{tg}_model.joblib")

    if args.extended:
        base = pd.read_csv("reports/model_comparison.csv")
        P("\n=== base vs extended (test F1, test AP, val AP) ===")
        P(f"{'target':<7}{'method':<18}{'F1 base':>9}{'F1 ext':>9}{'AP base':>9}{'AP ext':>9}{'valAP base':>12}{'valAP ext':>11}")
        for tg in TARGETS:
            for name in MODELS:
                b = base[(base["target"] == tg) & (base["method"] == name)].iloc[0]
                x = cmp[(cmp["target"] == tg) & (cmp["method"] == name)].iloc[0]
                P(f"{tg:<7}{name:<18}{b['f1']:>9.3f}{x['f1']:>9.3f}{b['avg_precision']:>9.3f}{x['avg_precision']:>9.3f}"
                  f"{b['val_ap']:>12.3f}{x['val_ap']:>11.3f}")

    v1 = Path("reports/model_comparison_extended_v1.csv")
    if args.extended and v1.exists():
        old = pd.read_csv(v1)
        P("\n=== v1 (no METAR) vs v2 (with METAR): test F1, test AP, val AP ===")
        P("NOTE: the dust target changed in v2 (also counts strong airport dust), so dust rows are NOT directly comparable; rain rows are.")
        P(f"{'target':<7}{'method':<18}{'F1 v1':>8}{'F1 v2':>8}{'AP v1':>8}{'AP v2':>8}{'valAP v1':>10}{'valAP v2':>10}")
        for tg in TARGETS:
            for name in MODELS:
                b = old[(old["target"] == tg) & (old["method"] == name)].iloc[0]
                x = cmp[(cmp["target"] == tg) & (cmp["method"] == name)].iloc[0]
                P(f"{tg:<7}{name:<18}{b['f1']:>8.3f}{x['f1']:>8.3f}{b['avg_precision']:>8.3f}{x['avg_precision']:>8.3f}"
                  f"{b['val_ap']:>10.3f}{x['val_ap']:>10.3f}")

    # self-checks
    assert set(cmp["target"]) == set(TARGETS) and len(cmp) == 10, "unexpected comparison rows"
    for tg in TARGETS:
        z = cmp[(cmp["target"] == tg) & (cmp["method"] == "AlwaysNo")].iloc[0]
        assert z["recall"] == 0, "AlwaysNo should have zero recall"
        assert (model_dir / f"{tg}_model.joblib").exists(), "model not saved"

    P(f"\ntotal runtime: {time.time() - t0:.0f} s")
    P("checks passed. Data: Open-Meteo.com (CC BY 4.0)")
    (d / f"train_report{sfx}.txt").write_text("\n".join(out), encoding="utf-8")
    print(f"\nreport saved to {d / f'train_report{sfx}.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
