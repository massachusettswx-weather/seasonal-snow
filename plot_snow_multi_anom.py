"""The C3S multi-model mean's monthly snowfall anomalies.

The multi-model mean has a total panel and a panel per lead month, but it had
no anomaly panel - every other centre's snowfall is shown against that
centre's own hindcast climate, and the multi-model was the odd one out.

The baseline here is the multi-model's OWN climate.  Each system's hindcast
climate mean is read from that system's own file and the systems are averaged
exactly the way the forecast is averaged in plot_snow_multi.py: one vote per
system, not one per member.  The ECCC enters once, as the pooled canSIPS
ensemble it already is on disk, so the mean of six systems never becomes the
mean of three hundred and one members.

A panel is only drawn for a lead month where EVERY system in that month's
multi-model mean also has a climate for that same calendar month.  Where a
centre's hindcast climate has not been fetched for that month the baseline
would not be the multi-model's own climate - it would be one centre's, or a
mean over fewer centres than the forecast - so the month is left out and said
so, rather than published with a baseline that is really somebody else's.

Writes:
  output/SNOW_C3S-MULTI_<Month><Year>_anom_in.png
and copies each panel into docs/assets/maps/.

usage: python3 plot_snow_multi_anom.py
"""
import json
import os
import shutil
import sys

import numpy as np
from matplotlib.colors import BoundaryNorm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import init_info                                                    # noqa: E402
from plot_snow_models import (ANOM_LEVELS, ANOM_MASK_CLIM, anom_cmap,   # noqa: E402
                              draw_map, grid_axes, grid_res, interp_to,
                              read_any, read_snowfall, setup_grid, to_2d)
from plot_snow_ref import (LON0, LON1, LAT0, LAT1, MONTH_NAMES)     # noqa: E402
from plot_snow_totals import GRID, month_len                        # noqa: E402
from plot_snow_multi import ALL_MONTHS, MODELS, model_monthly       # noqa: E402

DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
OUT = os.path.join(HERE, "output")
MAPS = os.path.join(HERE, "docs", "assets", "maps")

# the multi-model's own name and tag on the site
TAG = "c3s-multi"
NAME = "C3S Multi-Model Mean"
# the file-name stem, the same convention the per-model panels use
# (SNOW_<TAG>_<Month><Year>_anom_in.png)
STEM = "SNOW_C3S-MULTI"

# the 10:1 snow-to-water ratio.  plot_snow_multi.py hard-codes it when it
# builds the forecast, so the climate has to use the same one or the
# anomaly would be in different units from the panels it sits beside.
RATIO = 10.0

# the display grid - the same one plot_snow_multi.py interpolates onto
_lo = np.arange(LON0, LON1 + GRID / 2, GRID)
_la = np.arange(LAT0, LAT1 + GRID / 2, GRID)
LON, LAT = np.meshgrid(_lo, _la)

NAMES = dict(MODELS)


def model_clim(tag):
    """-> {calendar month: that system's own hindcast climate, inches of snow}.

    The climate is a rate in m w.e. s-1, like the monthly forecast, so it is
    scaled by the length of the month and by the 10:1 snow ratio - the same
    conversion the per-model anomaly panels use.  The records in one file are
    averaged first, which is what puts the ECCC's two systems together.
    """
    d = os.path.join(MDIR, tag)
    cg = os.path.join(d, "snowfall_hindcast.grib")
    if not os.path.exists(cg):
        cg = os.path.join(d, "snowfall_hindcast.npz")
    if not os.path.exists(cg):
        return None            # a centre whose climate has not arrived yet
    recs = read_any(cg)
    if not recs:
        return None
    bym = {}
    for step, ym, la, lo, v in recs:
        bym.setdefault(ym, []).append((la, lo, v))
    out = {}
    for ym, rs in sorted(bym.items()):
        if (ym[0], ym[1]) not in ALL_MONTHS:
            continue
        lats, lons, order = grid_axes(rs[0])
        stack = np.array([to_2d(r, lats, lons, order) for r in rs])
        cm = stack.mean(axis=0)
        y, m = ym
        g = interp_to(LAT.ravel(), LON.ravel(), lats, lons, cm).reshape(LAT.shape)
        out[ym] = g * month_len(y, m) * 86400.0 * 1000.0 / 25.4 * RATIO
    return out


def multi_window(fields):
    """The lead months the multi-model mean covers - the same window
    plot_snow_multi.py draws its monthly panels over."""
    inits = {}
    fp = os.path.join(DATA, "models_fetched.json")
    if os.path.exists(fp):
        for k, v in json.load(open(fp)).items():
            if v.get("init"):
                inits[k] = v["init"]
    latest = max(inits.values()) if inits else init_info.newest_init("ecmwf-seas5")
    first = (int(latest[:4]), int(latest[5:7]))
    return [ym for ym in ALL_MONTHS
            if ym >= first and any(ym in f for f in fields.values())], latest


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(MAPS, exist_ok=True)
    X, Y, _LAT, _LON, in_us, in_mex, relief, countries, states, provs = setup_grid()
    acmap = anom_cmap()
    levels = ANOM_LEVELS * RATIO
    anorm = BoundaryNorm(levels, acmap.N, clip=True)

    # the forecast, read by the multi-model's own reader so the anomaly is
    # measured against exactly the field the monthly panel shows
    fields = {}
    clims = {}
    for tag, name in MODELS:
        f = model_monthly(tag)
        if not f:
            print("  %s: no snowfall on disk - skipped" % tag, flush=True)
            continue
        fields[tag] = f
        clims[tag] = model_clim(tag)
        if not clims[tag]:
            print("  %s: no hindcast climate on disk" % tag, flush=True)
    if not fields:
        print("no C3S models with snowfall")
        return

    # the recorded contributors and the systems that are actually here have
    # to agree, or the multi-model's card and its panels are about different
    # ensembles
    mp = os.path.join(DATA, "multi_members.json")
    if os.path.exists(mp):
        try:
            rec = [x["tag"] for x in json.load(open(mp)).get("models", [])]
            if rec and sorted(rec) != sorted(fields):
                print("  !! multi_members.json says %s but the data has %s"
                      % (", ".join(rec), ", ".join(sorted(fields))), flush=True)
        except Exception:
            pass

    WINDOW, latest = multi_window(fields)
    if not WINDOW:
        print("the models share no calendar month")
        return
    print("window: %s .. %s  (%d systems)" %
          (WINDOW[0], WINDOW[-1], len(fields)), flush=True)

    initlabel = "%s-%s-01 00Z" % (latest[:4], latest[5:7])
    # the resolution note the per-model panels carry, when every system in
    # the mean is on the same grid
    res = ""
    resnotes = set()
    for tag in fields:
        d = os.path.join(MDIR, tag)
        for fn in ("snowfall_monthly.grib", "snowfall_monthly.npz"):
            p = os.path.join(d, fn)
            if not os.path.exists(p):
                continue
            try:
                by = read_snowfall(p)
                if by:
                    la, lo, _o = grid_axes(by[sorted(by)[0]][0])
                    resnotes.add(grid_res(la, lo))
            except Exception:
                pass
            break
    if len(resnotes) == 1:
        res = " · %s grid" % list(resnotes)[0]

    manifest_p = os.path.join(DATA, "render_manifest.json")
    manifest = json.load(open(manifest_p)) if os.path.exists(manifest_p) else {}
    written = []
    summary = []
    for k, ym in enumerate(WINDOW, start=1):
        y, m = ym
        contributors = [t for t in fields if ym in fields[t]]
        withclim = [t for t in contributors
                    if clims.get(t) and ym in clims[t]]
        if len(withclim) != len(contributors):
            missing = [NAMES.get(t, t) for t in contributors if t not in withclim]
            print("  %04d-%02d: no hindcast climate for %s - the baseline "
                  "would not be the multi-model's own, so no anomaly panel"
                  % (y, m, ", ".join(missing)), flush=True)
            continue
        # the forecast: the mean of the systems, each counted once
        fcst = np.array([fields[t][ym] for t in contributors]).mean(axis=0)
        # the climate: the mean of the systems' own hindcast climate means,
        # combined the same way
        base = np.array([clims[t][ym] for t in withclim]).mean(axis=0)
        # an anomaly where the multi-model's own climate expects essentially
        # no snow is noise, not signal: it is masked to white below
        # ANOM_MASK_CLIM inches, exactly as the per-model panels are
        a = np.where(base >= ANOM_MASK_CLIM, fcst - base, np.nan)

        fn = "%s_%s%d_anom_in.png" % (STEM, MONTH_NAMES[m - 1], y)
        outp = os.path.join(OUT, fn)
        title = "%s Snowfall Anomaly  %s %d" % (NAME, MONTH_NAMES[m - 1], y)
        sub = ("Init %s · %d-system ensemble mean%s · lead month %d · "
               "anomaly vs %s hindcast climate · inches" %
               (initlabel, len(fields), res, k, NAME))
        draw_map(outp, title, sub, a, X, Y, in_us, relief, states, provs,
                 countries, acmap, anorm, levels, "Snowfall anomaly (inches)")
        manifest[fn] = {"label": "%s %d" % (MONTH_NAMES[m - 1], y), "lead": k}
        written.append(fn)
        shutil.copyfile(outp, os.path.join(MAPS, fn))
        vm = np.where(in_us, a, np.nan)
        summary.append((fn, len(contributors), np.nanmax(vm), np.nanmin(vm)))
        print("rendered %-42s lead %d · %d systems · max %+.2f in · min %+.2f in"
              % (fn, k, len(contributors), np.nanmax(vm), np.nanmin(vm)),
              flush=True)

    # drop the panels of a longer previous window
    for f in sorted(os.listdir(OUT)):
        if f.startswith(STEM + "_") and f.endswith(".png") and f not in written:
            os.remove(os.path.join(OUT, f))
            print("  removed stale", f)
    for f in sorted(os.listdir(MAPS)):
        if f.startswith(STEM + "_") and f.endswith(".png") and f not in written:
            os.remove(os.path.join(MAPS, f))
            print("  removed stale", f, "from docs/assets/maps")
    for k in [k for k in manifest if k.startswith(STEM + "_")]:
        if k not in written:
            del manifest[k]
    json.dump(manifest, open(manifest_p, "w"), indent=1)

    print("rendered %d anomaly panels" % len(written), flush=True)
    for fn, n, mx, mn in summary:
        print("  %-42s %d systems   max %+.2f in   min %+.2f in" %
              (fn, n, mx, mn))


if __name__ == "__main__":
    main()
