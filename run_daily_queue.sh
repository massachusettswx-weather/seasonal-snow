#!/bin/bash
# Keep the daily pulls going: the 10 hPa wind first (the SPV panels), then
# the daily snowfall (which is what lets a model's snow panels run past lead
# month 6).  Each script is safe to re-run: they resume from their state.
cd "$(dirname "$0")"
export PATH="$PATH:/usr/local/bin"
python3 -u fetch_models_daily.py --auto >> data/probe/fetch_u10_daily.log 2>&1
echo "u10 daily done at $(date -u)" >> data/probe/fetch_u10_daily.log
python3 -u fetch_snow_daily.py --auto >> data/probe/fetch_snow_daily.log 2>&1
echo "snow daily done at $(date -u)" >> data/probe/fetch_snow_daily.log
