"""
server/app.py
Stateless FastAPI window for the ESP32: serves the latest output/command.json from the GitHub repo.
Env vars: COMMAND_URL (raw URL of output/command.json), LOG_URL (raw URL of output/decision_log.csv).
A value starting with "file:" is read from the local disk (for offline tests).
Data: Open-Meteo.com (CC BY 4.0); METAR: aviationweather.gov.
"""
import csv
import io
import json
import os
import time
from datetime import datetime, timedelta, timezone
from html import escape

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI()
CACHE_S, STALE_MIN = 60, 60
SAFE = {"action": "wait", "pump": False, "max_duration_min": 30,
        "reason": "no fresh command (safety)", "command_id": None}
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


@app.get("/command")
def command():
    return JSONResponse(latest() or SAFE, headers={"Cache-Control": "no-store"})


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def status():
    cmd = latest()
    now = (cmd or {}).get("now", {})
    rows = []
    try:
        rows = list(csv.reader(io.StringIO(fetch_text(os.environ["LOG_URL"]))))
    except Exception:
        pass
    e = lambda v: escape("-" if v is None else str(v))
    items = [("الإجراء / Action", (cmd or SAFE)["action"]), ("السبب / Reason", (cmd or SAFE)["reason"]),
             ("احتمال المطر / p_rain", (cmd or {}).get("p_rain")), ("احتمال الغبار / p_dust", (cmd or {}).get("p_dust")),
             ("PM10", now.get("pm10")), ("غبار المطار / Airport dust", now.get("metar_strong_dust")),
             ("الرؤية كم / Visibility km", now.get("metar_min_vis_km")),
             ("آخر تحديث / generated_at", (cmd or {}).get("generated_at"))]
    info = "".join(f"<tr><th>{k}</th><td>{e(v)}</td></tr>" for k, v in items)
    log = ""
    if rows:
        log = "<h3>آخر 24 قرار / Last 24 decisions</h3><table><tr>" + "".join(f"<th>{e(c)}</th>" for c in rows[0]) + "</tr>"
        log += "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows[1:][-24:]) + "</table>"
    note = "" if cmd else "<p><b>لا يوجد أمر حديث (وضع الأمان) / no fresh command (safe mode)</b></p>"
    return (f'<!doctype html><html dir="rtl" lang="ar"><meta charset="utf-8"><title>Hilla PV cleaner</title>'
            f'<style>body{{font-family:sans-serif;margin:1em}}td,th{{border:1px solid #ccc;padding:2px 6px}}</style>'
            f'<h2>تنظيف الألواح - الحلة / Hilla PV cleaning</h2>{note}<table>{info}</table>{log}'
            f'<p><small>Data: Open-Meteo.com (CC BY 4.0); METAR: aviationweather.gov</small></p></html>')
