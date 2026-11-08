#!/bin/bash
# Wait for the daily u10 pulls to land, then render the daily SPV charts,
# rebuild the site and publish it to GitHub Pages.
#
# Publishes as soon as at least MIN_CENTRES centres have their daily data, so a
# partial result is still published, and publishes whatever exists on timeout.
cd /workspace/seas5
TOKEN="$1"
MIN_CENTRES="${2:-1}"
CENTRES="cmcc-sps4 dwd-gcfs2 eccc-canesm5 eccc-gem5 ukmo-gloseas6"

publish () {
  echo "$(date +%H:%M:%S) $1 -> rendering + publishing"
  ./refresh_site.sh "$TOKEN" "Daily 10 hPa zonal-mean zonal wind for every seasonal centre"
  echo "$(date +%H:%M:%S) publish finished"
}

count_ready () {
  # a centre only counts when all three chunks are merged, i.e. the npz holds
  # the full 215-day run - a partial centre must not be published as if it
  # were the whole series.
  local n=0 t d
  for t in $CENTRES; do
    [ -f "data/models/$t/u10_daily.npz" ] || continue
    d=$(python3 -c "
import numpy as np,sys
try:
    z=np.load('data/models/$t/u10_daily.npz', allow_pickle=True)
    print(len(z['dates']))
except Exception:
    print(0)
" 2>/dev/null)
    [ "$d" = "215" ] && n=$((n+1)) || echo "   $t: only $d of 215 days - not publishing"
  done
  echo "$n"
}

for i in $(seq 1 500); do
  n=$(count_ready)
  if [ "$n" -ge "$MIN_CENTRES" ]; then
    publish "$n centres ready"
    exit 0
  fi
  sleep 120
done

n=$(count_ready)
if [ "$n" -gt 0 ]; then
  publish "$n centres ready (timeout)"
else
  echo "timed out with no daily data"
fi
