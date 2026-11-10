#!/bin/bash
# The ENSO half of the November rebuild, run beside the daily pulls.
#
# The daily 10 hPa and daily snowfall pulls sit in the
# "seasonal-original-*" queue; the seasonal SST sits in the
# "seasonal-monthly-*" queue.  They are different queues, so the ENSO work
# can go on at the same time instead of waiting behind the daily chunks.
cd "$(dirname "$0")"
set -u
log() { echo "[$(date -u +%H:%M:%S)] $*"; }

log "ENSO phase start"
python3 -u fetch_enso.py            # the C3S centres, one request at a time
log "C3S SST done"
python3 -u fetch_enso_noaa.py       # NOAA SFSv1 + NOAA CFSv2
log "NOAA SST done"
python3 -u fetch_enso_hc.py         # each centre's own SST hindcast climate
log "hindcast climate done"
python3 -u plot_enso.py
log "plumes rendered"
