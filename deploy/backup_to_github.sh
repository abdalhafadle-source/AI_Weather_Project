#!/bin/bash
# Daily backup of the live field records (decisions, state, ESP32 last-seen, retrain log, promoted models,
# updated data) from the server into the GitHub repo. Uses a deploy key that can write to this repo only.
# Runs as user hilla from hilla-backup.service (under the same flock as the hourly decision and the retrain).
set -euo pipefail
APP=/home/hilla/app
BK=/home/hilla/backup
REPO=git@github.com:abdalhafadle-source/AI_Weather_Project.git
export GIT_SSH_COMMAND="ssh -i /home/hilla/.ssh/github_backup -o IdentitiesOnly=yes -o BatchMode=yes"

[ -d "$BK/.git" ] || git clone -q "$REPO" "$BK"
cd "$BK"
git pull -q --rebase --autostash
for d in output state models/extended data/raw_hilla data/raw_hilla_extra data/raw_metar; do
  mkdir -p "$d"
  rsync -a --exclude test/ "$APP/$d/" "$d/"          # copy new/changed files, never delete anything
done
cp "$APP/reports/retrain_log.csv" reports/ 2>/dev/null || true
git add output state models/extended data/raw_hilla data/raw_hilla_extra data/raw_metar reports/retrain_log.csv
git diff --cached --quiet && { echo "nothing new to back up"; exit 0; }
git -c user.name="hilla-ai-server" -c user.email="hilla-ai-server@users.noreply.github.com" \
    commit -q -m "server backup $(date '+%Y-%m-%d %H:%M')"
for i in 1 2 3; do git push -q && { echo "backup pushed"; exit 0; }; sleep 10; git pull -q --rebase; done
exit 1
