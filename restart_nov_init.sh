#!/bin/bash
# ---------------------------------------------------------------------------
# Full rebuild for the C3S November 2026 release.
#
# Run this once the November init is published for every centre (C3S release
# date: 10 November 2026):
#
#     ./restart_nov_init.sh <github-token>
#
# Everything is re-fetched from scratch on the November init; nothing from the
# October fallback survives.  The NOAA systems (SFSv1, CFSv2) are already on
# the November init and are read from NOAA directly, so they are not touched
# here.
# ---------------------------------------------------------------------------
set -u
cd "$(dirname "$0")"
export PATH="$PATH:/usr/local/bin"
TOK="${1:-}"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

# 1. toolchain - the sandbox is rebuilt periodically and loses it
pip install --break-system-packages -q -i https://pypi.org/simple \
    requests eccodes numcodecs cdsapi zarr xarray h5netcdf fsspec s3fs h5py \
    >/dev/null 2>&1
log "toolchain ready"

# 2. drop every series that came from the October fallback
rm -f data/models/*/u10_daily.npz data/models/*/snow_daily.npz
rm -f data/models/*/sst_monthly.grib data/models/*/enso.json
rm -f data/daily_jobs.json data/snow_daily_jobs.json
log "October series removed"

# 3. point the daily pulls at the November init (365 d ceiling; each model is
#    later trimmed to its own last date).  NOAA is deliberately absent - it
#    never comes from C3S.
cat > data/daily_centres.json <<'JSON'
[
 {"tag":"cmcc-sps4",      "centre":"cmcc",        "system":4,   "year":2026,"month":11,"n_days":365},
 {"tag":"dwd-gcfs2",      "centre":"dwd",         "system":22,  "year":2026,"month":11,"n_days":365},
 {"tag":"eccc-canesm5",   "centre":"eccc",        "system":4,   "year":2026,"month":11,"n_days":365},
 {"tag":"eccc-gem5",      "centre":"eccc",        "system":5,   "year":2026,"month":11,"n_days":365},
 {"tag":"ukmo-gloseas6",  "centre":"ukmo",        "system":610, "year":2026,"month":11,"n_days":365},
 {"tag":"meteo-france-s9","centre":"meteo_france","system":9,   "year":2026,"month":11,"n_days":365}
]
JSON
cat > data/snow_daily_centres.json <<'JSON'
[
 {"tag":"ecmwf-seas5",      "centre":"ecmwf",        "system":51,  "year":2026,"month":11,"n_days":365},
 {"tag":"cmcc-sps4",        "centre":"cmcc",         "system":4,   "year":2026,"month":11,"n_days":365},
 {"tag":"dwd-gcfs2",        "centre":"dwd",          "system":22,  "year":2026,"month":11,"n_days":365},
 {"tag":"eccc-canesm5",     "centre":"eccc",         "system":4,   "year":2026,"month":11,"n_days":365},
 {"tag":"eccc-gem5",        "centre":"eccc",         "system":5,   "year":2026,"month":11,"n_days":365},
 {"tag":"ukmo-gloseas6",    "centre":"ukmo",         "system":610, "year":2026,"month":11,"n_days":365},
 {"tag":"meteo-france-s9",  "centre":"meteo_france", "system":9,   "year":2026,"month":11,"n_days":365}
]
JSON
log "daily pulls re-pointed at the November init"

# 4. what does C3S actually serve now?
python3 -u scan_inits.py 2>&1 | tee "data/probe/inits_$(date -u +%m%d).txt"

# 5. the data (CDS requests are sequential)
python3 -u fetch_models.py               # monthly snowfall + hindcast climate + u10
python3 -u fetch_models_daily.py --auto  # daily 10 hPa -> each model's full lead time
python3 -u fetch_snow_daily.py --auto    # daily snowfall -> snow past lead month 6
python3 -u fetch_sfs.py                  # NOAA SFSv1 on the current init
python3 -u fetch_cfsv2.py                # NOAA CFSv2 on the current init

# 6. the graphics
python3 -u plot_snow_models.py --unit snow
python3 -u plot_snow_multi.py
python3 -u build_spv_panels.py

# 6b. the ENSO plumes: the ERA5 1991-2020 basin climatology, the seasonal SST
#     for every C3S centre, the NOAA systems straight from NOAA, and the
#     charts.  This is what brings the remaining centres onto the site.
python3 -u fetch_era5_enso.py      # the ERA5 1991-2020 basin climatology
python3 -u fetch_ersst.py           # the analysis: NOAA ERSST v6
python3 -u fetch_oni.py             # the official NOAA/CPC ONI and RONI
python3 -u fetch_enso.py            # the C3S centres, one request at a time
python3 -u fetch_enso_noaa.py       # NOAA SFSv1 + NOAA CFSv2
ENSO_RELEASE=all python3 -u plot_enso.py

# 7. the site
python3 build_registry.py
python3 build_site.py

# 8. publish
if [ -n "$TOK" ]; then
    ./refresh_site.sh "$TOK" "C3S November 2026 init - full rebuild"
else
    log "no token given - site built but not published"
fi

# 9. verify the live site and repackage the bundle
python3 verify_site.py || log "verify_site reported problems"
rm -f /workspace/seasonal-snow-site.zip
( cd docs && zip -qr /workspace/seasonal-snow-site.zip . )
log "done - bundle at /workspace/seasonal-snow-site.zip"
