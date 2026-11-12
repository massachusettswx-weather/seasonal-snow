#!/bin/bash
# Build and publish the polar-cap section.
#
# The section needs three things, and all three have to be present before
# anything is published:
#
#   data/era5_polarcap_profiles.npz   the ERA5 1991-2020 polar-cap climatology
#   data/polar_cap_recent.npz         the ERA5 analysis just before the init
#   data/polar_model_z.json           the model's daily polar-cap forecast
#
# The publisher refuses to run if any of them is missing, so a chart is never
# published with an orphaned half.
set -e
cd "$(dirname "$0")"

echo "== the polar-cap section =="

python3 - <<'PY'
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath("build_site.py")))
need = ["data/era5_polarcap_profiles.npz", "data/polar_cap_clim.npz",
        "data/polar_cap_recent.npz", "data/polar_model_z.json"]
missing = [p for p in need if not os.path.exists(p)]
if missing:
    print("   the section is not ready, missing:")
    for m in missing:
        print("     %s" % m)
    raise SystemExit(2)
print("   the inputs are all present")
PY

# the section for every model that has a forecast series
python3 plot_polar_cap.py ecmwf-seas5 "ECMWF SEAS5" || true
for pair in "ukmo-gloseas6:UKMO GloSeas6" "meteo-france-s9:METFR System 9" \
            "cmcc-sps4:CMCC SPS4" "dwd-gcfs2:DWD GCFS2.2" "eccc-cansips:ECCC canSIPS"; do
  tag="${pair%%:*}"; label="${pair#*:}"
  python3 plot_polar_cap.py "$tag" "$label" || true
done

python3 build_registry.py
python3 build_site.py

echo "== done =="
