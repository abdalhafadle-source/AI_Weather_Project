#!/usr/bin/env python3
"""
watchdog.py
Run every 15 minutes on the server (hilla-watchdog.timer). Checks four things and sends a Telegram message
when one breaks (once), a reminder every 24 h while it stays broken, and one when it is fixed:
  esp32     output/esp32_seen.json last_seen older than 2 h (or file missing/broken)
  command   output/command.json generated_at older than 2 h (or file missing/broken)
  backup    hilla-backup.service Result is not "success", or the last commit in the backup folder is > 26 h old
  airports  now.metar_ok false or now.metar_available 0 in command.json, for 6 hours in a row

Usage:
    python deploy/watchdog.py               # check and send (needs TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)
    python deploy/watchdog.py --dry-run     # print the messages instead of sending; no token, no memory file
    python deploy/watchdog.py --test        # send one test message and exit
    python deploy/watchdog.py --self-test   # test the message logic (no files, no network)
    python deploy/watchdog.py --out output  # other output folder (default: <project>/output)

Memory file (outside the repo): ~/.hilla_watchdog.json (env WATCHDOG_STATE). Backup folder: /home/hilla/backup
(env BACKUP_DIR). Exit codes: 0 ok, 1 sending failed (memory not saved, so it is retried), 2 token/chat id missing.
Times in messages are Baghdad time (+03:00).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BAGHDAD = timezone(timedelta(hours=3))
STALE_H = 2              # esp32 / command older than this = problem
BACKUP_MAX_H = 26
REMIND_H = 24
AIRPORT_H = 6


def judge(now, facts, mem):
    """facts = {name: (bad, text, ok_text, min_hours)}, mem = {name: {"since": iso, "sent": iso|None}}.
    Returns (messages, new_mem). Pure: no files, no network."""
    msgs, new = [], {}
    for name, (bad, text, ok_text, min_h) in facts.items():
        m = mem.get(name)
        if not bad:
            if m and m.get("sent"):
                msgs.append("✅ " + ok_text)
            continue
        m = dict(m) if m else {"since": now.isoformat(), "sent": None}
        if m["sent"] is None:
            if now - datetime.fromisoformat(m["since"]) >= timedelta(hours=min_h):
                msgs.append("⚠️ " + text)
                m["sent"] = now.isoformat()
        elif now - datetime.fromisoformat(m["sent"]) >= timedelta(hours=REMIND_H):
            msgs.append("⚠️ ما زال: " + text)
            m["sent"] = now.isoformat()
        new[name] = m
    return msgs, new


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def bd(t):
    return t.astimezone(BAGHDAD).strftime("%Y-%m-%d %H:%M")


def ago(h):
    # Arabic duration: hours up to 2 days, then days
    n = int(h)
    if n < 48:
        return "ساعتين" if n == 2 else f"{n} ساعات" if 3 <= n <= 10 else f"{n} ساعة"
    d = n // 24
    return "يومين" if d == 2 else f"{d} أيام" if d <= 10 else f"{d} يوماً"


def age_fact(now, when, what, ok_text, missing):
    # when = aware datetime, or None (file missing / broken)
    if when is None:
        return (True, missing, ok_text, 0)
    h = (now - when).total_seconds() / 3600
    return (h > STALE_H, f"{what} منذ {ago(h)}. آخر مرة: {bd(when)}.", ok_text, 0)


def check_backup(now):
    # returns (bad, text), or None when unknown (no systemctl and no backup folder, e.g. Windows)
    folder = Path(os.environ.get("BACKUP_DIR", "/home/hilla/backup"))
    problems = []
    try:
        r = subprocess.run(["systemctl", "show", "hilla-backup.service", "-p", "Result", "--value"],
                           capture_output=True, text=True, timeout=20).stdout.strip()
        if r and r != "success":
            problems.append(f"آخر تشغيل للنسخ الاحتياطي فشل ({r})")
    except FileNotFoundError:
        if not folder.exists():
            return None
    except Exception:
        pass
    if folder.exists():
        try:
            ts = int(subprocess.run(["git", "-C", str(folder), "log", "-1", "--format=%ct"],
                                    capture_output=True, text=True, timeout=20, check=True).stdout.strip())
            when = datetime.fromtimestamp(ts, timezone.utc)
            h = (now - when).total_seconds() / 3600
            if h > BACKUP_MAX_H:
                problems.append(f"آخر نسخة احتياطية قبل {ago(h)} ({bd(when)})")
        except Exception:
            problems.append("تعذّرت قراءة آخر نسخة احتياطية")
    return (bool(problems), "النسخ الاحتياطي: " + "، ".join(problems) + ".")


def gather(now, out):
    facts = {}
    seen = load_json(out / "esp32_seen.json")
    try:
        when = datetime.fromisoformat(seen["last_seen"])
    except Exception:
        when = None
    facts["esp32"] = age_fact(now, when, "جهاز التحكم (ESP32) لم يتصل بالخادم", "جهاز التحكم (ESP32) عاد للاتصال.",
                              "جهاز التحكم (ESP32): ملف آخر اتصال مفقود أو تالف.")
    cmd = load_json(out / "command.json")
    try:
        when = datetime.fromisoformat(cmd["generated_at"])
    except Exception:
        when = None
    facts["command"] = age_fact(now, when, "لا يوجد قرار جديد من الذكاء الاصطناعي", "القرارات عادت تُصدَر كل ساعة.",
                                "قرار الذكاء الاصطناعي: ملف الأمر مفقود أو تالف.")
    b = check_backup(now)
    if b is None:
        print("backup: unknown (no systemctl and no backup folder) - skipped")
    else:
        facts["backup"] = (b[0], b[1], "النسخ الاحتياطي عاد يعمل.", 0)
    n = (cmd or {}).get("now") or {}
    air_bad = n.get("metar_ok") is False or n.get("metar_available") == 0
    facts["airports"] = (air_bad, "لا توجد بيانات من مطارات النجف وبغداد (METAR) منذ 6 ساعات أو أكثر؛ لا غسيل حتى تعود.",
                         "بيانات المطارات عادت.", AIRPORT_H)
    return facts


def send(token, chat, text):
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={"chat_id": chat, "text": text}, timeout=20)
    r.raise_for_status()


def save_atomic(path, text):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def self_test():
    t0 = datetime(2026, 11, 14, 9, 0, tzinfo=BAGHDAD)
    h = lambda k: t0 + timedelta(hours=k)
    bad = {"esp32": (True, "x", "ok", 0)}
    good = {"esp32": (False, "x", "ok", 0)}
    m, mem = judge(h(0), bad, {})
    assert m == ["⚠️ x"], m
    assert judge(h(1), bad, mem)[0] == []
    m, mem = judge(h(25), bad, mem)
    assert m == ["⚠️ ما زال: x"], m
    m, mem = judge(h(26), good, mem)
    assert m == ["✅ ok"] and mem == {}, (m, mem)
    air = lambda b: {"airports": (b, "a", "aok", AIRPORT_H)}
    mem = {}
    for k in range(6):                     # hours 0..5: bad but under 6 h -> silent
        m, mem = judge(h(k), air(True), mem)
        assert m == [], (k, m)
    m, mem = judge(h(6), air(True), mem)
    assert m == ["⚠️ a"], m
    mem = {}
    for k in range(5):
        m, mem = judge(h(k), air(True), mem)
    m, mem = judge(h(5), air(False), mem)  # back before 6 h: nothing at all
    assert m == [] and mem == {}, (m, mem)
    assert ago(2) == "ساعتين" and ago(5) == "5 ساعات" and ago(22) == "22 ساعة"
    assert ago(49) == "يومين" and ago(265) == "11 يوماً"
    print("watchdog.py self-test passed")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "output"))
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return 0
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not args.dry_run and not (token and chat):
        print("error: set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID (server: /etc/hilla/telegram.env), or use --dry-run")
        return 2
    try:
        if args.test:
            send(token, chat, "✅ اختبار: تنبيهات نظام الحلة تعمل.")
            print("test message sent")
            return 0
        now = datetime.now(BAGHDAD)
        spath = Path(os.environ.get("WATCHDOG_STATE", Path.home() / ".hilla_watchdog.json"))
        mem = load_json(spath) or {}
        msgs, new = judge(now, gather(now, Path(args.out)), mem)
        for m in msgs:
            if args.dry_run:
                print(m)
            else:
                send(token, chat, m)
        if not args.dry_run:
            save_atomic(spath, json.dumps(new, indent=2))
        print(f"{len(msgs)} message(s)")
    except requests.RequestException as e:
        print(f"sending failed ({type(e).__name__}); memory not saved, will retry next run")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
