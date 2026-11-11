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
                            read_extended,
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
    ("meteo-france-s9", "METFR System 9"),
    ("jma-jra3", "JMA CPS4"),
    ("bom-access-s2", "BOM ACCESS-S2"),
]
# every calendar month any of the models covers.  The window runs to the end
# of the range, not to the shortest model: each centre is averaged over the
# months it covers and the number of contributing systems is stated on the
# graphic.
ALL_MONTHS = [(2026, 10), (2026, 11), (2026, 12), (2027, 1), (2027, 2),
              (2027, 3), (2027, 4), (2027, 5), (2027, 6)]


def model_monthly(tag):
    """-> {calendar month: field in inches of snow} for one model."""
    d = os.path.join(MDIR, tag)
    fg = os.path.join(d, "snowfall_monthly.grib")
    if not os.path.exists(fg):
        fg = os.path.join(d, "snowfall_monthly.npz")
    if not os.path.exists(fg):
        return None            # a centre whose data has not arrived yet
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
    # the lead months past the sixth come from the sub-daily product
    xp = os.path.join(d, "snowfall_ext.npz")
    if os.path.exists(xp):
        try:
            for ym, (la, lo, v, nd) in read_extended(xp).items():
                if ym not in ALL_MONTHS or ym in out:
                    continue
                # a month the system only covered for a few days is not a
                # monthly mean - averaging it in with whole months would
                # drag the multi-model mean down
                if nd and nd < 20:
                    print("  %s: %04d-%02d has only %d day(s) - not averaged in"
                          % (tag, ym[0], ym[1], nd), flush=True)
                    continue
                g = interp_to(LAT.ravel(), LON.ravel(), la, lo,
                              v).reshape(LAT.shape)
                out[ym] = g * 1000.0 / 25.4 * 10.0
        except Exception as e:
            print("  %s: unreadable extended months (%s)" % (tag, e))
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

    # the window runs to the end of the C3S range, not to the shortest
    # model: every centre is averaged over the months it actually covers,
    # and the number of contributing systems is stated on the graphic
    # the window runs from the latest init onwards: a centre that is still on
    # an older init contributes its own lead months, but the series as a
    # whole starts where the newest run starts
    inits = {}
    fp = os.path.join(DATA, "models_fetched.json")
    if os.path.exists(fp):
        for k, v in json.load(open(fp)).items():
            if v.get("init"):
                inits[k] = v["init"]
    latest = max(inits.values()) if inits else "2026-11"
    first = (int(latest[:4]), int(latest[5:7]))
    WINDOW = [ym for ym in ALL_MONTHS
              if ym >= first and any(ym in f for f in fields.values())]
    if not WINDOW:
        print("the models share no calendar month")
        return
    print("window: %s .. %s  (%d models)" %
          (WINDOW[0], WINDOW[-1], len(fields)), flush=True)

    mean = {}
    counts = {}
    for ym in WINDOW:
        have = [fields[t][ym] for t in fields if ym in fields[t]]
        mean[ym] = np.array(have).mean(axis=0)
        counts[ym] = len(have)
    total = np.sum([mean[ym] for ym in WINDOW], axis=0)
    nmin = min(counts.values())
    nmax = max(counts.values())

    names = ", ".join(used)
    MN0 = ["", "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
    d0 = "%02d/%02d/%04d" % (WINDOW[0][1], 1, WINDOW[0][0])
    # the run ends on the day after the last month it covers - the same
    # convention the per-model panels use, so the multi-model graphic and
    # the site caption say the same thing
    import calendar
    from datetime import date as _date, timedelta as _td
    _y, _m = WINDOW[-1]
    _end = _date(_y, _m, calendar.monthrange(_y, _m)[1]) + _td(days=1)
    d1 = "%02d/%02d/%04d" % (_end.month, _end.day, _end.year)
    contrib = ("" if nmin == nmax else
               " · %d–%d of them contributing by month" % (nmin, nmax))
    sub = ("Mean of %d seasonal systems (%s) · 1° × 1° grid · %s to %s · inches%s"
           % (len(fields), names, d0, d1, contrib))
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
        msub = ("Mean of %d seasonal systems (%s) · 1° × 1° grid · %s · "
                "lead month %d of %d · %d contributing · inches"
                % (len(fields), names, "%s %d" % (MN[m], y), k, len(WINDOW),
                   counts[ym]))
        draw_map(os.path.join(OUT, "snow_c3s-multi_month%02d_in.png" % k),
                 "C3S Multi-Model Mean  Snowfall — %s %d" % (MN[m], y),
                 msub, mean[ym], X, Y, in_us, relief, states, provs, countries,
                 wm_cmap, BoundaryNorm(wm_levels, wm_cmap.N, clip=True), wm_levels,
                 "Accumulated snowfall (inches)", white_below=float(wm_levels[0]))
    # drop the panels of a longer previous window
    for f in sorted(os.listdir(OUT)):
        if f.startswith("snow_c3s-multi_month") and f.endswith(".png"):
            if f not in man:
                os.remove(os.path.join(OUT, f))
                print("  removed stale", f)
    json.dump(man, open(man_p, "w"), indent=1)
    print("rendered %d monthly panels" % len(WINDOW), flush=True)


if __name__ == "__main__":
    main()
