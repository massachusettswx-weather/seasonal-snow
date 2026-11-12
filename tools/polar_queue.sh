#!/bin/bash
# The polar-cap fetchers, one after the other.
#
# The CDS account holds two requests at a time and the archive's own queue
# is congested, so the two fetchers must not compete for the same slots.
# The ERA5 reanalysis goes first: it is four monthly requests and it is what
# makes the section's "what happened" half possible.  The seasonal run goes
# second and then walks the model out to the end of its own run.
#
#   ./tools/polar_queue.sh
#
# Both fetchers keep their own state file, so a restart picks up where it
# left off rather than asking the archive for the same days twice.
cd "$(dirname "$0")/.."

echo ">> the ERA5 reanalysis first"
python3 -u fetch_polar_era5_recent.py 90
echo ">> the ERA5 reanalysis is done - now the seasonal run"
python3 -u fetch_polar_models.py
echo ">> both are done"
