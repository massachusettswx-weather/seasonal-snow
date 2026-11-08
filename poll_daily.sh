#!/bin/bash
cd /workspace/seas5
for i in $(seq 1 400); do
  echo "===== poll $i $(date +%H:%M:%S)"
  python3 -u fetch_models_daily.py --poll 2>&1 | tail -30
  # stop when every centre has its daily npz
  ok=1
  for t in cmcc-sps4 dwd-gcfs2 eccc-canesm5 eccc-gem5 ukmo-gloseas6; do
    [ -f "data/models/$t/u10_daily.npz" ] || ok=0
  done
  [ "$ok" = "1" ] && { echo "ALL CENTRES HAVE DAILY DATA"; break; }
  sleep 120
done
