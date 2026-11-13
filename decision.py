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
Heat rule: too_hot() (May-Sep 10:00-15:59, or forecast >= 40 C); the caller passes it as block="too hot".
block="reason" (caller forbids a clean this hour, e.g. no airport data) turns the final clean, even the forced
one, into a wait with that reason; pending is kept.
settle(state, acked, t) checks the last issued clean (state["issued"], set by the caller) against the command ids
the ESP32 confirmed; after ACK_GRACE_H without confirmation it rolls the state back to just before that clean.
Used by simulate_decisions.py (and later by the live server). No pandas needed.

Data: Open-Meteo.com (CC BY 4.0) - cite it in the report.
"""
from __future__ import annotations

import os
import sys
import tempfile
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
ACK_GRACE_H = 2      # an issued clean the ESP32 has not confirmed after this long never happened
HOT_MONTHS = (5, 6, 7, 8, 9)   # May .. September
HOT_HOURS = range(10, 16)      # 10:00 .. 15:59
HOT_TEMP_C = 40                # forecast air temperature (2 m)


def too_hot(t, temp_c=None):
    """Cold water on sun-heated glass can crack it: no cleaning at summer midday (May-Sep, 10:00-15:59), nor
    when the forecast air temperature is >= 40 C. temp_c None or NaN -> the calendar rule alone."""
    return (t.month in HOT_MONTHS and t.hour in HOT_HOURS) or (temp_c is not None and temp_c >= HOT_TEMP_C)


def write_atomic(path, text):
    """Write text to path via a temp file + os.replace: a crash or power cut never leaves a half-written file."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def new_state():
    # last_end = event end used by the last clean (only for reporting "dirty time")
    return dict(storm=False, raining=False, pending=set(), event_end=None, cleans=[], last_end=None,
                pending_since=None)


def dump_state(s):
    """state -> JSON-ready dict (sets and datetimes become lists and ISO strings)."""
    out = {}
    for k, v in s.items():
        if k == "pending":
            out[k] = sorted(v)
        elif k == "cleans":
            out[k] = [c.isoformat() for c in v]
        elif k == "issued":
            out[k] = {"id": v["id"], "t": v["t"].isoformat(), "undo": dump_state(v["undo"])}
        else:
            out[k] = v.isoformat() if isinstance(v, datetime) else v
    return out


def load_state(js):
    """inverse of dump_state."""
    out = {}
    for k, v in js.items():
        if k == "pending":
            out[k] = set(v)
        elif k == "cleans":
            out[k] = [datetime.fromisoformat(c) for c in v]
        elif k == "issued":
            out[k] = {"id": v["id"], "t": datetime.fromisoformat(v["t"]), "undo": load_state(v["undo"])}
        elif v and k in ("event_end", "last_end", "pending_since"):
            out[k] = datetime.fromisoformat(v)
        else:
            out[k] = v
    return out


def settle(state, acked, t):
    """Check the last issued clean against the command ids the ESP32 confirmed (acked: a set of ids, or None
    when confirmations are not in use yet). Returns (state, replay_from). replay_from is None, or - when the
    clean was never confirmed - the hour of that clean, with the state rolled back to just before it: the
    caller replays from that hour with can_clean=False, so the clean is issued again in the first safe hour."""
    job = state.get("issued")
    if not job:
        return state, None
    if acked is None or job["id"] in acked:            # confirmations not in use yet / the ESP32 confirmed it
        del state["issued"]
        state.pop("retries", None)
        return state, None
    if t - job["t"] < timedelta(hours=ACK_GRACE_H):    # still time for the confirmation to arrive
        return state, None
    undo = job["undo"]                                 # never happened: back to the state just before it
    undo["retries"] = undo.get("retries", 0) + 1
    return undo, job["t"]


def step(state, t, rain_mm, pm10, safe, min_wait=None, dust_obs=False, haze=False, can_clean=True, block=None):
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
    if block:                                  # the caller forbids a clean this hour (e.g. no airport data)
        return "wait", block
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
    # block: rain at 2,3, blocked only at hour 4 -> wait, still pending, clean at 5
    s = new_state()
    acts = [step(s, datetime(2025, 3, 1) + i * HOUR, 1 if i in (2, 3) else 0, 20, True,
                 block="no airport data" if i == 4 else None) for i in range(6)]
    assert acts[4] == ("wait", "no airport data") and acts[5][0] == "clean" and s["cleans"] == [datetime(2025, 3, 1, 5)], acts
    s = new_state()
    for i in range(5):
        a = step(s, datetime(2025, 3, 1) + i * HOUR, 1 if i in (2, 3) else 0, 20, True, block="no airport data" if i == 4 else None)
    assert a == ("wait", "no airport data") and s["pending"] == {"rain"}, (a, s)
    # block also stops the forced MAX_WAIT clean: wait at hour MAX_WAIT_H, clean at MAX_WAIT_H + 1
    s, acts = new_state(), []
    for i in range(MAX_WAIT_H + 3):
        acts.append(step(s, datetime(2025, 3, 1) + i * HOUR, 1 if i == 0 else 0, 20, False,
                         block="no airport data" if i == MAX_WAIT_H else None))
    assert acts[MAX_WAIT_H] == ("wait", "no airport data") and [i for i, a in enumerate(acts) if a[0] == "clean"] == [MAX_WAIT_H + 1], acts
    # too_hot
    nan = float("nan")
    assert too_hot(datetime(2025, 7, 1, 12)) and not too_hot(datetime(2025, 7, 1, 17), 38)
    assert too_hot(datetime(2025, 7, 1, 17), 41) and not too_hot(datetime(2025, 1, 1, 12), 20)
    assert not too_hot(datetime(2025, 7, 1, 9), nan) and too_hot(datetime(2025, 7, 1, 12), None)
    # rain at 9,10 on a 39 C July day: waits 11..15 (too hot), single clean at 16, pending kept meanwhile
    s, acts = new_state(), []
    for i in range(20):
        t = datetime(2025, 7, 1) + i * HOUR
        acts.append(step(s, t, 1 if i in (9, 10) else 0, 20, True, block="too hot" if too_hot(t, 39) else None))
        if 11 <= i <= 15:
            assert s["pending"] == {"rain"}
    assert all(a == ("wait", "too hot") for a in acts[11:16]), acts
    assert [i for i, a in enumerate(acts) if a[0] == "clean"] == [16], acts
    # write_atomic: second write replaces the first, no .tmp left behind
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, "x.json")
        write_atomic(f, "a")
        write_atomic(f, "b")
        assert open(f, encoding="utf-8").read() == "b" and os.listdir(td) == ["x.json"], os.listdir(td)
    # settle: rain 2,3 -> clean at 4, issued but maybe never executed
    import copy
    import json
    T0 = datetime(2025, 3, 1)
    s = new_state()
    for i in range(4):
        step(s, T0 + i * HOUR, 1 if i in (2, 3) else 0, 20, True)
    before = copy.deepcopy(s)
    assert step(s, T0 + 4 * HOUR, 0, 20, True)[0] == "clean"
    s["issued"] = {"id": "c4", "t": T0 + 4 * HOUR, "undo": before}
    assert load_state(json.loads(json.dumps(dump_state(s)))) == s
    old = dump_state(new_state())                      # an old state file (no issued, no retries) still loads
    assert "issued" not in load_state(old) and "retries" not in load_state(old)
    a, redo = settle(copy.deepcopy(s), {"c4"}, T0 + 5 * HOUR)
    assert "issued" not in a and redo is None and a["cleans"] == [T0 + 4 * HOUR], a
    a, redo = settle(copy.deepcopy(s), set(), T0 + 5 * HOUR)
    assert "issued" in a and redo is None
    a, redo = settle(copy.deepcopy(s), set(), T0 + 6 * HOUR)
    assert a["pending"] == {"rain"} and a["cleans"] == [] and a["pending_since"] == T0 + 2 * HOUR, a
    assert a["retries"] == 1 and "issued" not in a and redo == T0 + 4 * HOUR, (a, redo)
    acts = [step(a, T0 + i * HOUR, 0, 20, True, can_clean=i == 6)[0] for i in range(4, 7)]
    assert acts == ["wait", "wait", "clean"] and a["cleans"] == [T0 + 6 * HOUR], (acts, a)
    a, redo = settle(copy.deepcopy(s), {"demo-20261114T100000"}, T0 + 6 * HOUR)
    assert a["cleans"] == [] and redo == T0 + 4 * HOUR
    a, redo = settle(copy.deepcopy(s), None, T0 + 9 * HOUR)
    assert "issued" not in a and redo is None and a["cleans"] == [T0 + 4 * HOUR]
    print("decision.py self-test passed")
