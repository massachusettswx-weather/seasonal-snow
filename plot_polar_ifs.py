"""Draw the polar cap section for the ECMWF open data (the IFS).

The reference figure is "ECMWF 11 Nov 12z: Polar Cap (60-90N) Normalized
Geopotential Height Anomaly", with the ECMWF analysis on the left of the
split and the 15-day forecast on the right.  This reproduces that layout
with this site's own house style:

  * the ERA5 1991-2020 polar cap climatology, normalised by sigma;
  * the IFS analysis from the open data bucket for the days before the init;
  * the IFS forecast from the same bucket for the 15 days after it;
  * the reference's own colour ladder, log pressure axis and altitude axis.

The IFS open data does not carry 30 hPa, so the section uses the eleven
levels it serves out of the reference's twelve.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import (LEVELS, load_climatology, normalise,   # noqa: E402
                       plot_section)

FC = os.path.join(DATA, "polar_ifs.json")
AN = os.path.join(DATA, "polar_analysis.json")
OUT = os.path.join(HERE, "output", "polar_cap")

# the levels the IFS open data serves that the reference also uses
IFS_LEVELS = [10, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]

# the ERA5 climatology was built on the C3S level set, which includes 30 hPa.
# The IFS does not serve 30 hPa, so the section is drawn on the levels both
# have, and the climatology is subset to match.
CLIM_LEVELS = [10, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]


def _load(path, key):
    if not os.path.exists(path):
        return [], []
    d = json.load(open(path))
    rec = d.get(key)
    if not rec:
        return [], []
    return list(rec["times"]), np.array(rec["values"], float)


def _subset(values, src_levels, want):
    """Pick the wanted levels out of a (n, nlev) array."""
    idx = [src_levels.index(l) for l in want]
    return values[:, idx]


def main():
    os.makedirs(OUT, exist_ok=True)

    at, av = _load(AN, "ifs-analysis")
    ft, fv = _load(FC, "20261111-ifs")
    if not ft:
        print("   no IFS forecast yet")
        return None
    print("   the analysis: %d days   the forecast: %d days" % (len(at), len(ft)))

    # the climatology, subset to the levels the IFS serves
    days, clevels, cmean, csigma = load_climatology()
    keep = [clevels.index(l) for l in CLIM_LEVELS]
    clim = (days, CLIM_LEVELS, cmean[:, keep], csigma[:, keep])

    av = _subset(av, IFS_LEVELS, CLIM_LEVELS)
    fv = _subset(fv, IFS_LEVELS, CLIM_LEVELS)

    # join on the calendar day: the analysis ends on the init day, which is
    # also the first forecast day, so the init day is taken once (from the
    # forecast) and the analysis stops the day before
    fdays = [t[:10] for t in ft]
    adays = [t[:10] for t in at]
    init = fdays[0]
    ana_days = [d for d in adays if d < init]

    aday_idx = {d: i for i, d in enumerate(adays)}
    fday_idx = {d: i for i, d in enumerate(fdays)}

    days_used = ana_days + fdays
    values = np.vstack([av[[aday_idx[d] for d in ana_days]],
                        fv[[fday_idx[d] for d in fdays]]])
    split = len(ana_days)

    anom, norm = normalise(days_used, values, CLIM_LEVELS, clim)
    if not np.isfinite(norm).any():
        print("   the normalisation produced nothing")
        return None

    # the split line sits between the last analysis day and the init
    title = ("ECMWF IFS 11 Nov 12z: Polar Cap (60-90N) Normalized "
             "Geopotential Height Anomaly")
    subtitle = ("Data: ECMWF IFS open data & ERA5 (1991-2020 Climatology)   "
                "Plot by: @Massachusettswx")
    path = os.path.join(OUT, "polar_cap_ifs.png")
    plot_section(days_used, norm, CLIM_LEVELS, path, title, subtitle,
                 split=split, credit=None,
                 analysis_label="ECMWF ANALYSIS",
                 forecast_label="ECMWF 15-DAY FORECAST (11 Nov 12z)")
    print("   the figure: %s" % path)
    return path


if __name__ == "__main__":
    main()
