"""Cross-check for the GEFS v12 series: our ensemble mean against NCEP's own.

`fetch_polar_gefs.py` computes the ensemble mean from the 31 member files.
NCEP publishes the same mean as `geavg.*`.  This pulls the `geavg` file for
one lead and the twelve levels, reduces it the same way, and prints the two
side by side - the difference should be far below the day-to-day signal.

    python3 verify_polar_gefs.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

import fetch_polar_gefs as f  # noqa: E402
from polar_cap import LEVELS, read_grib_levels  # noqa: E402


def main():
    date, hour = f.find_cycle()
    f.DATE, f.HOUR = date, hour
    lead = 12
    parts = {}
    for part in ("a", "b"):
        base = "atmos/%sgeavg.t00z.pgrb2%s.0p50.f%03d" % (f.PARTS[part], part,
                                                           lead)
        try:
            msgs = f.read_idx(base + ".idx")
        except Exception as e:                         # noqa: BLE001
            print("   the geavg %s half is not there: %s" % (part, e))
            continue
        size = f.head_size(base)
        alloff = sorted(set(x[0] for x in msgs))
        blob = b""
        for lev in LEVELS:
            if f.PART_OF[lev] != part:
                continue
            hit = [o for o, v, l in msgs if v == "HGT" and l == "%d mb" % lev]
            if not hit:
                print("   the geavg %s half has no %d hPa" % (part, lev))
                continue
            off = hit[0]
            nxt = [o for o in alloff if o > off]
            end = nxt[0] if nxt else size
            r = f.get_first(base, headers={"Range": "bytes=%d-%d" % (off, end - 1)})
            blob += r.content
        parts[part] = blob
    if not parts:
        print("   NCEP's ensemble mean is not published for this lead")
        return
    tmp = os.path.join(DATA, "_gefs_geavg.grib2")
    with open(tmp, "wb") as fp:
        for part in sorted(parts):
            fp.write(parts[part])
    row, t = f.read_cap_mean(tmp)
    os.remove(tmp)
    print("   NCEP's own ensemble mean at %s:" % t)
    print("      " + "  ".join("%d:%.0f" % (l, row.get(l, float("nan")))
                               for l in LEVELS))
    print("   10 hPa: %.0f m2/s2 (%.0f m)" % (row[10], row[10] / f.G0))


if __name__ == "__main__":
    main()
