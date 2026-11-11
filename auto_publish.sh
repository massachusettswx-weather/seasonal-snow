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
# The token lives in data/.github_token with mode 600, not on the command
# line, so it is never visible in the process list.  It is passed as the
# first argument for compatibility and written into the file.
TOKFILE="data/.github_token"
if [ -n "${1:-}" ]; then
    mkdir -p data
    printf '%s' "$1" > "$TOKFILE"
    chmod 600 "$TOKFILE"
fi
TOK="$(cat "$TOKFILE" 2>/dev/null || true)"
WATCH="data/models"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

# the fingerprint of the input data: every model file, with its size and
# modification time
fingerprint() {
    find "$WATCH" -type f \( -name '*.grib' -o -name '*.npz' -o -name '*.nc' \
         -o -name 'enso.json' \) \
        -printf '%p %s %T@\n' 2>/dev/null | sort
}

# The fingerprint is kept in a file, so that a restart of this watcher
# still knows what was published last.  Without it, a restart would treat
# everything as a first look and never rebuild - which is exactly what
# happens after the sandbox rebuilds and the data changed in between.
FPFILE="data/.publish_fingerprint"
prev=""
[ -f "$FPFILE" ] && prev=$(cat "$FPFILE")
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
            # the ECCC's two systems are pooled into the official canSIPS
            # ensemble before anything is rendered
            python3 -u build_cansips.py >> logs_auto_publish.log 2>&1
            python3 -u plot_snow_models.py --unit snow >> logs_auto_publish.log 2>&1
            python3 -u plot_snow_multi.py >> logs_auto_publish.log 2>&1
            python3 -u plot_enso.py >> logs_auto_publish.log 2>&1
            # A revoked token would fail the push and leave a dead
            # credential behind, so it is checked once.  Either way the site
            # is rebuilt and committed locally; only the push is
            # conditional, so a missing token never stops the work.
            if [ -z "$TOK" ]; then
                log "no GitHub token - the site is built locally but NOT published"
                SKIP_PUSH=1 ./refresh_site.sh "none" "New seasonal data" >> logs_auto_publish.log 2>&1
            else
                code=$(curl -s -o /dev/null -w '%{http_code}' -m 20 \
                    -H "Authorization: token $TOK" https://api.github.com/user)
                if [ "$code" != "200" ]; then
                    log "the GitHub token is no longer accepted (HTTP $code) - the site is built locally but NOT published"
                    SKIP_PUSH=1 ./refresh_site.sh "$TOK" "New seasonal data" >> logs_auto_publish.log 2>&1
                else
                    ./refresh_site.sh "$TOK" "New seasonal data" >> logs_auto_publish.log 2>&1
                    log "published"
                fi
            fi
            python3 -u verify_site.py >> logs_auto_publish.log 2>&1
            rm -f /workspace/seasonal-snow-site.zip
            ( cd docs && zip -qr /workspace/seasonal-snow-site.zip . )
        fi
        prev="$cur"
        echo "$cur" > "$FPFILE"
    fi
    sleep 120
done
