"""
server/app.py
Stateless FastAPI window for the ESP32: serves the latest output/command.json from the GitHub repo.
Env vars: COMMAND_URL (raw URL of output/command.json), LOG_URL (raw URL of output/decision_log.csv).
A value starting with "file:" is read from the local disk (for offline tests).
/api/status feeds the web page (static/index.html). forecast.json: next to the command file, or FORECAST_URL.
The ESP32 last-seen time is kept in esp32_seen.json next to the command file (no IP addresses stored).
Confirmations: the ESP32 sends POST /ack {"command_id": ...} (header X-Key = env ACK_KEY) when it really starts a
clean, and repeats its last executed id in the X-Last-Id header of every GET /command. The ids are kept in
esp32_ack.json next to the command file; live_decision.py reads it, and the page shows only a confirmed last clean.
Without ACK_KEY on the server, /ack answers 503 and nothing is stored.
Data: Open-Meteo.com (CC BY 4.0); METAR: aviationweather.gov.
"""
import csv
import hmac
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
STATS = {"useful_cleans_pct": 78.7, "useful_cleans_rules_pct": 59.0, "fewer_washes_pct": 38, "wasted_less_vs_rule_pct": 27,
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


def demo():
    # a manual test command (deploy/demo_clean.py) wins while it is still valid; it never touches the AI state
    url = os.environ.get("COMMAND_URL", "")
    p = Path(url[5:]).with_name("demo_command.json") if url.startswith("file:") else None
    d = read_json(p) if p and p.exists() else None
    try:
        return d if d and datetime.now(timezone.utc) < datetime.fromisoformat(d["valid_until"]) else None
    except Exception:
        return None


def latest():
    # returns the command dict, or None if it cannot be trusted
    d = demo()
    if d:
        return d
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


def seen_path(name="esp32_seen.json"):
    # next to the command file; None when the command comes from http(s)
    url = os.environ.get("COMMAND_URL", "")
    return Path(url[5:]).with_name(name) if url.startswith("file:") else None


def write_atomic(path, obj):
    # temp file + os.replace: a crash never leaves a half-written file
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj))
    os.replace(tmp, path)


def record_seen():
    p = seen_path()
    if not p:
        return
    try:
        now = datetime.now(timezone(timedelta(hours=3)))
        day = now.strftime("%Y-%m-%d")
        old = read_json(p) or {}
        n = old.get("count_today", 0) + 1 if old.get("day") == day else 1
        write_atomic(p, {"last_seen": now.isoformat(timespec="seconds"), "count_today": n, "day": day})
    except Exception:
        pass


ACK_KEEP = 50


def record_ack(cid, key):
    """The ESP32 says it really started command `cid`. Kept in esp32_ack.json next to the command file
    (read by live_decision.py). Returns an HTTP status: 503 = no ACK_KEY set on this server (switched off),
    403 = wrong key, 400 = bad id, 200 = saved."""
    want = os.environ.get("ACK_KEY", "")
    p = seen_path("esp32_ack.json")
    if not want or not p:
        return 503
    if not hmac.compare_digest((key or "").encode(), want.encode()):
        return 403
    if not isinstance(cid, str) or len(cid) > 64:
        return 400
    try:
        old = read_json(p) or {}
        ids = [x for x in old.get("ids", []) if isinstance(x, str)]
        if cid and cid not in ids:
            ids.append(cid)
        now = datetime.now(timezone(timedelta(hours=3)))
        write_atomic(p, {"ids": ids[-ACK_KEEP:], "updated": now.isoformat(timespec="seconds")})
    except Exception:
        return 503
    return 200


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


@app.get("/command")
def command(request: Request):
    if "ESP32" in request.headers.get("user-agent", ""):
        record_seen()
        if "x-last-id" in request.headers:           # backup in case an ack POST got lost
            record_ack(request.headers["x-last-id"], request.headers.get("x-key"))
    return JSONResponse(latest() or SAFE, headers=NO_STORE)


@app.post("/ack")
async def ack(request: Request):
    key = request.headers.get("x-key")
    code = record_ack("", key)                      # checks 503 / 403 first, without storing anything new
    if code == 200:
        try:
            cid = (await request.json())["command_id"]
        except Exception:
            cid = None
        code = record_ack(cid, key) if isinstance(cid, str) and cid else 400
    return JSONResponse({"ok": code == 200}, status_code=code, headers=NO_STORE)


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
    ap = seen_path("esp32_ack.json")
    acks = read_json(ap) if ap and ap.exists() else None
    if acks is not None:                            # confirmations in use: only a confirmed clean counts
        clean = [c for c in clean if c in acks.get("ids", [])]
    p = seen_path()
    return JSONResponse({"command": latest() or SAFE, "forecast": fc, "log": rows[-48:],
                         "last_clean": clean[-1] if clean else None,
                         "esp32": read_json(p) if p else None, "stats": STATS}, headers=NO_STORE)


@app.get("/")
def page():
    return FileResponse(Path(__file__).parent / "static" / "index.html")
