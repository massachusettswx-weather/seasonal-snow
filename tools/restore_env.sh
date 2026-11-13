#!/bin/bash
# Restore the Python packages the pipeline needs.
#
# The sandbox's system packages (/usr/local/lib/python3.11/dist-packages) are
# reset from time to time, and `requests` and `eccodes` disappear with them -
# which kills every fetcher and every GRIB reader in the pipeline without
# an error message that says so.
#
# They are installed into the USER site, which lives under the workspace
# (/workspace/.home) and therefore survives the reset.  Note that the user
# site is only on sys.path when the directory exists, so this script creates
# it first.
#
#     ./tools/restore_env.sh
set -u
cd "$(dirname "$0")/.."
SITE="$HOME/.local/lib/python3.11/site-packages"
mkdir -p "$SITE"
# the Aliyun mirror in PIP_INDEX_URL is not reachable from here; pypi.org is
pip install --break-system-packages --index-url https://pypi.org/simple \
    --target "$SITE" requests eccodes 2>&1 | tail -3
python3 - <<'PY'
import requests, eccodes
print("requests %s and eccodes %s are in place" % (requests.__version__,
                                                   eccodes.__version__))
PY
