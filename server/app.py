"""
server/app.py
Stateless FastAPI window for the ESP32: serves the latest output/command.json from the GitHub repo.
Env vars: COMMAND_URL (raw URL of output/command.json), LOG_URL (raw URL of output/decision_log.csv).
A value starting with "file:" is read from the local disk (for offline tests).
/api/status feeds the web page (static/index.html). forecast.json: next to the command file, or FORECAST_URL.
The ESP32 last-seen time is kept in esp32_seen.json next to the command file (no IP addresses stored).
Data: Open-Meteo.com (CC BY 4.0); METAR: aviationweather.gov.
"""
import csv
import io
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI()
CACHE_S, STALE_MIN = 60, 60
SAFE = {"action": "wait", "pump": False, "max_duration_min": 30,
        "reason": "no fresh command (safety)", "command_id": None}
NO_STORE = {"Cache-Control": "no-store"}
STATS = {"useful_cleans_pct": 78.4, "useful_cleans_rules_pct": 58.7, "fewer_washes_pct": 44, "wasted_less_vs_rule_pct": 27,
         "rain_detect_ai_pct": 71, "rain_detect_forecast_pct": 57, "algorithm": "Random Forest", "features": 58,
         "years_of_data": 4.8, "storms_missed_by_cams_pct": 77}
_cache = {}


def fetch_text(url):
    # cached 60 s in memory (lost on restart: fine, nothing important is kept)
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    if url.startswith("file:"):
        txt = open(url[5:], encoding="utf-8").read()
    else:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        txt = r.text
    _cache[url] = (time.time(), txt)
    return txt


def latest():
    # returns the command dict, or None if it cannot be trusted
    try:
        cmd = json.loads(fetch_text(os.environ["COMMAND_URL"]))
        until = datetime.fromisoformat(cmd["valid_until"])
        if until.tzinfo is None:
            return None
        late = datetime.now(timezone.utc) - until
        if late > timedelta(minutes=STALE_MIN):
            return None
        if late > timedelta(0) and cmd.get("action") == "clean":
            return None  # an expired "clean" is never served (the ESP32 may have no reliable clock)
        return cmd if isinstance(cmd, dict) and "action" in cmd else None
    except Exception:
        return None


def seen_path():
    # next to the command file; None when the command comes from http(s)
    url = os.environ.get("COMMAND_URL", "")
    return Path(url[5:]).with_name("esp32_seen.json") if url.startswith("file:") else None


def record_seen():
    p = seen_path()
    if not p:
        return
    try:
        now = datetime.now(timezone(timedelta(hours=3)))
        day = now.strftime("%Y-%m-%d")
        old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        n = old.get("count_today", 0) + 1 if old.get("day") == day else 1
        p.write_text(json.dumps({"last_seen": now.isoformat(timespec="seconds"), "count_today": n, "day": day}), encoding="utf-8")
    except Exception:
        pass


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


@app.get("/command")
def command(request: Request):
    if "ESP32" in request.headers.get("user-agent", ""):
        record_seen()
    return JSONResponse(latest() or SAFE, headers=NO_STORE)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def api_status():
    url = os.environ.get("COMMAND_URL", "")
    fc, rows = None, []
    try:
        furl = os.environ.get("FORECAST_URL") or (str(Path(url[5:]).with_name("forecast.json")) if url.startswith("file:") else "")
        fc = json.loads(fetch_text(furl if furl.startswith("http") else "file:" + furl)) if furl else None
    except Exception:
        pass
    try:
        rows = list(csv.DictReader(io.StringIO(fetch_text(os.environ["LOG_URL"]))))
    except Exception:
        pass
    clean = [r["command_id"] for r in rows if r.get("action") == "clean"]
    p = seen_path()
    return JSONResponse({"command": latest() or SAFE, "forecast": fc, "log": rows[-48:],
                         "last_clean": clean[-1] if clean else None,
                         "esp32": read_json(p) if p else None, "stats": STATS}, headers=NO_STORE)


@app.get("/")
def page():
    return FileResponse(Path(__file__).parent / "static" / "index.html")
