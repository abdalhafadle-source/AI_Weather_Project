#!/usr/bin/env python3
"""
demo_clean.py
For the thesis defence: send ONE test "clean" command to the ESP32 so the committee sees the relays react.
It writes output/demo_command.json (valid 10 minutes, pump 1 minute). The web server serves it instead of
the AI command while it is valid; the AI decision state is never touched, and it expires by itself.

Usage (on the server):  python deploy/demo_clean.py          # start a 10-minute demo window
                        python deploy/demo_clean.py --stop   # end it now
Then press RESET on the ESP32 so it asks the server at once (otherwise it asks within 14 minutes).
The ESP32's own safety caps still apply (max 2 runs/day, 6 h between runs).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "output" / "demo_command.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop", action="store_true", help="end the demo window now")
    ap.add_argument("--minutes", type=int, default=10, help="how long the demo command stays valid")
    args = ap.parse_args()
    if args.stop:
        OUT.unlink(missing_ok=True)
        print("demo stopped - the AI command is served again")
        return 0
    now = datetime.now(timezone(timedelta(hours=3))).replace(microsecond=0)
    cmd = {"command_id": "demo-" + now.strftime("%Y%m%dT%H%M%S"),   # new id, so the ESP32 runs it once
           "generated_at": now.isoformat(), "valid_until": (now + timedelta(minutes=args.minutes)).isoformat(),
           "action": "clean", "pump": True, "max_duration_min": 1, "reason": "demo (manual test)",
           "p_rain": None, "p_dust": None, "pending": [], "source": "manual demo for the thesis defence"}
    OUT.write_text(json.dumps(cmd, indent=2), encoding="utf-8")
    print(f"demo command valid until {cmd['valid_until'][11:16]} - now press RESET on the ESP32")
    return 0


if __name__ == "__main__":
    sys.exit(main())
