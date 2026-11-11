"""Build the ENSO plume indices from a centre's SST file that is already on disk.

The centres added later (JMA, BoM) get their sea-surface temperature from
fetch_new_centre.py, which downloads the GRIB but does not decode it - the
decoder lives in fetch_enso.py.  This runs that decoder over the file that is
already there instead of asking the CDS for it a second time.

    python3 build_enso_json.py <tag> [<tag> ...]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fetch_enso import indices_from_grib, save, MDIR      # noqa: E402


def main():
    for tag in sys.argv[1:]:
        p = os.path.join(MDIR, tag, "sst_monthly.grib")
        if not os.path.exists(p):
            print("  %s: no SST on disk - skipping" % tag, flush=True)
            continue
        got = indices_from_grib(p)
        if not got:
            print("  %s: the SST file did not decode" % tag, flush=True)
            continue
        idx, trop = got
        save(tag, idx, trop, "c3s-sst")
        print("  %s: %d lead months of plume indices written"
              % (tag, len(idx)), flush=True)


if __name__ == "__main__":
    main()
