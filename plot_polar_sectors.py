"""Draw the polar cap split into two sectors: the North Pacific and the
North Atlantic, 60-90N.

The same field as the polar-cap section - the geopotential height anomaly in
metres against the 1991-2020 climate - but over one longitude sector at a
time, because the Atlantic and the Pacific do not warm together and the
polar-cap mean hides the difference between them.

Inputs:
  data/polar_model_z.json     the model's daily polar-cap series, with the
                               sector means under "sectors"
  data/polar_cap_clim_monthly.npz
                               the monthly climate, with the sector climate
                               under "sector_data"

    python3 plot_polar_sectors.py <tag> <label>
"""

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import (G0, SECTOR_LABELS, daily_climate,  # noqa: E402
                       plot_sector_sections)
from ecmwf_credit import credit_for  # noqa: E402

OUT = os.path.join(HERE, "output", "polar_cap")
MODEL_CACHE = os.path.join(DATA, "polar_model_z.json")
CLIM_MONTHLY = os.path.join(DATA, "polar_cap_clim_monthly.npz")
# the EC46 keeps its own file
EC46_CACHE = os.path.join(DATA, "polar_ec46_z.json")


def cache_for(tag):
    return EC46_CACHE if tag == "ec46" else MODEL_CACHE


def load_sector_clim():
    """-> {sector: {month: (mean, sigma)}}, or None."""
    if not os.path.exists(CLIM_MONTHLY):
        return None
    d = np.load(CLIM_MONTHLY, allow_pickle=True)
    if "sector_data" not in d:
        return None
    out = {}
    for entry in d["sector_data"]:
        for name, months in entry.items():
            out[name] = {int(m): (np.array(v["mean"], float),
                                  np.array(v["sigma"], float))
                         for m, v in months.items()}
    return out


def main(tag="gefsv12", label="NOAA GEFSv12"):
    p = cache_for(tag)
    if not os.path.exists(p):
        print("   no polar series for %s yet" % tag)
        return None
    rec = json.load(open(p)).get(tag)
    if not rec or not rec.get("sectors"):
        print("   the %s series carries no sector means" % tag)
        return None
    clim = load_sector_clim()
    if not clim:
        print("   no sector climate yet - the CDS monthly means are still "
              "being fetched")
        return None

    times = list(rec["times"])
    order = sorted(range(len(times)), key=lambda i: times[i])
    times = [times[i] for i in order]
    levels = [int(x) for x in (rec.get("levels") or [])]

    # the monthly climate, per sector, for each month of the series
    anom = {}
    for name, series in rec["sectors"].items():
        if name not in clim:
            print("   the %s sector has no climate yet" % name)
            continue
        vals = np.array(series, float)[order]
        keep = [i for i, t in enumerate(times)
                if t.endswith("12") or len(t) == 10]
        times_s = [times[i] for i in keep]
        vals = vals[keep]
        if len(times_s) < 3:
            continue
        # the monthly sector climate, as arrays, and then put on the days
        # of the series: a monthly climate applied to a daily series steps
        # at every month boundary and the step draws a seam across the
        # chart
        mlist = sorted(clim[name])
        mmean = np.array([np.asarray(clim[name][m][0], float)[:len(levels)]
                          for m in mlist])
        daily = daily_climate(times_s, mlist, mmean)
        # the climate and the model are both geopotential (m2/s2); the
        # chart is in METRES, so the anomaly is divided by G0
        rows = [(vals[i] - daily[i]) / G0 for i in range(len(times_s))]
        anom[name] = np.array(rows, float)
        times = times_s
        vals = None

    if not anom:
        print("   no sector series could be put against the climate")
        return None

    # the title and the descriptor
    label_txt = "%s · Polar Cap (60-90°N) by Sector" % label
    run = rec.get("run") or ""
    nmem = rec.get("members")
    bits = []
    if run:
        bits.append("%s run" % run)
    if nmem:
        bits.append("%s members" % nmem)
    bits.append("%d levels (10-1000 hPa)" % len(levels))
    bits.append("ERA5 1991-2020 sector climatology")
    subtitle = ("the %s sector forecast from %s to %s · %s"
                % (label, times[0][:10], times[-1][:10], " · ".join(bits)))

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "polar_sectors_%s.png" % tag)
    plot_sector_sections(times, anom, levels, path, label_txt, subtitle,
                         credit=credit_for(tag))
    print("   the figure: %s" % path)
    return path


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "gefsv12"
    label = sys.argv[2] if len(sys.argv) > 2 else "NOAA GEFSv12"
    main(tag, label)
