"""The C3S multi-model mean snowfall.

Every seasonal system that comes through the C3S archive is averaged into one
ensemble: each model's monthly accumulation is put on the common CONUS grid,
the models are averaged month by month over the common calendar window
(November to April), and the result is drawn with the same 0-300 in snow-depth
colour scale as the single-model panels.

    python3 plot_snow_multi.py
"""
import json
import os
import sys

import numpy as np
from matplotlib.colors import BoundaryNorm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from plot_snow_models import (draw_map, grid_axes, interp_to, read_snowfall,
                              setup_grid, to_2d)
from plot_snow_ref import LON0, LON1, LAT0, LAT1
from plot_snow_totals import month_len, wm_colormap, GRID

_lo = np.arange(LON0, LON1 + GRID / 2, GRID)
_la = np.arange(LAT0, LAT1 + GRID / 2, GRID)
LON, LAT = np.meshgrid(_lo, _la)

OUT = os.path.join(HERE, "output")
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")

# the C3S seasonal systems (NOAA is not part of C3S)
MODELS = [
    ("ecmwf-seas5", "ECMWF SEAS5"),
    ("cmcc-sps4", "CMCC SPS4"),
    ("dwd-gcfs2", "DWD GCFS2.2"),
    ("eccc-canesm5", "ECCC CanESM5"),
    ("eccc-gem5", "ECCC GEM5.2"),
    ("ukmo-gloseas6", "UKMO GloSeas6"),
]
# every calendar month any of the models covers; the common window is the
# intersection, so the average always spans exactly the months every centre
# has.  When the other centres move onto the November init this becomes
# November 2026 to April 2027.
WINDOW0 = [(2026, 11), (2026, 12), (2027, 1), (2027, 2), (2027, 3), (2027, 4)]
ALL_MONTHS = [(2026, 10), (2026, 11), (2026, 12), (2027, 1), (2027, 2),
              (2027, 3), (2027, 4), (2027, 5), (2027, 6)]


def model_monthly(tag):
    """-> {calendar month: field in inches of snow} for one model."""
    d = os.path.join(MDIR, tag)
    fg = os.path.join(d, "snowfall_monthly.grib")
    if not os.path.exists(fg):
        fg = os.path.join(d, "snowfall_monthly.npz")
    by_step = read_snowfall(fg)
    if not by_step:
        return None
    lats, lons, order = grid_axes(by_step[sorted(by_step)[0]][0])
    out = {}
    for ym, recs in sorted(by_step.items()):
        if (ym[0], ym[1]) not in ALL_MONTHS:
            continue
        stack = np.array([to_2d(r, lats, lons, order) for r in recs])
        ens = stack.mean(axis=0)
        y, m = ym
        g = interp_to(LAT.ravel(), LON.ravel(), lats, lons, ens).reshape(LAT.shape)
        out[(y, m)] = g * month_len(y, m) * 86400.0 * 1000.0 / 25.4 * 10.0
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    X, Y, LAT, LON, in_us, in_mex, relief, countries, states, provs = setup_grid()
    wm_cmap, wm_levels = wm_colormap()

    fields = {}
    used = []
    for tag, name in MODELS:
        f = model_monthly(tag)
        if f:
            fields[tag] = f
            used.append(name)
        else:
            print("  %s: no snowfall on disk - skipped" % tag, flush=True)
    if not fields:
        print("no C3S models with snowfall")
        return

    # the calendar months every model has
    common = set(WINDOW0)
    for f in fields.values():
        common &= set(f)
    WINDOW = sorted(common)
    if not WINDOW:
        print("the models share no calendar month")
        return
    fields = {t: {ym: f[ym] for ym in WINDOW} for t, f in fields.items()}
    print("common window: %s .. %s  (%d models)" %
          (WINDOW[0], WINDOW[-1], len(fields)), flush=True)

    mean = {}
    for ym in WINDOW:
        stack = np.array([fields[t][ym] for t in fields])
        mean[ym] = stack.mean(axis=0)
    total = np.sum([mean[ym] for ym in WINDOW], axis=0)

    names = ", ".join(used)
    MN0 = ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
    d0 = "%02d/%02d/%04d" % (WINDOW[0][1], 1, WINDOW[0][0])
    d1 = "%02d/%02d/%04d" % (WINDOW[-1][1], 1, WINDOW[-1][0])
    sub = ("Mean of %d seasonal systems (%s) · 1° × 1° grid · %s to %s · inches"
           % (len(fields), names, d0, d1))
    draw_map(os.path.join(OUT, "snow_c3s-multi_total_run_in.png"),
             "C3S Multi-Model Mean  Snowfall Total — %s to %s" % (d0, d1),
             sub, total, X, Y, in_us, relief, states, provs, countries,
             wm_cmap, BoundaryNorm(wm_levels, wm_cmap.N, clip=True), wm_levels,
             "Accumulated snowfall (inches)", white_below=float(wm_levels[0]))
    print("rendered snow_c3s_multi_total_in.png", flush=True)

    MN = ["", "January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
    man_p = os.path.join(DATA, "render_manifest.json")
    man = json.load(open(man_p)) if os.path.exists(man_p) else {}
    man["snow_c3s-multi_total_run_in.png"] = {"label": "", "lead": 0}
    for k, ym in enumerate(WINDOW, start=1):
        y, m = ym
        man["snow_c3s-multi_month%02d_in.png" % k] = {"label": "%s %d" % (MN[m], y),
                                                     "lead": k}
        draw_map(os.path.join(OUT, "snow_c3s-multi_month%02d_in.png" % k),
                 "C3S Multi-Model Mean  Snowfall — %s %d" % (MN[m], y),
                 sub, mean[ym], X, Y, in_us, relief, states, provs, countries,
                 wm_cmap, BoundaryNorm(wm_levels, wm_cmap.N, clip=True), wm_levels,
                 "Accumulated snowfall (inches)", white_below=float(wm_levels[0]))
    json.dump(man, open(man_p, "w"), indent=1)
    print("rendered %d monthly panels" % len(WINDOW), flush=True)


if __name__ == "__main__":
    main()
