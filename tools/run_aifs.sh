#!/bin/bash
# Fetch the AIFS ensemble polar cap, restarting if the process is reaped.
#
# The sandbox kills detached background processes when they sit idle, and the
# open data bucket throttles hard enough that a step takes a couple of
# minutes.  The fetch is therefore run in a loop: each pass picks up where
# the last one left off, because the step that was already decoded is
# skipped.
cd "$(dirname "$0")/.."
for i in $(seq 1 40); do
  echo "=== the pass $i ($(date -u +%H:%M:%S)) ==="
  python3 -u fetch_polar_aifs.py
  # the fetch is done when the file has every step
  n=$(python3 - <<'PY'
import json, os
p = "data/polar_aifs.json"
print(len(json.load(open(p))["times"]) if os.path.exists(p) else 0)
PY
)
  echo "=== the pass $i finished with $n steps ==="
  if [ "$n" -ge 16 ]; then
    echo "all the steps are in"
    break
  fi
  sleep 5
done
