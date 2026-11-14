#!/bin/bash
# Rebuild the polar section against the native-store climatology and publish.
#
#   ./tools/rebuild_polar.sh
#
# The climatology is the one built from ARCO's native ERA5 store - the same
# product and grid as the reanalysis half of the section.
set -e
cd "$(dirname "$0")/.."
export HOME=/workspace/.home
export PYTHONPATH=/workspace/.home/.local/lib/python3.11/site-packages

echo ">> the polar-cap charts"
python3 -u plot_polar_cap.py ecmwf-seas5 "ECMWF SEAS5"
python3 -u plot_polar_cap.py gefsv12 "NOAA GEFSv12"
python3 -u plot_polar_sectors.py gefsv12 "NOAA GEFSv12"

echo ">> the registry and the site"
python3 -u build_registry.py > /dev/null
python3 -u build_site.py > /dev/null
python3 -u build_polar_page.py > /dev/null

echo ">> the init coherence gate"
python3 -u audit_inits.py --gate

echo ">> publishing"
./push_to_github.sh

echo ">> verifying"
python3 -u verify_site.py
