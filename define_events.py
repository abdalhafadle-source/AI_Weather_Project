#!/usr/bin/env python3
"""
define_events.py
Define "rain event" and "dust storm" from the data, and test how long to wait
after an event ends before cleaning the PV panels.

Usage:
    python define_events.py                 # reads data/processed/hilla_hourly.csv
    python define_events.py --dir data/processed

Outputs: <dir>/hilla_events.csv, <dir>/hilla_hourly_labeled.csv, <dir>/events_report.txt
         reports/charts/events_per_month.png, storm_example.png, delay_tradeoff.png
Only hilla_hourly.csv is read; the raw folders are never touched.

Data: Open-Meteo.com (CC BY 4.0) - cite it in the report.
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

RAIN_MM = 0.1            # an hour counts as rainy
RAIN_EVENT_MIN_MM = 0.5  # ignore events with less total rain (ERA5 over-reports drizzle)
RAIN_GAP_H = 2           # rainy hours closer than this belong to one event
DUST_START = 200         # PM10 that starts a storm
DUST_END = 100           # storm lasts until PM10 falls below this (hysteresis stops flicker)
DUST_GAP_H = 3           # storms closer than this are merged
DELAYS = (1, 3, 5, 8, 12)  # waiting times to test after an event ends, hours
RESOIL_PM10 = 150        # PM10 that re-dirties freshly cleaned panels
WINDOW_H = 6             # hours after cleaning we check for re-soiling / new rain


def merge_spans(spans, gap):
    # spans: sorted list of (start_pos, end_pos); join when next.start - prev.end <= gap
    out = []
    for s, e in spans:
        if out and s - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/processed")
    args = ap.parse_args(argv)
    d = Path(args.dir)
    chart_dir = Path("reports/charts")
    chart_dir.mkdir(parents=True, exist_ok=True)
    out = []

    def P(s=""):
        out.append(s)
        print(s)

    df = pd.read_csv(d / "hilla_hourly.csv", parse_dates=["time"])
    n = len(df)
    t = df["time"]
    rain = df["obs_precipitation"].to_numpy()
    pm = df["aq_pm10"].to_numpy()

    # 1. rain events (positions in the hourly table)
    idx = np.flatnonzero(rain >= RAIN_MM)
    rain_spans = merge_spans([(i, i) for i in idx], RAIN_GAP_H)
    rows = []
    for s, e in rain_spans:
        tot = float(rain[s:e + 1].sum())
        if tot >= RAIN_EVENT_MIN_MM:
            rows.append(("rain", s, e, float(rain[s:e + 1].max()), tot))

    # 2. dust storms (hysteresis, then merge)
    raw, i = [], 0
    while i < n:
        if pm[i] >= DUST_START:
            j = i
            while j + 1 < n and pm[j + 1] >= DUST_END:
                j += 1
            raw.append((i, j))
            i = j + 1
        else:
            i += 1
    for s, e in merge_spans(raw, DUST_GAP_H):
        rows.append(("dust", s, e, float(pm[s:e + 1].max()), np.nan))

    # 3. events table
    ev = pd.DataFrame(rows, columns=["type", "s", "e", "peak", "total_mm"]).sort_values("s", kind="stable")
    ev["start"] = t.iloc[ev["s"].to_numpy()].to_numpy()
    ev["end"] = t.iloc[ev["e"].to_numpy()].to_numpy()
    ev["duration_h"] = ev["e"] - ev["s"] + 1
    ev = ev.reset_index(drop=True)
    ev[["type", "start", "end", "duration_h", "peak", "total_mm"]].to_csv(d / "hilla_events.csv", index=False)

    # 4. labeled hourly table
    is_rain = np.zeros(n, dtype=int)
    is_dust = np.zeros(n, dtype=int)
    for r in ev.itertuples():
        (is_rain if r.type == "rain" else is_dust)[r.s:r.e + 1] = 1
    lab = df.copy()
    lab["is_rain"] = is_rain
    lab["is_dust_storm"] = is_dust
    lab.to_csv(d / "hilla_hourly_labeled.csv", index=False)
    any_event = (is_rain | is_dust).astype(bool)

    # 5. delay analysis
    years = (t.iloc[-1] - t.iloc[0]).total_seconds() / 86400 / 365.25
    tables = {}
    for typ in ("rain", "dust"):
        res = []
        for dl in DELAYS:
            ins, rs, ra, med, k = [], [], [], [], 0
            for r in ev[ev["type"] == typ].itertuples():
                c = r.e + dl
                if c + WINDOW_H >= n:
                    continue
                k += 1
                ins.append(any_event[c])
                rs.append((pm[c + 1:c + WINDOW_H + 1] >= RESOIL_PM10).any())
                ra.append((rain[c + 1:c + WINDOW_H + 1] >= RAIN_MM).any())
                med.append(pm[c])
            res.append((dl, k, 100 * np.mean(ins), 100 * np.mean(rs), 100 * np.mean(ra), float(np.median(med))))
        tables[typ] = pd.DataFrame(res, columns=["delay_h", "events", "inside_event_%", "resoil_%",
                                                 "rain_again_%", "median_pm10_at_clean"])

    # 6. report
    P("=== define_events report ===")
    P(f"data: {n:,} rows   from {t.iloc[0]}   to {t.iloc[-1]}   ({years:.2f} years)")
    P("\nthresholds used:")
    for name in ("RAIN_MM", "RAIN_EVENT_MIN_MM", "RAIN_GAP_H", "DUST_START", "DUST_END", "DUST_GAP_H",
                 "DELAYS", "RESOIL_PM10", "WINDOW_H"):
        P(f"   {name:<18} = {globals()[name]}")
    for typ in ("rain", "dust"):
        x = ev[ev["type"] == typ]
        P(f"\n=== {typ} ===")
        P(f"events: {len(x)}   per year: {len(x) / years:.1f}")
        P(f"duration h: median {x['duration_h'].median():.0f}   max {x['duration_h'].max()}")
        if typ == "rain":
            P(f"total mm per event: median {x['total_mm'].median():.1f}   max {x['total_mm'].max():.1f}")
        else:
            P(f"peak PM10: median {x['peak'].median():.0f}   max {x['peak'].max():.0f}")
        P(f"\ndelay after {typ} ends (cleaning at end + delay; window = next {WINDOW_H} h):")
        P(tables[typ].to_string(index=False, float_format=lambda v: f"{v:.1f}"))

    # 7. charts
    nyears = years
    mon = pd.DataFrame({m: [((ev["type"] == ty) & (ev["start"].dt.month == m)).sum() / nyears
                            for ty in ("rain", "dust")] for m in range(1, 13)}, index=["rain", "dust"])
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x = np.arange(12)
    ax.bar(x - 0.2, mon.loc["rain"], 0.4, label="Rain events", color="tab:blue")
    ax.bar(x + 0.2, mon.loc["dust"], 0.4, label="Dust storms", color="tab:orange")
    ax.set_xticks(x)
    ax.set_xticklabels(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_xlabel("Calendar month")
    ax.set_ylabel("Events per month (average per year)")
    ax.set_title("Hilla: average rain events and dust storms per month")
    ax.legend()
    fig.tight_layout()
    fig.savefig(chart_dir / "events_per_month.png", dpi=120)
    plt.close(fig)

    top = ev[ev["type"] == "dust"].sort_values("peak", ascending=False).iloc[0]
    lo, hi = max(0, top.s - 24), min(n - 1, top.e + 24)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(t.iloc[lo:hi + 1], pm[lo:hi + 1], color="black", lw=1.2, label="PM10")
    ax.axhline(DUST_START, ls="--", color="red", label=f"start threshold ({DUST_START})")
    ax.axhline(DUST_END, ls="--", color="green", label=f"end threshold ({DUST_END})")
    ax.axvspan(top.start, top.end, color="orange", alpha=0.25, label="storm")
    for dl in DELAYS:
        tx = top.end + pd.Timedelta(hours=dl)
        ax.axvline(tx, color="gray", lw=0.7)
        ax.text(tx, ax.get_ylim()[1], f"+{dl}h", ha="center", va="bottom", fontsize=8)
    ax.set_xlabel("Time")
    ax.set_ylabel("PM10 (µg/m³)")
    ax.set_title(f"Strongest dust storm (peak {top.peak:.0f} µg/m³, starts {top.start:%Y-%m-%d %H:%M})", pad=18)
    ax.legend(loc="upper right")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(chart_dir / "storm_example.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    dd, rr = tables["dust"], tables["rain"]
    ax.plot(dd["delay_h"], dd["resoil_%"], "o-", label="After dust: re-soiling (PM10 >= %d)" % RESOIL_PM10)
    ax.plot(dd["delay_h"], dd["inside_event_%"], "o-", label="After dust: cleaning inside an event")
    ax.plot(rr["delay_h"], rr["rain_again_%"], "s--", label="After rain: rain again")
    ax.plot(rr["delay_h"], rr["resoil_%"], "s--", label="After rain: re-soiling (PM10 >= %d)" % RESOIL_PM10)
    ax.set_xlabel("Delay after event end (hours)")
    ax.set_ylabel(f"Share of events (%) within {WINDOW_H} h window")
    ax.set_title("Cleaning delay trade-off")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(chart_dir / "delay_tradeoff.png", dpi=120)
    plt.close(fig)

    # 8. self-checks
    for typ in ("rain", "dust"):
        x = ev[ev["type"] == typ]
        assert x["s"].is_monotonic_increasing, f"{typ} not sorted"
        assert (x["s"].to_numpy()[1:] > x["e"].to_numpy()[:-1]).all(), f"{typ} events overlap"
    assert (ev.loc[ev["type"] == "dust", "peak"] >= DUST_START).all(), "dust peak below DUST_START"
    assert (ev.loc[ev["type"] == "rain", "total_mm"] >= RAIN_EVENT_MIN_MM).all(), "rain total below minimum"
    assert is_rain.sum() == ev.loc[ev["type"] == "rain", "duration_h"].sum(), "is_rain != rain durations"
    assert is_dust.sum() == ev.loc[ev["type"] == "dust", "duration_h"].sum(), "is_dust != dust durations"

    P("\nchecks passed. Data: Open-Meteo.com (CC BY 4.0)")
    (d / "events_report.txt").write_text("\n".join(out), encoding="utf-8")
    print(f"\nreport saved to {d / 'events_report.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
