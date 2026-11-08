#!/bin/bash
# Keep the daily-u10 fetch loop and the auto-publisher alive.
#
# The sandbox is rebuilt periodically and every background process dies with
# it, while the CDS jobs themselves survive server-side.  This watchdog
# restarts the local loops if they are missing.
cd /workspace/seas5
TOKEN="$1"

while true; do
  if ! pgrep -f "fetch_models_dail[y].py --auto" > /dev/null 2>&1; then
    echo "$(date +%H:%M:%S) fetch loop down -> restarting"
    nohup python3 -u fetch_models_daily.py --auto >> data/probe/auto_daily.log 2>&1 &
    sleep 5
  fi
  if ! pgrep -f "auto_publish_dail[y].sh" > /dev/null 2>&1; then
    echo "$(date +%H:%M:%S) publisher down -> restarting"
    nohup ./auto_publish_daily.sh "$TOKEN" 1 >> data/probe/auto_publish.log 2>&1 &
    sleep 5
  fi
  sleep 60
done
