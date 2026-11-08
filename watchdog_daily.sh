#!/bin/bash
# Keep the daily-u10 pipeline alive across sandbox rebuilds.
#
# The sandbox is rebuilt periodically and every background process dies with
# it, while the CDS jobs themselves survive server-side.  A rebuild also wipes
# the Python toolchain.  This watchdog restores both.
cd /workspace/seas5
TOKEN="$1"

while true; do
  if ! python3 -c "import requests, eccodes, numcodecs" > /dev/null 2>&1; then
    echo "$(date +%H:%M:%S) toolchain missing -> reinstalling"
    pip install --break-system-packages -q -i https://pypi.org/simple \
      requests eccodes numcodecs cdsapi >> data/probe/watchdog.log 2>&1
  fi
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
  sleep 45
done
