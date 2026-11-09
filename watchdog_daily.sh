#!/bin/bash
# Keep the toolchain alive across sandbox rebuilds.
#
# The sandbox is rebuilt periodically and every background process dies with
# it, while the CDS jobs themselves survive server-side.  A rebuild also wipes
# the Python toolchain, so this watchdog restores it.
#
# The daily pulls are PAUSED (9 Nov 2026) until C3S releases the November init
# on 10 November 2026, so this watchdog deliberately does NOT restart the
# fetch loop or the publisher any more - it only keeps the toolchain ready
# for restart_nov_init.sh.
cd /workspace/seas5

while true; do
  if ! python3 -c "import requests, eccodes, numcodecs" > /dev/null 2>&1; then
    echo "$(date +%H:%M:%S) toolchain missing -> reinstalling"
    pip install --break-system-packages -q -i https://pypi.org/simple \
      requests eccodes numcodecs cdsapi >> data/probe/watchdog.log 2>&1
  fi
  sleep 120
done
