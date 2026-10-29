#!/usr/bin/env python3
"""
decision.py
WHEN to send "clean" to the PV-panel cleaner (ESP32 + pump). One function, step(), called once per hour.

Usage:
    python decision.py                      # runs the built-in self-test

Rules: never clean during rain or a dust storm; after rain wait >= 1 h, after a storm >= 3 h (both: 3 h);
then clean only if `safe` (the caller decides: model / forecast says next 6 h dry and PM10 < 150).
Caps: max 2 cleans per calendar day, at least 6 h between cleans.
Optional dust_obs=True (airport reports STRONG dust) also starts / prolongs a storm; haze=True (light dust
at the airport) only blocks cleaning that hour (also the forced MAX_WAIT clean).
can_clean=False (replay of a missed past hour) turns the final clean into a wait.
Used by simulate_decisions.py (and later by the live server). No pandas needed.

Data: Open-Meteo.com (CC BY 4.0) - cite it in the report.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

RAIN_NOW_MM = 0.1        # an hour with at least this much rain = raining
DUST_START = 200         # PM10 that starts a dust storm
DUST_END = 100           # storm ends when PM10 falls below this (hysteresis)
RAIN_MIN_WAIT_H = 1      # hours to wait after rain ends
DUST_MIN_WAIT_H = 3      # hours to wait after a storm ends
MAX_PER_DAY = 2          # max cleans per calendar day
MIN_GAP_H = 6            # min hours between two cleans
MAX_WAIT_H = 48          # dirty this long since the first event -> clean even if the model says not safe
HOUR = timedelta(hours=1)


def new_state():
    # last_end = event end used by the last clean (only for reporting "dirty time")
    return dict(storm=False, raining=False, pending=set(), event_end=None, cleans=[], last_end=None,
                pending_since=None)


def step(state, t, rain_mm, pm10, safe, min_wait=None, dust_obs=False, haze=False, can_clean=True):
    mw = min_wait or {"rain": RAIN_MIN_WAIT_H, "dust": DUST_MIN_WAIT_H}
    # 1. rain now
    if rain_mm >= RAIN_NOW_MM:
        state["pending_since"] = state["pending_since"] or t
        state["pending"].add("rain")
        state["event_end"], state["raining"] = None, True
        return "wait", "raining"
    # 2. dust storm with hysteresis
    # dust_obs = an airport (METAR) reports dust now: starts a storm, and keeps it going
    if pm10 >= DUST_START or dust_obs:
        state["storm"] = True
    elif state["storm"] and pm10 < DUST_END:
        state["storm"] = False
        state["event_end"] = t - HOUR
    if state["storm"]:
        state["pending_since"] = state["pending_since"] or t
        state["pending"].add("dust")
        state["event_end"] = None
        return "wait", "dust storm"
    # 2b. light dust in the air (airport): do not clean now, but it is not an event (no pending, event_end untouched)
    if haze:
        return ("wait" if state["pending"] else "idle"), "dust in air (airport)"
    # 3. rain just ended
    if state["raining"]:
        state["raining"] = False
        e = state["event_end"]
        state["event_end"] = t - HOUR if e is None else max(e, t - HOUR)
    # 4. nothing to clean
    if not state["pending"]:
        return "idle", "nothing to clean"
    # 5. minimum wait after the event
    need = max(mw[k] for k in state["pending"])
    if state["event_end"] is None or t - state["event_end"] < timedelta(hours=need):
        return "wait", f"waiting {need} h after event"
    # 6. safety caps
    if sum(c.date() == t.date() for c in state["cleans"]) >= MAX_PER_DAY:
        return "wait", "daily cap"
    if state["cleans"] and t - state["cleans"][-1] < timedelta(hours=MIN_GAP_H):
        return "wait", "min gap"
    # 7. model / forecast check, unless the panel has been dirty for MAX_WAIT_H
    forced = t - state["pending_since"] >= timedelta(hours=MAX_WAIT_H)
    if not safe and not forced:
        return "wait", "model: next 6 h not safe"
    # 8. clean (can_clean=False: replaying a past hour, a clean there never physically happened)
    if not can_clean:
        return "wait", "replay: past hour"
    kinds = "+".join(sorted(state["pending"]))
    state["cleans"].append(t)
    state["last_end"] = state["event_end"]
    state["pending"], state["event_end"], state["pending_since"] = set(), None, None
    return "clean", "after " + kinds + (f" (max wait {MAX_WAIT_H} h)" if not safe else "")


def _run(seq, safe=lambda i: True, start=datetime(2025, 3, 1, 0)):
    # seq: list of (rain_mm, pm10) per hour; returns list of (hour index, action, reason)
    s, out = new_state(), []
    for i, (r, p) in enumerate(seq):
        a, why = step(s, start + i * HOUR, r, p, safe(i))
        out.append((i, a, why))
    return out


if __name__ == "__main__":
    # rain 2 h (hours 2,3) then dry: end = 3, clean at 4
    seq = [(0, 20)] * 2 + [(1, 20)] * 2 + [(0, 20)] * 4
    acts = _run(seq)
    assert [i for i, a, _ in acts if a == "clean"] == [4], acts
    assert all(a == "wait" for i, a, _ in acts if i in (2, 3))
    # same, but not safe at hour 4 and 5 -> clean at 6
    acts = _run(seq, safe=lambda i: i >= 6)
    assert [i for i, a, _ in acts if a == "clean"] == [6]
    # dust storm hours 1..3 (pm10 250, 150, 120), ends at hour 4 (<100); end = 3, clean at 6
    seq = [(0, 20), (0, 250), (0, 150), (0, 120)] + [(0, 30)] * 8
    acts = _run(seq)
    assert [i for i, a, _ in acts if a == "clean"] == [6], acts
    assert all(a != "clean" for i, a, _ in acts if i <= 5)
    # rain + storm: the longer wait (3 h) wins
    seq = [(1, 300), (0, 300), (0, 20)] + [(0, 20)] * 6   # last wet/stormy hour = 1, clean at 4
    acts = _run(seq)
    assert [i for i, a, _ in acts if a == "clean"] == [4], acts
    # caps: rain every 5 h (hours 0,5,10,15), all on one day
    seq = []
    for _ in range(4):
        seq += [(1, 20)] + [(0, 20)] * 4          # rain, then 4 dry hours 
    s, cl = new_state(), []
    for i, (r, p) in enumerate(seq):
        if step(s, datetime(2025, 3, 1, 0) + i * HOUR, r, p, True)[0] == "clean":
            cl.append(i)
    # clean at 1; event at 5 -> blocked by min gap (4 h) -> clean at 7; event at 10 -> daily cap blocks 3rd
    assert cl == [1, 7], cl
    # fixed 5 h wait override
    s = new_state()
    r = [step(s, datetime(2025, 3, 1) + i * HOUR, *x, True, {"rain": 5, "dust": 5})[0]
         for i, x in enumerate([(1, 20)] + [(0, 20)] * 8)]
    assert r.index("clean") == 5, r
    # never safe: rain at hour 0 -> forced clean at hour MAX_WAIT_H
    acts = _run([(1, 20)] + [(0, 20)] * (MAX_WAIT_H + 5), safe=lambda i: False)
    assert [i for i, a, _ in acts if a == "clean"] == [MAX_WAIT_H], acts
    # METAR dust at hours 1..3 while pm10 stays 60: no clean during, storm ends at 4, end = 3, clean at 6
    s, acts = new_state(), []
    for i in range(12):
        acts.append(step(s, datetime(2025, 3, 1) + i * HOUR, 0, 60, True, dust_obs=i in (1, 2, 3))[0])
    assert [i for i, a in enumerate(acts) if a == "clean"] == [6], acts
    assert all(a != "clean" for a in acts[:6])
    # haze: rain at hour 0, haze at 1..3 blocks the clean (clean at 4); haze with nothing pending stays idle
    s, acts = new_state(), []
    for i in range(8):
        acts.append(step(s, datetime(2025, 3, 1) + i * HOUR, 1 if i == 0 else 0, 20, True, haze=i in (1, 2, 3)))
    assert [i for i, a in enumerate(acts) if a[0] == "clean"] == [4], acts
    assert all(a[0] == "wait" for a in acts[:4])
    s = new_state()
    assert step(s, datetime(2025, 3, 1), 0, 20, True, haze=True) == ("idle", "dust in air (airport)") and not s["pending"]
    # can_clean=False: would clean at hour 4 -> waits instead, state untouched (still pending); clean at the next hour
    s = new_state()
    acts = [step(s, datetime(2025, 3, 1) + i * HOUR, 1 if i in (2, 3) else 0, 20, True, can_clean=i != 4)
            for i in range(6)]
    assert acts[4] == ("wait", "replay: past hour") and s["cleans"] == [datetime(2025, 3, 1, 5)] and acts[5][0] == "clean", acts
    print("decision.py self-test passed")
