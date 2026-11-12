#!/bin/bash
# A full rebuild and publish, run by hand when the graphics have changed.
#
#   bash full_publish.sh "commit message"
#
# The token comes from data/.github_token, never from the command line.
set -u
cd "$(dirname "$0")"
MSG="${1:-Refresh seasonal graphics}"

echo ">> pooling the ECCC systems into canSIPS"
python3 -u build_cansips.py

echo ">> the snow maps"
python3 -u plot_snow_models.py --unit snow

echo ">> the multi-model mean"
python3 -u plot_snow_multi.py

echo ">> the ENSO plumes"
python3 -u plot_enso.py

echo ">> the site"
./refresh_site.sh "" "$MSG"

echo ">> verifying"
python3 -u verify_site.py

rm -f /workspace/seasonal-snow-site.zip
( cd docs && zip -qr /workspace/seasonal-snow-site.zip . )
echo ">> done"
