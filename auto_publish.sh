#!/bin/bash
# ---------------------------------------------------------------------------
# Publish the site whenever new data lands.
#
# The CDS queue is slow - a request can take hours - so the site should not
# wait for a human to notice that a file arrived.  This watches the model's
# data directory and, when anything changes, rebuilds the graphics and the
# pages and pushes them.
#
#     ./auto_publish.sh <github-token>
#
# It only acts when the INPUT DATA has changed, so it does not push on every
# poll, and it does not publish a build that changed nothing.
# ---------------------------------------------------------------------------
set -u
cd "$(dirname "$0")"
TOK="${1:-}"
WATCH="data/models"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

# the fingerprint of the input data: every model file, with its size and
# modification time
fingerprint() {
    find "$WATCH" -type f \( -name '*.grib' -o -name '*.npz' \) \
        -printf '%p %s %T@\n' 2>/dev/null | sort
}

prev=""
while true; do
    cur=$(fingerprint)
    if [ -n "$cur" ] && [ "$cur" != "$prev" ]; then
        if [ -z "$prev" ]; then
            log "first look - nothing to do yet"
        else
            log "the data changed - rebuilding"
            # the plume indices of any centre whose SST has just landed
            for tag in jma-jra3 bom-access-s2 eccc-gem5 eccc-canesm5; do
                if [ -f "data/models/$tag/sst_monthly.grib" ]; then
                    python3 -u build_enso_json.py "$tag" >> logs_auto_publish.log 2>&1
                fi
            done
            python3 -u plot_snow_models.py --unit snow >> logs_auto_publish.log 2>&1
            python3 -u plot_snow_multi.py >> logs_auto_publish.log 2>&1
            python3 -u plot_enso.py >> logs_auto_publish.log 2>&1
            if [ -n "$TOK" ]; then
                # refresh_site.sh renders the SPV panels, the registry and the
                # pages, commits and pushes
                ./refresh_site.sh "$TOK" "New seasonal data" >> logs_auto_publish.log 2>&1
                python3 -u verify_site.py >> logs_auto_publish.log 2>&1
                rm -f /workspace/seasonal-snow-site.zip
                ( cd docs && zip -qr /workspace/seasonal-snow-site.zip . )
                log "published"
            else
                log "built but not published (no token)"
            fi
        fi
        prev="$cur"
    fi
    sleep 120
done
