#!/usr/bin/env python3
"""
make_figures.py
Build all thesis figures into thesis/figures/ (copies of existing charts + new ones).

Usage:
    python thesis/make_figures.py              # everything
    python thesis/make_figures.py --skip-net   # skip fig19-fig21 (need internet / Edge)

Reads: reports/charts/*.png, reports/model_comparison*.csv,
       the live decision log on GitHub (fig19), the live page (fig20, fig21).
Outputs: thesis/figures/fig01..fig21 *.png and README.txt
The raw data folders are never touched.

Data: Open-Meteo.com (CC BY 4.0) - cite it in the thesis.
"""
from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "thesis" / "figures"
CHARTS = ROOT / "reports" / "charts"
LOG_URL = ("https://raw.githubusercontent.com/abdalhafadle-source/"
           "AI_Weather_Project/main/output/decision_log.csv")
PAGE_URL = "https://hilla-ai.duckdns.org/"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

RAIN, DUST, GOOD, WARN = "#2a78d6", "#eb6834", "#0ca30c", "#fab219"
DARK, MID = "#52514e", "#8a8984"
GRID = "#e3e2de"

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    "axes.edgecolor": MID, "axes.titlesize": 12, "axes.labelsize": 10,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.axisbelow": True, "font.size": 10, "text.color": DARK,
    "axes.labelcolor": DARK, "xtick.color": DARK, "ytick.color": DARK,
})

COPIES = {
    "fig03_events_per_month.png": "events_per_month.png",
    "fig04_storm_example.png": "storm_example.png",
    "fig05_delay_tradeoff.png": "delay_tradeoff.png",
    "fig06_pr_rain_base.png": "pr_curves_rain.png",
    "fig07_pr_dust_base.png": "pr_curves_dust.png",
    "fig08_importance_rain_base.png": "feature_importance_rain.png",
    "fig09_importance_dust_base.png": "feature_importance_dust.png",
    "fig10_pr_rain_final.png": "pr_curves_rain_extended.png",
    "fig11_pr_dust_final.png": "pr_curves_dust_extended.png",
    "fig12_importance_rain_final.png": "feature_importance_rain_extended.png",
    "fig13_importance_dust_final.png": "feature_importance_dust_extended.png",
    "fig15_metar_vs_cams.png": "metar_vs_cams.png",
    "fig16_strategy_comparison.png": "strategy_comparison.png",
    "fig17_decision_timeline.png": "decision_timeline.png",
}


def save(fig, name):
    fig.savefig(OUT / name, dpi=150, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print("wrote", name)


# ---------- diagram helpers ----------
def box(ax, x, y, w, h, text, fc="#f4f3f0", ec=MID, fs=9, bold=False, tc=DARK):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.0,rounding_size=0.8",
                                fc=fc, ec=ec, lw=1.3))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
            color=tc, fontweight="bold" if bold else "normal", linespacing=1.35)


def arrow(ax, p, q, color=DARK):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=14,
                                 color=color, lw=1.5, shrinkA=0, shrinkB=0))


def blank(figsize, xlim, ylim):
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.axis("off")
    return fig, ax


# ---------- fig01 ----------
def fig01():
    fig, ax = blank((16, 9), (0, 160), (0, 90))
    ax.text(80, 87, "System architecture", ha="center", fontsize=14, fontweight="bold")
    heads = [(19, "1. Data sources"), (63, "2. VPS server (DigitalOcean, Frankfurt)"),
             (107, "3. FastAPI + Caddy HTTPS"), (143, "4. Field device")]
    for x, h in heads:
        ax.text(x, 80, h, ha="center", va="center", fontsize=10.5, fontweight="bold")
    srcs = ["Open-Meteo forecasts\n(best_match, GFS,\nUKMO, JMA)",
            "CAMS dust forecast\n(PM10)",
            "Airport reports METAR\n(Najaf ORNI,\nBaghdad ORBI)"]
    for i, t in enumerate(srcs):
        y = 56 - i * 22
        box(ax, 2, y, 34, 17, t, fc="#e8f0fb", ec=RAIN, fs=10)
        arrow(ax, (36, y + 8.5), (40, 44), color=MID)
    ax.add_patch(FancyBboxPatch((40, 12), 46, 64, boxstyle="round,pad=0,rounding_size=1",
                                fc="#fafaf8", ec=DARK, lw=1.6))
    steps = ["live_decision.py\nevery hour (:05, retry :35)",
             "58 features",
             "2 Random Forest models\nP(rain next 6 h), P(dust next 6 h)",
             "decision.py\nrules + safety caps",
             "command.json"]
    ys = [64, 53, 40, 27, 16]
    hs = [9, 7, 10, 9, 7]
    for t, y, h in zip(steps, ys, hs):
        fc = "#fef1d0" if t.startswith("2 Random") else "#ffffff"
        box(ax, 43, y - 1, 40, h, t, fc=fc, fs=9.5)
    for i in range(len(steps) - 1):
        arrow(ax, (63, ys[i] - 1), (63, ys[i + 1] - 1 + hs[i + 1]))
    box(ax, 92, 36, 30, 28,
        "FastAPI + Caddy\nHTTPS\nhilla-ai.duckdns.org\n\n/command\n/api/status\nweb page",
        fc="#e6f5e6", ec=GOOD, fs=10)
    arrow(ax, (86, 19.5), (92, 44))
    box(ax, 128, 52, 30, 17, "ESP32\npolls every 14 min\nverifies TLS certificate\nlocal safety caps",
        fc="#fef1d0", ec=WARN, fs=9.5)
    box(ax, 128, 32, 30, 10, "Relays (pins 26, 27)", fs=10)
    box(ax, 128, 12, 30, 14, "Classic-control\ncleaning system + pump", fs=10)
    arrow(ax, (128, 58), (122, 52))
    arrow(ax, (143, 52), (143, 42))
    arrow(ax, (143, 32), (143, 26))
    box(ax, 92, 8, 30, 14, "Weekly self-retraining\n(Fri 02:00): new model kept\nonly if better on last 90 days",
        fs=8.5)
    box(ax, 92, 70, 30, 7, "Daily backup 03:50 -> GitHub", fs=8.5)
    arrow(ax, (92, 14), (86, 14), color=MID)
    arrow(ax, (86, 72), (92, 73), color=MID)
    save(fig, "fig01_architecture.png")


# ---------- fig02 ----------
def fig02():
    fig, ax = blank((12, 16.8), (0, 120), (-10, 160))
    ax.text(60, 157, "decision.step() - run once per hour", ha="center", fontsize=14, fontweight="bold")
    qs = [
        ("Raining now?\n(forecast >= 0.1 mm)", "WAIT\n(mark rain pending)"),
        ("Dust storm?\n(PM10 >= 200 or airport strong dust <= 2 km for 2 h;\nends when PM10 < 100)",
         "WAIT\n(mark dust pending)"),
        ("Light airport dust (haze)?", "WAIT / IDLE\n(no new pending)"),
        ("Anything pending?", None),
        ("Minimum wait passed?\n(1 h after rain, 3 h after dust)", "WAIT"),
        ("Daily cap (2/day) or\n< 6 h since last clean?", "WAIT"),
        ("AI says next 6 h safe?\n(P(rain) < 0.275 and P(dust) < 0.321)\nOR dirty >= 48 h", "WAIT"),
    ]
    right_lab = ["yes", "yes", "yes", "no", "no", "yes", "no"]
    down_lab = ["no", "no", "no", "yes", "yes", "no", "yes"]
    cx, w, h = 42, 62, 14
    step = 20.5
    ys = [148 - i * step - h for i in range(len(qs))]
    rx = 84
    for i, (q, res) in enumerate(qs):
        y = ys[i]
        box(ax, cx - w / 2, y, w, h, q, fc="#e8f0fb", ec=RAIN, fs=9.5)
        if res is None:
            box(ax, rx, y + 2, 30, 10, "IDLE", fc="#eceae6", ec=MID, fs=10, bold=True)
        else:
            box(ax, rx, y + 2, 30, 10, res, fc="#fef1d0", ec=WARN, fs=9.5, bold=True)
        arrow(ax, (cx + w / 2, y + h / 2), (rx, y + h / 2))
        ax.text((cx + w / 2 + rx) / 2, y + h / 2 + 2.2, right_lab[i], ha="center",
                fontsize=9, fontweight="bold")
        if i < len(qs) - 1:
            arrow(ax, (cx, y), (cx, ys[i + 1] + h))
            ax.text(cx + 2, y - (step - h) / 2, down_lab[i], fontsize=9, fontweight="bold", va="center")
    y = ys[-1]
    yc = y - 17
    arrow(ax, (cx, y), (cx, yc + 11))
    ax.text(cx + 2, y - 3, "yes", fontsize=9, fontweight="bold", va="center")
    box(ax, cx - 22, yc, 44, 11, "CLEAN\n(pump on, max 30 min)", fc="#e6f5e6", ec=GOOD, fs=10.5, bold=True)
    save(fig, "fig02_decision_flow.png")


# ---------- fig14 ----------
def fig14():
    files = [("Base (29 features)", "model_comparison.csv"),
             ("Extended (51)", "model_comparison_extended_v1.csv"),
             ("+Airports (58)", "model_comparison_extended.csv")]
    dfs = [(l, pd.read_csv(ROOT / "reports" / f)) for l, f in files]
    algos = [("RandomForest", "Random Forest", RAIN), ("GradientBoosting", "Gradient Boosting", MID),
             ("XGBoost", "XGBoost", DUST)]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), sharey=True)
    bw = 0.25
    for ax, tgt, base, title in zip(axes, ["rain", "dust"], ["OpenMeteoForecast", "Persistence"],
                                    ["Rain (next 6 h)", "Dust (next 6 h)"]):
        for j, (key, lab, col) in enumerate(algos):
            for r, (_, df) in enumerate(dfs):
                v = float(df[(df.target == tgt) & (df.method == key)].f1.iloc[0])
                x = r + (j - 1) * bw
                ax.bar(x, v, bw * 0.92, color=col, label=lab if r == 0 else None)
                ax.text(x, v + 0.012, f"{v:.2f}", ha="center", fontsize=8.5,
                        bbox=dict(fc="white", ec="none", pad=0.8))
        bname = "Open-Meteo forecast" if tgt == "rain" else "Persistence"
        for r, (_, df) in enumerate(dfs):
            b = float(df[(df.target == tgt) & (df.method == base)].f1.iloc[0])
            ax.plot([r - 0.42, r + 0.42], [b, b], ls="--", color=DARK, lw=1.4,
                    label=f"No-AI baseline: {bname}" if r == 0 else None)
        ax.set_xticks(range(3))
        ax.set_xticklabels([l for l, _ in dfs])
        ax.set_title(title)
        ax.set_ylim(0, 1.0)
        ax.grid(axis="x", visible=False)
        ax.legend(loc="upper center", fontsize=8.5, frameon=False, ncol=2)
    axes[0].set_ylabel("Test F1 score")
    fig.suptitle("Test F1 of three algorithms across the three feature rounds", fontsize=12)
    fig.tight_layout()
    save(fig, "fig14_algorithms_f1.png")


# ---------- fig18 ----------
def fig18():
    fig, ax = plt.subplots(figsize=(7, 5))
    data = {"Rain": (0.552, 0.566), "Dust": (0.630, 0.680)}
    bw = 0.34
    for i, (k, (a, b)) in enumerate(data.items()):
        ax.bar(i - bw / 2, a, bw * 0.95, color=MID, label="Current model" if i == 0 else None)
        ax.bar(i + bw / 2, b, bw * 0.95, color=GOOD,
               label="Candidate (retrained with newer data)" if i == 0 else None)
        ax.text(i - bw / 2, a + 0.01, f"{a:.3f}", ha="center")
        ax.text(i + bw / 2, b + 0.01, f"{b:.3f}", ha="center")
        ax.text(i, max(a, b) + 0.07, f"+{b - a:.3f}", ha="center", fontsize=12,
                fontweight="bold", color=GOOD)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Rain model", "Dust model"])
    ax.set_ylim(0, 0.88)
    ax.set_ylabel("Average precision (last 90 days)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), frameon=False, fontsize=9)
    ax.set_title("Weekly self-retraining: current vs candidate model\n"
                 "Holdout 2026-07-28 to 2026-10-26 (server dry-run)", fontsize=12)
    fig.text(0.5, -0.14, "New model is adopted only if it is not worse", ha="center",
             fontsize=10, style="italic")
    save(fig, "fig18_self_learning.png")


# ---------- fig19 ----------
def fig19():
    with urllib.request.urlopen(LOG_URL, timeout=60) as r:
        df = pd.read_csv(io.StringIO(r.read().decode("utf-8")))
    df["t"] = pd.to_datetime(df.command_id).dt.tz_localize(None)
    df = df[df.t >= "2026-10-29"].reset_index(drop=True)
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True,
                             gridspec_kw={"height_ratios": [3, 2, 1.3], "hspace": 0.12})
    a1, a2, a3 = axes
    a1.plot(df.t, df.p_rain * 100, color=RAIN, lw=1.6, marker="o", ms=3, label="P(rain next 6 h)")
    a1.plot(df.t, df.p_dust * 100, color=DUST, lw=1.6, marker="o", ms=3, label="P(dust next 6 h)")
    a1.axhline(27.5, color=RAIN, ls="--", lw=1)
    a1.axhline(32.1, color=DUST, ls="--", lw=1)
    a1.text(1.005, 27.5, "27.5%", color=RAIN, transform=a1.get_yaxis_transform(), va="top", fontsize=8.5)
    a1.text(1.005, 32.1, "32.1%", color=DUST, transform=a1.get_yaxis_transform(), va="bottom", fontsize=8.5)
    a1.set_ylim(-3, 95)
    a1.set_ylabel("Probability (%)")
    a1.legend(loc="upper right", frameon=False, ncol=2)
    a1.set_title("Live field operation (server decision log)", fontsize=12)
    a2.plot(df.t, df.pm10, color=DARK, lw=1.5, marker="o", ms=3)
    a2.set_ylabel("PM10 (µg/m³)")
    style = {"clean": (GOOD, "^", 1), "wait": (WARN, "s", 0), "idle": (MID, "o", -1)}
    for act, (c, m, y) in style.items():
        d = df[df.action == act]
        a3.scatter(d.t, [y] * len(d), color=c, marker=m, s=45, label=act, zorder=3)
    a3.set_yticks([])
    a3.set_ylim(-1.8, 2.0)
    a3.set_ylabel("Decision")
    a3.grid(axis="y", visible=False)
    a3.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=9)
    storm = df[df.reason == "dust storm"]
    if len(storm):
        t0 = storm.t.iloc[0]
        a1.annotate("Dust storm\n2026-10-29", (t0, storm.p_dust.iloc[0] * 100),
                    xytext=(t0 + pd.Timedelta(hours=10), 75), fontsize=9, color=DUST,
                    arrowprops=dict(arrowstyle="->", color=DUST))
    rain_t = pd.Timestamp("2026-11-01 02:00")
    r = df[df.t == rain_t]
    if len(r):
        a1.annotate("Rain\n2026-11-01", (rain_t, r.p_rain.iloc[0] * 100),
                    xytext=(rain_t - pd.Timedelta(hours=26), 80), fontsize=9, color=RAIN,
                    arrowprops=dict(arrowstyle="->", color=RAIN))
    for _, row in df[df.action == "clean"].iterrows():
        a3.annotate("CLEAN", (row.t, 1), xytext=(row.t, 1.4), ha="center",
                    fontsize=8.5, color=GOOD, fontweight="bold")
    a3.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12]))
    a3.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d\n%H:%M"))
    a3.set_xlim(df.t.min() - pd.Timedelta(hours=3), df.t.max() + pd.Timedelta(hours=3))
    a3.set_xlabel("Local time (UTC+3)")
    save(fig, "fig19_live_operation.png")


# ---------- fig20 / fig21 ----------
def screenshot(scheme, name):
    for budget in (10000, 20000, 30000):
        if _shoot(scheme, name, budget):
            return
    print("WARNING: page may not have loaded fully:", name)


def _shoot(scheme, name, budget):
    tmp = Path(tempfile.mkdtemp())
    html = tmp / "p.html"
    html.write_text(f'<html><body style="margin:0;padding:10px;width:410px;background:#fff">'
                    f'<iframe src="{PAGE_URL}" width="390" height="3800" style="border:0"></iframe>'
                    f'</body></html>', encoding="utf-8")
    png = tmp / "shot.png"
    args = ["--headless", f"--user-data-dir={tmp / 'prof'}", "--hide-scrollbars",
            f"--blink-settings=preferredColorScheme={scheme}", "--window-size=420,3900",
            f"--virtual-time-budget={budget}", f"--screenshot={png}", html.as_uri()]
    arglist = ",".join("'" + x + "'" for x in args)
    # Start-Process -Wait is needed: calling Edge directly returns before it writes the file
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Start-Process -FilePath '{EDGE}' -ArgumentList {arglist} -Wait"],
                   check=False, timeout=180)
    img = mpimg.imread(png)
    crop = img[10:10 + 3800, 10:10 + 390, :3]
    # trim the empty rows at the bottom (same colour as the last row)
    bg = crop[-1, 0]
    diff = (abs(crop - bg).sum(axis=2) > 0.02).any(axis=1)
    last = diff.nonzero()[0].max() if diff.any() else crop.shape[0] - 1
    crop = crop[: min(crop.shape[0], last + 25)]
    mpimg.imsave(OUT / name, crop)
    print("wrote", name, crop.shape)
    return crop.shape[0] > 1500


def readme():
    lines = """fig01_architecture.png - System architecture: data sources, VPS server, API, ESP32 and cleaning system.
fig02_decision_flow.png - Flowchart of the hourly decision.step() rules.
fig03_events_per_month.png - Number of rain events and dust storms per month.
fig04_storm_example.png - Example dust storm: PM10 curve with start/end thresholds.
fig05_delay_tradeoff.png - Trade-off between waiting time after an event and the cleaning outcome.
fig06_pr_rain_base.png - Precision-recall curves for rain, base model (29 features).
fig07_pr_dust_base.png - Precision-recall curves for dust, base model (29 features).
fig08_importance_rain_base.png - Feature importance for rain, base model.
fig09_importance_dust_base.png - Feature importance for dust, base model.
fig10_pr_rain_final.png - Precision-recall curves for rain, final model (58 features).
fig11_pr_dust_final.png - Precision-recall curves for dust, final model (58 features).
fig12_importance_rain_final.png - Feature importance for rain, final model.
fig13_importance_dust_final.png - Feature importance for dust, final model.
fig14_algorithms_f1.png - Test F1 of RandomForest, GradientBoosting, XGBoost over three feature rounds, with no-AI baselines.
fig15_metar_vs_cams.png - Airport (METAR) dust reports compared with CAMS PM10 forecasts.
fig16_strategy_comparison.png - Simulated comparison of cleaning strategies.
fig17_decision_timeline.png - Simulated decision timeline over a period.
fig18_self_learning.png - Weekly retraining: current vs candidate model average precision on the last 90 days.
fig19_live_operation.png - Live field operation from the server decision log: probabilities, PM10 and decisions.
fig20_page_light.png - Screenshot of the live web page at phone width, light theme.
fig21_page_dark.png - Screenshot of the live web page at phone width, dark theme.
Data: Open-Meteo.com (CC BY 4.0).
"""
    (OUT / "README.txt").write_text(lines, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-net", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for dst, src in COPIES.items():
        shutil.copyfile(CHARTS / src, OUT / dst)
        print("copied", dst)
    fig01()
    fig02()
    fig14()
    fig18()
    if not a.skip_net:
        fig19()
        screenshot(1, "fig20_page_light.png")
        screenshot(0, "fig21_page_dark.png")
    readme()


if __name__ == "__main__":
    main()
