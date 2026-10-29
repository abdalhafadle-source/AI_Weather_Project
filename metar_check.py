#!/usr/bin/env python3
"""
metar_check.py
Does CAMS PM10 (our dust source) see the dust that the airports (METAR, Najaf + Baghdad) report?

Usage:
    python metar_check.py                   # reads data/processed/hilla_hourly_labeled.csv + hilla_events.csv

METAR dust episode = run of hours with metar_any_dust == 1, runs joined when the gap is <= 3 h.
Second block: the same for metar_strong_dust (dust AND visibility <= 2 km). The chart shows any-dust episodes.
CAMS "caught" an episode if is_dust_storm == 1 anywhere in [start - 6 h, end + 6 h].
Reverse: a CAMS storm (hilla_events.csv, type dust) is "confirmed" if METAR has dust within +-6 h.

Outputs: <dir>/metar_report.txt, reports/charts/metar_vs_cams.png
Only files in data/processed are read; the raw folders are never touched.

Data: Iowa Environmental Mesonet (METAR); Open-Meteo.com (CC BY 4.0) for CAMS PM10.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

GAP_H, PAD = 3, pd.Timedelta(hours=6)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/processed")
    args = ap.parse_args()
    d = Path(args.dir)
    Path("reports/charts").mkdir(parents=True, exist_ok=True)
    out = []

    def P(s=""):
        out.append(s)
        print(s)

    df = pd.read_csv(d / "hilla_hourly_labeled.csv", parse_dates=["time"]).set_index("time")
    ev = pd.read_csv(d / "hilla_events.csv", parse_dates=["start", "end"])
    ev = ev[ev["type"] == "dust"]
    assert df["metar_strong_dust"].notna().all(), "run download_metar.py and prepare_data.py first"

    def episodes(col):
        # runs of hours with col == 1, joined when the gap is <= 3 h
        h = df.index[df[col] == 1]
        new = np.r_[True, np.diff(h.to_numpy()) > np.timedelta64(GAP_H + 1, "h")]
        grp = pd.Series(h).groupby(new.cumsum())
        epi = pd.DataFrame({"start": grp.min(), "end": grp.max()}).reset_index(drop=True)
        storm = df["is_dust_storm"] == 1
        epi["caught"] = [storm[a - PAD:b + PAD].any() for a, b in zip(epi["start"], epi["end"])]
        epi["max_pm10"] = [df["aq_pm10"][a:b].max() for a, b in zip(epi["start"], epi["end"])]
        epi["min_vis"] = [df["metar_min_vis_km"][a:b].min() for a, b in zip(epi["start"], epi["end"])]
        got, miss = epi[epi["caught"]], epi[~epi["caught"]]
        conf = [df[col][a - PAD:b + PAD].max() == 1 for a, b in zip(ev["start"], ev["end"])]
        P(f"{col}: dust hours {len(h):,}, episodes {len(epi)} (gap <= {GAP_H} h joined), per year {len(epi) / (len(df) / 8766):.1f}")
        P("  per calendar year: " + ", ".join(f"{y}: {n}" for y, n in epi["start"].dt.year.value_counts().sort_index().items()))
        P(f"  CAMS caught (is_dust_storm within +-6 h): {int(epi['caught'].sum())} of {len(epi)} = {100 * epi['caught'].mean():.1f}%")
        P(f"  missed episodes: {len(miss)}   max aq_pm10 during them: median {miss['max_pm10'].median():.0f}, "
          f"p90 {miss['max_pm10'].quantile(0.9):.0f}")
        P(f"  median min visibility (km) in episode: caught {got['min_vis'].median():.1f}, missed {miss['min_vis'].median():.1f}")
        P(f"  reverse: CAMS storms {len(ev)}, with {col} within +-6 h: {sum(conf)} = {100 * np.mean(conf):.1f}%")
        assert len(epi) == len(got) + len(miss) and epi["end"].ge(epi["start"]).all()
        assert (epi["start"].iloc[1:].to_numpy() - epi["end"].iloc[:-1].to_numpy() > np.timedelta64(GAP_H + 1, "h")).all()
        return epi, miss

    P("=== metar_check report ===")
    P(f"period: {df.index.min()} .. {df.index.max()}")
    epi, miss = episodes("metar_any_dust")
    P("")
    P("strong dust = dust code AND min visibility <= 2 km")
    episodes("metar_strong_dust")

    # chart: per calendar month (any-dust episodes)
    m = pd.DataFrame({"METAR episodes": epi.groupby(epi["start"].dt.to_period("M")).size(),
                      "CAMS storms": ev.groupby(ev["start"].dt.to_period("M")).size(),
                      "CAMS-missed": miss.groupby(miss["start"].dt.to_period("M")).size()})
    m = m.reindex(pd.period_range(df.index.min(), df.index.max(), freq="M")).fillna(0)
    fig, ax = plt.subplots(figsize=(14, 4.5))
    x, w = np.arange(len(m)), 0.28
    for k, (c, col) in enumerate(zip(m.columns, ("tab:orange", "tab:blue", "tab:red"))):
        ax.bar(x + (k - 1) * w, m[c], w, label=c, color=col)
    ax.set_xticks(x[::3])
    ax.set_xticklabels([str(q) for q in m.index[::3]], rotation=60, fontsize=8)
    ax.set_ylabel("Episodes per month")
    ax.set_title("Dust seen by airports (METAR) vs CAMS PM10 storms, Hilla 2022-2026")
    ax.legend()
    fig.tight_layout()
    fig.savefig("reports/charts/metar_vs_cams.png", dpi=120)
    plt.close(fig)

    P("\nchecks passed. Data: Iowa Environmental Mesonet (METAR); Open-Meteo.com (CC BY 4.0)")
    (d / "metar_report.txt").write_text("\n".join(out), encoding="utf-8")
    print(f"\nreport saved to {d / 'metar_report.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
