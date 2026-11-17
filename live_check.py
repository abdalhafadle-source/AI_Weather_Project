#!/usr/bin/env python3
"""
live_check.py
Score what the live system predicted (p_rain, p_dust in output/decision_log.csv) against what really happened in the next 6 hours.

Usage:
    python live_check.py                      # writes reports/live_performance.md
    python live_check.py --out reports/x.md

Truth is built straight from the raw files (no prepare_data), same definition as train_models.targets:
y_rain = max ERA5 precipitation in t+1..t+6 >= RAIN_MM; y_dust = max PM10 in t+1..t+6 >= DUST_PM10 or strong airport dust.
All raw times are local Baghdad time (download timezone Asia/Baghdad); decision_log command_id is +03:00, so the offset is dropped.
Hours whose 6-hour future is not fully in the raw files yet (ERA5 arrives days late) are left out and counted.
Thresholds come from models/extended. Data: Open-Meteo.com (CC BY 4.0), aviationweather.gov.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss

from train_models import DUST_PM10, RAIN_MM, H

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROMOTED = pd.Timestamp("2026-11-06")    # day the current model was adopted (reports/retrain_log.csv)


def fwd(x, op):
    return getattr(x.rolling(H), op)().shift(-H)


def score(y, p, th):
    n, pos = len(y), int(y.sum())
    if n == 0:
        return dict(n=0, pos=0, prec="-", rec="-", f1="-", ap="لا توجد ساعات", brier="-")
    pred = p >= th
    tp = int((pred & (y == 1)).sum())
    prec = tp / pred.sum() if pred.sum() else 0.0
    rec = tp / pos if pos else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if pos and prec + rec else 0.0
    ap = f"{average_precision_score(y, p):.3f}" if pos else "لا توجد حالات موجبة — لا يمكن القياس"
    f = lambda v: "-" if np.isnan(v) else f"{v:.3f}"
    return dict(n=n, pos=pos, prec=f(prec), rec=f(rec), f1=f(f1), ap=ap, brier=f"{brier_score_loss(y, p):.4f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="output/decision_log.csv")
    ap.add_argument("--models", default="models/extended")
    ap.add_argument("--out", default="reports/live_performance.md")
    args = ap.parse_args()

    log = pd.read_csv(args.log)
    log["time"] = pd.to_datetime(log["command_id"].str[:19])           # local time, +03:00 dropped
    log = log.drop_duplicates("time").set_index("time").sort_index()

    era = pd.read_csv("data/raw_hilla/era5_weather.csv", parse_dates=["time"]).set_index("time")["precipitation"]
    aq = pd.read_csv("data/raw_hilla/air_quality.csv", parse_dates=["time"]).set_index("time")["pm10"]
    me = pd.read_csv("data/raw_hilla_extra/metar.csv", parse_dates=["time"]).set_index("time")["strong_dust"]
    grid = pd.date_range(min(era.index.min(), aq.index.min()), max(era.index.max(), aq.index.max(), me.index.max()), freq="h")
    era, aq, me = (s.reindex(grid) for s in (era, aq, me))             # missing hours become NaN
    mr, mp, ms = fwd(era, "max"), fwd(aq, "max"), fwd(me, "max")       # NaN if any of the 6 hours is missing
    y_rain = (mr >= RAIN_MM).astype(float).where(mr.notna())
    y_dust = ((mp >= DUST_PM10) | (ms >= 1)).astype(float).where(mp.notna() & ms.notna())

    d = log[["p_rain", "p_dust"]].join(pd.DataFrame({"y_rain": y_rain, "y_dust": y_dust}))
    total = len(d)
    th = {k: joblib.load(Path(args.models) / f"{k}_model.joblib")["threshold"] for k in ("rain", "dust")}

    L = [f"# أداء النظام الحي: ما توقعه مقابل ما حدث بعد 6 ساعات",
         "",
         f"- سجل القرارات: {total} ساعة، من {d.index.min()} إلى {d.index.max()} (توقيت بغداد).",
         f"- العتبات من `{args.models}`: مطر {th['rain']:.3f}، غبار {th['dust']:.3f}.",
         f"- النموذج الحالي اعتُمد مرة واحدة في 2026-11-06 (reports/retrain_log.csv)؛ قسّمنا النتائج قبل/بعد هذا التاريخ.",
         "- الحقيقة: مطر ERA5 >= %s ملم، أو PM10 >= %d، أو غبار قوي في المطار، خلال الساعات t+1..t+6." % (RAIN_MM, DUST_PM10),
         ""]
    print(f"decision log: {total} hours")
    for tgt in ("rain", "dust"):
        ok = d[f"y_{tgt}"].notna() & d[f"p_{tgt}"].notna()
        L += [f"## {'المطر' if tgt == 'rain' else 'الغبار'} (rain)" if tgt == "rain" else "## الغبار (dust)",
              f"ساعات استُبعدت لأن حقيقتها لم تكتمل بعد: {int((~ok).sum())} من {total}.", "",
              "| الفترة | ساعات | موجبة | precision | recall | F1 | AP | Brier |", "|---|---|---|---|---|---|---|---|"]
        parts = (("الكل", ok), ("قبل 2026-11-06", ok & (d.index < PROMOTED)), ("من 2026-11-06", ok & (d.index >= PROMOTED)))
        for name, m in parts:
            r = score(d.loc[m, f"y_{tgt}"].to_numpy(), d.loc[m, f"p_{tgt}"].to_numpy(), th[tgt])
            L.append(f"| {name} | {r['n']} | {r['pos']} | {r['prec']} | {r['rec']} | {r['f1']} | {r['ap']} | {r['brier']} |")
            print(f"{tgt:5} {name:<16} n={r['n']:>4} pos={r['pos']:>3} P={r['prec']} R={r['rec']} F1={r['f1']} AP={r['ap']} Brier={r['brier']}")
        L.append("")
    L += ["## كيف تقرأ الجدول",
          "- precision: من كل مرة قال فيها النموذج «خطر»، كم مرة صدق. recall: من كل الأحداث الحقيقية، كم التقط.",
          "- Brier: كلما اقترب من الصفر كانت الاحتمالات أدق. AP: جودة الترتيب بغض النظر عن العتبة.",
          "- عدد الحالات الموجبة صغير في فترة قصيرة، فالأرقام تقريبية ولا تُحكم عليها إلا بعد أسابيع أكثر.",
          "",
          "المصدر: Open-Meteo.com (CC BY 4.0) وaviationweather.gov."]
    Path(args.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"report saved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
