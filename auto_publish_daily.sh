#!/bin/bash
# Wait for the daily u10 pulls to land, then render the daily SPV charts,
# rebuild the site and publish it to GitHub Pages.
cd /workspace/seas5
TOKEN="$1"
for i in $(seq 1 500); do
  ok=1
  for t in cmcc-sps4 dwd-gcfs2 eccc-canesm5 eccc-gem5 ukmo-gloseas6; do
    [ -f "data/models/$t/u10_daily.npz" ] || ok=0
  done
  if [ "$ok" = "1" ]; then
    echo "$(date +%H:%M:%S) all daily npz present -> rendering + publishing"
    ./refresh_site.sh "$TOKEN" "Daily 10 hPa zonal-mean zonal wind for every seasonal centre"
    echo "$(date +%H:%M:%S) publish finished"
    exit 0
  fi
  sleep 120
done
echo "timed out waiting for the daily pulls"
