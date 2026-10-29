#!/usr/bin/env python3
"""
simulate_decisions.py
Replay 2025-01-01 .. end of data hour by hour as if live, and compare cleaning strategies.

Usage:
    python simulate_decisions.py            # reads data/processed/hilla_hourly_labeled.csv, models/extended/
    python simulate_decisions.py --dir data/processed

Live inputs to decision.step(): fc_precipitation (forecast, not obs) and aq_pm10. Strategies differ only in
`safe` / `min_wait`:  AI (extended models), FixedDelay (rules only), Fixed5h (always wait 5 h),
ForecastRule (forecast next 6 h dry and PM10 < 150), Oracle (perfect knowledge, upper bound).
A clean is "good" if t+1..t+6 has no obs_precipitation >= 0.1, no aq_pm10 >= 150 and no metar_strong_dust,
else "wasted" (primary truth, includes the airports). good%_cams is the old truth without METAR.
Airport dust is passed to step() for every strategy except AI_noMETAR (same models, no METAR input):
dust_obs = strong dust now and 1 h ago (storm), haze = any other airport dust now (blocks cleaning).
Oracle uses the primary truth.

Outputs: <dir>/decisions_2025_2026.csv, <dir>/simulation_report.txt,
         reports/charts/strategy_comparison.png, decision_timeline.png
Only hilla_hourly_labeled.csv and the saved models are read; the raw folders are never touched.

Data: Open-Meteo.com (CC BY 4.0) - cite it in the report.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from decision import DUST_START, HOUR, MAX_PER_DAY, MIN_GAP_H, RAIN_NOW_MM, new_state, step
from train_models import RAIN_MM, H, build, build_ext, fwd

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

START = "2025-01-01"
SAFE_PM10 = 150          # PM10 that re-dirties panels
STRATS = ("AI", "AI_noMETAR", "FixedDelay", "Fixed5h", "ForecastRule", "Oracle")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/processed")
    args = ap.parse_args()
    d = Path(args.dir)
    chart_dir = Path("reports/charts")
    chart_dir.mkdir(parents=True, exist_ok=True)
    out = []

    def P(s=""):
        out.append(s)
        print(s)

    df = pd.read_csv(d / "hilla_hourly_labeled.csv", parse_dates=["time"])
    X = build(df)
    X = X.join(build_ext(df, X))
    mr, md = joblib.load("models/extended/rain_model.joblib"), joblib.load("models/extended/dust_model.joblib")
    ok = X[mr["features"]].notna().all(axis=1) & X[md["features"]].notna().all(axis=1)
    p_rain, p_dust = pd.Series(np.nan, index=df.index), pd.Series(np.nan, index=df.index)
    p_rain[ok] = mr["model"].predict_proba(X.loc[ok, mr["features"]])[:, 1]
    p_dust[ok] = md["model"].predict_proba(X.loc[ok, md["features"]])[:, 1]
    th_r, th_d = mr["threshold"], md["threshold"]

    # truth for t+1..t+6 and forecast sum (NaN at the end of the data)
    true_rain = fwd(df["obs_precipitation"], "max") >= RAIN_MM
    true_dust = fwd(df["aq_pm10"], "max") >= SAFE_PM10
    known = fwd(df["obs_precipitation"], "max").notna() & fwd(df["aq_pm10"], "max").notna()
    fc_sum = fwd(df["fc_precipitation"], "sum")
    truth_cams = ~(true_rain | true_dust)
    truth_safe = truth_cams & ~(fwd(df["metar_strong_dust"], "max") >= 1)     # primary: strong airport dust also counts
    ai_safe = ok & (p_rain < th_r) & (p_dust < th_d)           # NaN features -> not safe
    safe = {"AI": ai_safe,
            "AI_noMETAR": ai_safe,
            "FixedDelay": pd.Series(True, index=df.index),
            "Fixed5h": pd.Series(True, index=df.index),
            "ForecastRule": (fc_sum < RAIN_MM) & (df["aq_pm10"] < SAFE_PM10),
            "Oracle": truth_safe}
    mwait = {"Fixed5h": {"rain": 5, "dust": 5}}

    idx = np.flatnonzero((df["time"] >= START) & known).tolist()
    assert df["aq_pm10"].iloc[idx].notna().all(), "NaN pm10 in the replay period"
    times = df["time"]
    rain_in, pm_in = df["fc_precipitation"].to_numpy(), df["aq_pm10"].to_numpy()
    obs_rain = df["obs_precipitation"].to_numpy()
    strong = df["metar_strong_dust"] == 1
    dust_ob = (strong & strong.shift(1, fill_value=False)).to_numpy()
    haze_ob = ((df["metar_any_dust"] == 1) & ~pd.Series(dust_ob, index=df.index)).to_numpy()

    rows, stats = [], {}
    for name in STRATS:
        st, sf = new_state(), safe[name].to_numpy()
        events = missed = 0
        dirty = []
        for i in idx:
            t = times.iloc[i].to_pydatetime()
            before_p, before_in = len(st["pending"]), st["raining"] or st["storm"]
            act, why = step(st, t, rain_in[i], pm_in[i], bool(sf[i]), mwait.get(name), dust_obs=bool(dust_ob[i]) and name != "AI_noMETAR", haze=bool(haze_ob[i]) and name != "AI_noMETAR")
            if before_p == 0 and st["pending"]:
                events += 1
            if before_p and not before_in and (st["raining"] or st["storm"]):
                missed += 1                                   # new event before we managed to clean
            if act == "clean":
                assert rain_in[i] < RAIN_NOW_MM and not st["storm"], f"{name}: clean during rain/storm at {t}"
                assert name != "AI" or not (dust_ob[i] or haze_ob[i]), f"AI clean during airport dust at {t}"
                dirty.append((t - st["last_end"]) / HOUR)
                rows.append(dict(strategy=name, time=t, trigger=why,
                                 outcome="good" if truth_safe.iloc[i] else "wasted",
                                 outcome_cams="good" if truth_cams.iloc[i] else "wasted",
                                 during_event=bool(obs_rain[i] >= RAIN_MM or pm_in[i] >= DUST_START),
                                 p_rain=p_rain.iloc[i], p_dust=p_dust.iloc[i]))
        stats[name] = dict(events=events, missed=missed, dirty=np.array(dirty), cleans=st["cleans"])
        # self-checks
        days = pd.Series(st["cleans"]).dt.date.value_counts() if st["cleans"] else pd.Series(dtype=int)
        assert (days <= MAX_PER_DAY).all(), f"{name}: more than {MAX_PER_DAY} cleans in a day"
        gaps = np.diff(pd.Series(st["cleans"]).to_numpy()) / np.timedelta64(1, "h")
        assert (gaps >= MIN_GAP_H).all(), f"{name}: gap below {MIN_GAP_H} h"

    dec = pd.DataFrame(rows, columns=["strategy", "time", "trigger", "outcome", "outcome_cams", "during_event", "p_rain", "p_dust"])
    dec.to_csv(d / "decisions_2025_2026.csv", index=False)

    t0, t1 = times.iloc[idx[0]], times.iloc[idx[-1]]
    P("=== simulate_decisions report ===")
    P(f"replay: {t0} .. {t1}  ({len(idx):,} hours)   AI thresholds: rain {th_r:.3f}, dust {th_d:.3f}")
    P("live inputs: fc_precipitation and aq_pm10; truth for outcome: obs_precipitation, aq_pm10, metar_strong_dust in t+1..t+6")
    P("caps: max %d cleans/day, min %d h between cleans; Oracle is an upper bound, not achievable\n" % (MAX_PER_DAY, MIN_GAP_H))
    hdr = f"{'strategy':<14}{'cleans':>7}{'2025':>6}{'2026':>6}{'good':>6}{'wasted':>7}{'good%':>7}{'good%_cams':>11}{'in_event':>9}" \
          f"{'dirty_med_h':>12}{'dirty_p90_h':>12}{'events':>8}{'missed':>8}"
    P(hdr)
    summ = {}
    for name in STRATS:
        x, s = dec[dec["strategy"] == name], stats[name]
        good = int((x["outcome"] == "good").sum())
        n = len(x)
        yr = x["time"].dt.year.value_counts()
        dv = s["dirty"]
        good_m = int((x["outcome_cams"] == "good").sum())
        summ[name] = (good, n - good)
        P(f"{name:<14}{n:>7}{yr.get(2025, 0):>6}{yr.get(2026, 0):>6}{good:>6}{n - good:>7}{100 * good / max(n, 1):>7.1f}{100 * good_m / max(n, 1):>11.1f}"
          f"{int(x['during_event'].sum()):>9}{np.median(dv):>12.1f}{np.percentile(dv, 90):>12.1f}"
          f"{s['events']:>8}{s['missed']:>8}")
    P("\ngood% = no obs rain, PM10 < 150 and no strong airport dust in t+1..t+6; good%_cams = same without the airport part.")
    P("in_event = clean at an hour that itself had obs rain or PM10 >= %d; dirty_*_h = hours from event end to clean;"
      % DUST_START)
    P("events = times something needed cleaning; missed = a new event arrived before we cleaned.")

    # charts
    fig, ax = plt.subplots(figsize=(8, 4.5))
    xs = np.arange(len(STRATS))
    g = [summ[k][0] for k in STRATS]
    w = [summ[k][1] for k in STRATS]
    ax.bar(xs, g, color="tab:green", label="good")
    ax.bar(xs, w, bottom=g, color="tab:red", label="wasted")
    for i, (a, b) in enumerate(zip(g, w)):
        ax.text(i, a + b, f"{100 * a / max(a + b, 1):.0f}% good", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(xs)
    ax.set_xticklabels(STRATS)
    ax.set_ylabel("Number of cleans")
    ax.set_title("Hilla: cleaning strategies replayed on 2025+ (good = dry and clean air for 6 h after)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(chart_dir / "strategy_comparison.png", dpi=120)
    plt.close(fig)

    ai = pd.Series(stats["AI"]["cleans"])
    ai25 = ai[ai.dt.year == 2025]
    hours = pd.date_range("2025-01-01", periods=int(((times.iloc[-1] - pd.Timestamp("2025-01-01")) / HOUR)) + 1, freq="h")
    cnt = pd.Series(0, index=hours)
    cnt[cnt.index.isin(ai25)] = 1
    win = cnt.rolling(240).sum()
    win = win[win.index < "2026-01-01"]
    end = win.idxmax()
    lo = end - 239 * HOUR
    seg = df[(df["time"] >= lo) & (df["time"] <= end)]
    sg = pd.DataFrame({"p_rain": p_rain, "p_dust": p_dust}).loc[seg.index]
    fd = pd.Series(stats["FixedDelay"]["cleans"])
    fig, axs = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    axs[0].plot(seg["time"], seg["aq_pm10"], color="black", lw=1)
    axs[0].axhline(SAFE_PM10, ls="--", color="orange", label="150")
    axs[0].axhline(DUST_START, ls="--", color="red", label="200")
    axs[0].set_ylabel("PM10 (µg/m³)")
    axs[0].legend(loc="upper right")
    axs[1].bar(seg["time"], seg["obs_precipitation"], width=1 / 24, color="tab:blue", label="observed (obs)")
    axs[1].plot(seg["time"], seg["fc_precipitation"], color="tab:orange", lw=1, label="forecast (fc)")
    axs[1].set_ylabel("Precipitation (mm/h)")
    axs[1].legend(loc="upper right")
    axs[2].plot(seg["time"], sg["p_rain"], color="tab:blue", label="p_rain")
    axs[2].plot(seg["time"], sg["p_dust"], color="tab:brown", label="p_dust")
    axs[2].axhline(th_r, ls=":", color="tab:blue")
    axs[2].axhline(th_d, ls=":", color="tab:brown")
    axs[2].set_ylabel("Model probability")
    axs[2].legend(loc="upper right")
    for k, a in enumerate(axs):
        for c in ai[(ai >= lo) & (ai <= end)]:
            a.axvline(c, color="green", lw=1.5, label="AI clean" if (k == 0 and c == ai[(ai >= lo) & (ai <= end)].iloc[0]) else None)
        for c in fd[(fd >= lo) & (fd <= end)]:
            a.axvline(c, color="red", ls="--", lw=1)
    axs[0].plot([], [], color="green", label="AI clean")
    axs[0].plot([], [], color="red", ls="--", label="FixedDelay clean")
    axs[0].legend(loc="upper right")
    axs[0].set_title(f"Decision timeline {lo:%Y-%m-%d} .. {end:%Y-%m-%d} (10 days with the most AI cleans)")
    axs[2].set_xlabel("Time")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(chart_dir / "decision_timeline.png", dpi=120)
    plt.close(fig)

    assert set(dec["strategy"]) == set(STRATS), "a strategy made no cleans"
    P("\nchecks passed. Data: Open-Meteo.com (CC BY 4.0)")
    (d / "simulation_report.txt").write_text("\n".join(out), encoding="utf-8")
    print(f"\nreport saved to {d / 'simulation_report.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
