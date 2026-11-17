# Deployment guide (current setup: one VPS)

No IP addresses or Wi-Fi names here (this repo is public). Private details are in `handoff.local.md` (not in git).

## 1. Architecture
- A small Ubuntu VPS (DigitalOcean) runs everything: the decision model, the weekly retraining, the web page and the ESP32 window.
- Caddy (reverse proxy) serves HTTPS on `hilla-ai.duckdns.org` and forwards to the app on `127.0.0.1:8000`.
- The ESP32 asks `/command` over HTTPS about every 14 minutes, checks `valid_until`, runs the pump only for a new `command_id`, and confirms with `POST /ack`.
- GitHub is only a daily backup. The old GitHub Actions workflows were removed.
- Project: `/home/hilla/app`. Python environment: `/home/hilla/venv`. User: `hilla`.

## 2. Services and timers (systemd)
| Unit | When | What |
|---|---|---|
| `hilla-decide.timer` | every hour at :05 and :35 | runs `live_decision.py`, writes `output/command.json` (same hour = same command, the second run is a retry) |
| `hilla-retrain.timer` | Friday 02:00 | runs `retrain.py`; a new model is accepted only if it scores better |
| `hilla-backup` | daily 03:50 | `deploy/backup_to_github.sh` |
| `hilla-web` | always on | uvicorn on `127.0.0.1:8000` behind Caddy |

`flock` stops the decision, retraining and backup from running at the same time.
Useful: `systemctl list-timers`, `journalctl -u hilla-decide -n 50`.

## 3. Environment variables (web service)
| Variable | Meaning |
|---|---|
| `COMMAND_URL` | where `server/app.py` reads `command.json` (`file:` prefix = local disk) |
| `LOG_URL` | same for `decision_log.csv` |
| `ACK_KEY` | secret the ESP32 sends in header `X-Key` when it confirms a clean. If missing, `/ack` answers 503 |

`ACK_KEY` lives in `/etc/hilla/web.env` (one line `ACK_KEY=...`, `chmod 600`). It is loaded by `deploy/systemd/hilla-web.ack.conf`:
```
sudo mkdir -p /etc/systemd/system/hilla-web.service.d
sudo cp deploy/systemd/hilla-web.ack.conf /etc/systemd/system/hilla-web.service.d/ack.conf
sudo systemctl daemon-reload && sudo systemctl restart hilla-web
```
The same key is in the ESP32 `secrets.h` (never committed).

## 4. Deploying new code (scp, not git pull)
`output/` and `state/` change on the server all the time. Never copy the local `output/` or `state/` over them.
1. On the server, back up the state first: `cp -a /home/hilla/app/state /home/hilla/state_$(date +%F)`.
2. `scp` only the changed code files (`*.py`, `server/`, `deploy/`, `requirements.txt`).
3. If `server/` changed: `sudo systemctl restart hilla-web`. The timers pick up new Python files by themselves.
4. Check: open the site, and `journalctl -u hilla-decide -n 20`.

## 5. Daily backup
`deploy/backup_to_github.sh` (user `hilla`, 03:50) copies `output`, `state`, `models/extended`, `data/raw_hilla*`, `data/raw_metar` and `reports/retrain_log.csv` into a clone of this repo and pushes. It uses a deploy key that can write to this repository only. It never deletes files.
The local copy is behind GitHub: run `git pull` before editing.

## 6. Defence demo
- `deploy\demo_start.bat` sends one test "clean" command (1 minute, valid 10 minutes). Then press RESET on the ESP32.
- `deploy\demo_stop.bat` ends it. The ESP32 counts it in the 2-washes-per-day limit.
- Both use `ssh hilla-vps`, a short name you define once in `%USERPROFILE%\.ssh\config` (example in `handoff.local.md`).

## 7. ESP32 code and Wi-Fi setup
- Code: `esp32/pv_cleaner_client/`. Copy `secrets.example.h` to `secrets.h` and fill in the server address and `ACK_KEY`; `secrets.h` is ignored by git.
- Wi-Fi is set from a phone (WiFiManager): hold the BOOT button for 3 seconds, join the network `Hilla-PV-Setup`, choose the 2.4 GHz network and enter its password. No re-flashing needed.
- Safety rules inside the ESP32: pump at most 30 minutes, nothing if the connection fails or the command is expired.

Data: Open-Meteo.com (CC BY 4.0); METAR: aviationweather.gov.
