"""Polar cap (60-90N) geopotential height: the zonal-mean machinery.

The reference figure is a time-height section of the polar cap geopotential
height anomaly, normalised by the climatological standard deviation.  It
needs three things, and this module owns all three:

  1. the polar cap mean of the geopotential height on a set of pressure
     levels, area weighted over 60-90N (cos(lat) weights), for a set of
     times;
  2. the ERA5 1991-2020 climatology of that quantity, per calendar day, so
     the anomaly can be taken and then divided by sigma;
  3. the drawing routine that lays the result out as a time-height section
     with a pressure axis on the left and an approximate-altitude axis on
     the right.

The two data sources are the same for every model:

  * ERA5 (the analysis) comes from the CDS "ERA5 post-processed daily
    statistics on pressure levels" product, requested over the polar cap
    only, which gives daily means for the whole 1991-2020 record;
  * the forecast comes from the seasonal sub-daily archive
    ("seasonal-original-pressure-levels"), which carries geopotential on
    exactly the twelve levels the reference uses, at every 12-hourly step
    out to 215 days.

The zonal mean is taken the same way everywhere, so an ECMWF member and an
ERA5 day are directly comparable.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# the levels the C3S seasonal archive serves, in the order it serves them
LEVELS = [10, 30, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]

# the polar cap: 60N to the pole
CAP_N = 90.0
CAP_S = 60.0


# ---------------------------------------------------------------- the zonal mean
def cap_weights(lat):
    """The area weights (cos(lat)) for the polar cap band.

    The comparison is made with a tolerance: the grids this runs on store
    their latitudes as floating point, and ARCO's 60N row is
    59.999999999999986 - an exact comparison drops the bottom row of the
    cap, which shifts the mean.
    """
    lat = np.asarray(lat, float)
    w = np.cos(np.deg2rad(lat))
    inside = (lat >= CAP_S - 1e-6) & (lat <= CAP_N + 1e-6)
    return np.where(inside, w, 0.0)


def zonal_mean(field, lat):
    """The area-weighted zonal mean of a 2-D field over the polar cap.

    field: (nlat, nlon); lat: (nlat,)
    -> a single number

    The denominator is n_lon * sum(w): the polar cap is a band of latitudes
    that wraps the whole globe, so every longitude is present at every
    latitude in the band.  Getting this wrong inflates the mean by
    n_lon / n_lat_used.
    """
    w = cap_weights(lat)
    used = w > 0
    if not used.any():
        return np.nan
    nlon = field.shape[1]
    ww = w[used]
    return float((field[used, :] * ww[:, None]).sum() / (nlon * ww.sum()))


def sector_mean(field, lat, lon, lon0, lon1):
    """The area-weighted zonal mean of a 2-D field over ONE longitude sector.

    field: (nlat, nlon); lat: (nlat,); lon: (nlon,) in degrees east
    lon0 -> lon1, going east; the sector wraps if lon1 < lon0.

    The same reduction as the full cap mean, but only over the longitudes
    of the sector: the field is averaged east-west over the sector at every
    latitude of the band, and then weighted by cos(lat).
    """
    w = cap_weights(lat)
    used = w > 0
    if not used.any():
        return np.nan
    lons = np.asarray(lon, float) % 360.0
    if lon1 >= lon0:
        m = (lons >= lon0) & (lons < lon1)
    else:
        m = (lons >= lon0) | (lons < lon1)
    if not m.any():
        return np.nan
    f = field[used, :][:, m]
    ww = w[used][:, None]
    return float((f * ww).sum() / (float(m.sum()) * ww.sum()))


# The polar cap split into two sectors, so that a warming over one ocean
# can be told from a warming over the other - the Atlantic and the Pacific
# do not warm together, and the difference between them is the story.
# The sectors are 120 degrees wide and do not overlap: the Atlantic runs
# from 300E to 60E, the Pacific from 120E to 240E, and the Arctic sector
# (240E to 300E) is left out.
SECTORS = {
    "natl": (300.0, 60.0),
    "npac": (120.0, 240.0),
}
SECTOR_LABELS = {
    "natl": "North Atlantic",
    "npac": "North Pacific",
}


def read_grib_levels(path, levels=None):
    """-> (times, {level: polar cap mean geopotential height}).

    Reads a GRIB with geopotential on pressure levels and reduces each
    field to the polar cap mean.  Returns the times as ISO date strings
    (hourly resolution kept in the key) and the values in m**2 s**-2.

    An ENSEMBLE file carries every member at the same valid time and level,
    so the member values are averaged: the section shows the ensemble mean,
    and a file with one member (a control run) comes through unchanged.
    """
    times, cap, _sector = read_grib_levels_sectors(path, levels)
    return times, cap


def read_grib_levels_sectors(path, levels=None):
    """-> (times, cap, sectors).

    cap:    {time: {level: the polar cap mean}}
    sectors: {time: {sector: {level: the sector mean}}}

    The same reduction as read_grib_levels, plus the sector means, so one
    pass over the file serves both.
    """
    import eccodes
    from datetime import datetime, timedelta
    from collections import defaultdict
    acc = defaultdict(lambda: defaultdict(list))
    sacc = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                lo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                ni = int(eccodes.codes_get(gid, "Ni", 0) or 0)
                nj = int(eccodes.codes_get(gid, "Nj", 0) or 0)
                if ni and nj and v.size == ni * nj:
                    lat2d = la.reshape(nj, ni)
                    lon2d = lo.reshape(nj, ni)
                    v = v.reshape(nj, ni)
                else:
                    lats = np.unique(la)[::-1]
                    lons = np.unique(lo)
                    if v.size != lats.size * lons.size:
                        continue
                    v = v.reshape(len(lats), len(lons))
                    lat2d = np.repeat(lats[:, None], len(lons), axis=1)
                    lon2d = np.repeat(lons[None, :], len(lats), axis=0)
                lats = lat2d[:, 0]
                lons = lon2d[0, :]
                # the valid time: eccodes' own validityDate/validityTime
                # already carry the reference time plus the forecast step,
                # and they are the same for a reanalysis (12Z, step 0) and
                # for a seasonal run (the 00Z init plus the lead time).
                # Reading dataDate/dataTime/step instead puts every ERA5
                # field at 00Z and every seasonal field a whole day out.
                try:
                    vd = int(eccodes.codes_get(gid, "validityDate"))
                    vt = int(eccodes.codes_get(gid, "validityTime"))
                    valid = datetime(vd // 10000, (vd // 100) % 100, vd % 100) \
                        + timedelta(hours=vt // 100, minutes=vt % 100)
                except Exception:
                    dd = int(eccodes.codes_get(gid, "dataDate"))
                    tt = int(eccodes.codes_get(gid, "dataTime", 0) or 0)
                    st = int(eccodes.codes_get(gid, "step", 0) or 0)
                    valid = datetime(dd // 10000, (dd // 100) % 100, dd % 100) \
                        + timedelta(hours=tt // 100, minutes=tt % 100) \
                        + timedelta(hours=st)
                lev = int(eccodes.codes_get(gid, "level"))
                key = valid.strftime("%Y-%m-%d %H")
                acc[key][lev].append(zonal_mean(v, lats))
                for name, (a, b) in SECTORS.items():
                    sacc[key][name][lev].append(
                        sector_mean(v, lats, lons, a, b))
            except Exception:
                pass
            finally:
                eccodes.codes_release(gid)
    out = {t: {lev: float(np.mean(vals)) for lev, vals in d.items()}
           for t, d in acc.items()}
    sout = {t: {name: {lev: float(np.mean(vals)) for lev, vals in ld.items()}
                for name, ld in sd.items()}
            for t, sd in sacc.items()}
    times = sorted(out)
    return times, out, sout


# ---------------------------------------------------------------- the climatology
def build_climatology(clim_path, out_path=None):
    """Build the ERA5 1991-2020 polar cap climatology.

    clim_path: an npz with
        times   : (n,)   ISO "YYYY-MM-DD" daily strings
        levels  : (nlev,) the pressure levels
        values  : (n, nlev) the polar cap mean geopotential height

    Writes an npz with, per calendar day (mm-dd) and level, the mean, the
    standard deviation and the count of the 1991-2020 samples.  A month is
    given its own entry where the record is long enough.
    """
    d = np.load(clim_path, allow_pickle=True)
    times = [str(t) for t in d["times"]]
    levels = [int(x) for x in d["levels"]]
    values = np.asarray(d["values"], float)

    from collections import defaultdict
    by_md = defaultdict(list)
    for i, t in enumerate(times):
        if t[:4] in [str(y) for y in range(1991, 2021)]:
            by_md[t[5:10]].append(values[i])

    out = {}
    for md, arr in by_md.items():
        a = np.asarray(arr, float)
        good = np.isfinite(a).all(axis=1)
        a = a[good]
        if a.size == 0:
            continue
        out[md] = {
            "n": int(a.shape[0]),
            "mean": a.mean(axis=0).tolist(),
            "sigma": a.std(axis=0, ddof=1).tolist() if a.shape[0] > 1
                     else [0.0] * len(levels),
        }
    res = {"levels": np.array(levels), "days": np.array(sorted(out))}
    res["mean"] = np.array([out[m]["mean"] for m in sorted(out)], float)
    res["sigma"] = np.array([out[m]["sigma"] for m in sorted(out)], float)
    res["count"] = np.array([out[m]["n"] for m in sorted(out)], int)
    p = out_path or os.path.join(DATA, "polar_cap_clim.npz")
    np.savez_compressed(p, **res)
    return p


def load_climatology(path=None):
    """-> (days, levels, mean, sigma) with the day-of-year lookup."""
    p = path or os.path.join(DATA, "polar_cap_clim.npz")
    d = np.load(p, allow_pickle=True)
    days = [str(x) for x in d["days"]]
    return days, [int(x) for x in d["levels"]], d["mean"], d["sigma"]


def normalise(times, values, levels, clim):
    """Turn polar cap means into the normalised anomaly.

    times:  (n,)    ISO "YYYY-MM-DD" or "YYYY-MM-DD HH"
    values: (n, nlev)
    levels: (nlev,)

    The climatology is keyed by calendar day, so a value is looked up by
    its month and day.  A day with no climatological entry falls back to
    the nearest day in the same month.
    """
    days, clevels, cmean, csigma = clim
    lev_index = {l: i for i, l in enumerate(levels)}
    cidx = {l: i for i, l in enumerate(clevels)}
    mean = np.full((len(times), len(levels)), np.nan)
    sigma = np.full((len(times), len(levels)), np.nan)
    for i, t in enumerate(times):
        md = t[5:10]
        if md not in days:
            # the nearest day in the same month
            cands = [d for d in days if d[3:] == md[3:]]
            if not cands:
                cands = days
            md = min(cands, key=lambda d: abs(int(d[:2]) - int(md[:2])))
        j = days.index(md)
        for l in levels:
            if l in lev_index and l in cidx:
                mean[i, lev_index[l]] = cmean[j, cidx[l]]
                sigma[i, lev_index[l]] = csigma[j, cidx[l]]
    anom = values - mean
    with np.errstate(invalid="ignore", divide="ignore"):
        norm = np.where(sigma > 0, anom / sigma, np.nan)
    return anom, norm


# ---------------------------------------------------------------- the drawing
# The colour ladder is a diverging ramp: the site's navy through the blues
# to a pale tint, a white centre, then pale yellow into yellow, amber,
# orange and the site's own deep red.  The colours are this site's own;
# the LAYOUT is ours too - nothing here is lifted from a published figure.
#
# The field is the geopotential height ANOMALY IN METRES, not a normalised
# one.  A normalised anomaly needs a climatology of its own for every system
# - and the subseasonal guidance has no hindcast to build one from - while a
# height anomaly in metres can be put straight next to the reanalysis.  The
# trade-off is that the anomaly is much larger in the stratosphere than in
# the troposphere, so the scale is set by the stratosphere.
#
# The scale runs to +/-2000 m: the stratospheric warming of early November
# 2026 put the polar cap about 1700 m above its 1991-2020 mean at 10 hPa,
# so a +/-600 m scale showed nothing but a solid red.  The steps are fine
# near zero and coarse at the ends, the same shape as the reference's
# normalised ladder, so an ordinary day's anomaly still reads.
BREAKS = [-2000, -1600, -1270, -1000, -770, -570, -380, -200, -60,
          60, 200, 380, 570, 770, 1000, 1270, 1600, 2000]
COLORS = [
    # nine blues: a saturated royal blue out to a pale tint.  The deep end
    # is a COLOURED blue, not a near-black navy - a dark, desaturated end
    # reads as a hole in the chart rather than as a strong cold anomaly.
    "#1017c4", "#101fda", "#1230ec", "#1c4cf1", "#3a77f4",
    "#5c9cf7", "#87befa", "#b2d6fb", "#d9e9fc",
    # the white centre
    "#ffffff",
    # seven warms: a bright yellow, then gold, orange, vermilion, a vivid
    # red and a deep red.  These are the saturated colours, not the dusty
    # ones - a muted ramp makes a strong anomaly look like a weak one.
    "#fff45a", "#fdc742", "#f79030", "#ee6326", "#ea4220",
    "#d52c1b", "#b22318",
]

# the house colours, the same ones the zonal-wind panels use
C_TEXT = "#1f2937"
C_MUTED = "#6b7280"
C_GRID = "#d6d3d1"
C_SPLIT = "#12263f"
C_TODAY = "#9d174d"

# the standard gravity, for turning a geopotential into a height
G0 = 9.80665

# the approximate height of the pressure levels, for the right-hand axis.
# A standard atmosphere, not a table lifted from anywhere.
def _height_km(p):
    import math
    return 0.288 * 1000.0 * math.log(1013.25 / p) / 0.0065 / 1000.0 * 10.0


def _short_date(t):
    """'13 Nov' - the full date is too wide when the run is short."""
    t = str(t)
    try:
        import datetime as _dt
        d = _dt.date.fromisoformat(t[:10])
        return "%d %s" % (d.day, ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                  "Jul", "Aug", "Sep", "Oct", "Nov",
                                  "Dec")[d.month - 1])
    except Exception:
        return t[:10]


def _alt_label(km):
    return "%d km" % round(km)


def plot_section(times, norm, levels, out_path, title, subtitle,
                 split=None, split_label="", credit=None, handle="@Massachusettswx",
                 vmax=5.0, analysis_label=None, forecast_label=None,
                 today=None, forecast_alpha=0.55):
    """Draw the time-height section.

    times:  (n,)   ISO strings
    norm:   (n, nlev) the normalised anomaly
    levels: (nlev,) the pressure levels, hPa
    split:  the index where the forecast begins, or None
    today:  the index of "now", drawn as a marker

    The layout is this site's own: a bold title and a grey descriptor line
    on the LEFT, a plain-text summary on the right, the colour bar below
    the panel and the handle bottom right.  The analysis is drawn at full
    strength and the forecast at a lighter one, so what has happened and
    what might happen are told apart at a glance.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap

    cmap = ListedColormap(COLORS)
    edges = np.array(BREAKS, float)
    norm_c = BoundaryNorm(edges, cmap.N, clip=False)

    lev = np.asarray(levels, float)
    order = np.argsort(lev)
    lev = lev[order]
    z = np.asarray(norm, float)[:, order].T      # (nlev, ntime)

    n = len(times)
    x = np.arange(n)

    # The figure is kept short and the panel is given most of it: the first
    # version of this chart carried a wide band of empty white above the
    # panel and a deep band under it, and the panel itself was squashed.
    fig_w = 13.5
    fig_h = 7.0
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor="white")
    ax = fig.add_axes([0.052, 0.148, 0.876, 0.700])
    ax.set_facecolor("white")

    # The panel is drawn in one piece.  It used to be drawn in three, each
    # with its own shading, and a contourf only fills the columns it is
    # given - so the day before the "now" line was never filled and the
    # chart carried a white stripe down it.  The reanalysis is still picked
    # out: it is drawn a second time, a little stronger, over the columns
    # it covers.
    mid = today if (today is not None and 0 < today < n) else n
    if split is not None and 0 < split < n:
        # what happened, at full strength; what the model says, lighter.
        # The last column is shared with the panel below it, so the two meet
        # with no gap.
        ax.contourf(x, lev, z, levels=edges, cmap=cmap,
                    norm=norm_c, extend="both", alpha=0.62)
        ax.contourf(x[:split + 1], lev, z[:, :split + 1], levels=edges,
                    cmap=cmap, norm=norm_c, extend="both", alpha=1.0)
    else:
        # no reanalysis in front of the run: the model's own forecast is
        # the whole panel, and it is drawn at full strength.
        ax.contourf(x, lev, z, levels=edges, cmap=cmap,
                    norm=norm_c, extend="both", alpha=1.0)

    ax.set_yscale("log")
    ax.set_ylim(1000.0, 10.0)

    # the pressure ticks
    have = set(int(v) for v in lev)
    shown = [p for p in (1000, 700, 500, 400, 300, 200, 100, 50, 30, 10) if p in have]
    ax.set_yticks(shown)
    ax.set_yticklabels(["%d" % p for p in shown], fontsize=10, color=C_TEXT)
    ax.set_ylabel("Pressure (hPa)", fontsize=11, color=C_TEXT, labelpad=8)

    # the date labels: about nine of them, and never two that overlap
    step = max(1, n // 9)
    idx = list(range(0, n, step))
    if idx[-1] != n - 1:
        if (n - 1) - idx[-1] >= step * 0.6:
            idx.append(n - 1)
        else:
            idx[-1] = n - 1
    while len(idx) > 2:
        gaps = [(idx[i + 1] - idx[i]) for i in range(len(idx) - 1)]
        if min(gaps) >= step * 0.75:
            break
        j = int(np.argmin(gaps))
        if j == 0:
            del idx[1]
        elif j == len(gaps) - 1:
            del idx[-2]
        else:
            del idx[j + 1]
    ax.set_xticks(idx)
    ax.set_xticklabels([_short_date(times[i]) for i in idx], fontsize=9,
                        color=C_TEXT)
    ax.set_xlim(-0.5, n - 0.5)

    ax.grid(True, color=C_GRID, linestyle=(0, (1, 3)), lw=0.6, alpha=0.8)
    ax.xaxis.grid(True)
    ax.yaxis.grid(True)

    # the approximate height on the right, in this site's own thin grey
    ax2 = ax.twinx()
    ax2.set_yscale("linear")
    ax2.set_ylim(0.0, 33.0)
    hticks = [(0, 0), (8, 5), (16, 10), (24, 15), (32, 20)]
    ax2.set_yticks([t[0] for t in hticks])
    ax2.set_yticklabels([_alt_label(t[0]) for t in hticks], fontsize=9,
                        color=C_MUTED)
    ax2.set_ylabel("Approximate height", fontsize=10, color=C_MUTED,
                   labelpad=10)
    ax2.tick_params(axis="y", length=3, colors=C_MUTED)

    ax.spines["top"].set_visible(False)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#9ca3af")
        ax.spines[s].set_linewidth(0.9)
    ax2.spines["right"].set_color("#9ca3af")
    ax2.spines["right"].set_linewidth(0.9)
    ax.tick_params(length=3, colors=C_TEXT)

    # the boundary between the analysis and the forecast
    if split is not None and 0 < split < n:
        ax.axvline(split - 0.5, color=C_SPLIT, lw=1.3, ls=(0, (5, 3)),
                   zorder=6)

    # the titles: left aligned, the way the rest of the site does it
    fig.text(0.052, 0.968, title, fontsize=15.5, fontweight="bold",
             ha="left", va="top", color=C_TEXT)
    if subtitle:
        fig.text(0.052, 0.921, subtitle, fontsize=9.5, color=C_MUTED,
                 ha="left", va="top")

    # the two sides are named just above the panel
    if analysis_label and split:
        fig.text(0.056, 0.858, analysis_label, fontsize=10,
                 fontweight="bold", color=C_SPLIT, ha="left", va="bottom")
    if forecast_label:
        fig.text(0.924, 0.858, forecast_label, fontsize=10,
                 fontweight="bold", color=C_SPLIT, ha="right", va="bottom")

    # the colour bar, below the panel.  It is drawn from a clean mappable so
    # that it always shows the colours at full strength, whatever the
    # shading of the panel above.
    from matplotlib.cm import ScalarMappable
    sm = ScalarMappable(norm=norm_c, cmap=cmap)
    sm.set_array([])
    cax = fig.add_axes([0.245, 0.076, 0.48, 0.018])
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal",
                      boundaries=edges, ticks=edges[1:-1], extend="neither",
                      spacing="uniform")
    cb.ax.set_xticklabels(["%g" % e for e in edges[1:-1]], fontsize=8,
                          color=C_TEXT)
    cb.outline.set_visible(True)
    cb.outline.set_edgecolor("#c8c5c2")
    cb.outline.set_linewidth(0.8)
    cb.ax.tick_params(length=2, colors=C_TEXT)
    fig.text(0.485, 0.030, "Geopotential height anomaly (m)",
             fontsize=10.5, ha="center", va="center", fontweight="bold",
             color=C_TEXT)

    if credit:
        fig.text(0.985, 0.007, credit, fontsize=6.0, color="#777777",
                 ha="right", va="bottom", linespacing=1.35)
    if handle:
        fig.text(0.985, 0.032, handle, fontsize=9.5, fontweight="bold",
                 color=C_TEXT, ha="right", va="bottom")

    fig.savefig(out_path, dpi=150, facecolor="white")
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    print("the levels:", LEVELS)
    print("the module is meant to be imported")


def plot_sector_sections(times, sectors, levels, out_path, title, subtitle,
                         split=None, credit=None, handle="@Massachusettswx",
                         order=("npac", "natl"), forecast_alpha=0.62):
    """Draw the polar cap split into two sectors, side by side.

    times:   (n,)    ISO strings
    sectors: {name: (n, nlev)} the geopotential height ANOMALY in metres,
             one array per sector
    levels:  (nlev,) the pressure levels, hPa

    The same figure as the polar-cap section - the same colours, the same
    log pressure axis, the same height axis on the right - with one panel
    per sector.  The Atlantic and the Pacific do not warm together, and the
    difference between them is the story the polar-cap mean hides.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.cm import ScalarMappable

    cmap = ListedColormap(COLORS)
    edges = np.array(BREAKS, float)
    norm_c = BoundaryNorm(edges, cmap.N, clip=False)

    lev = np.asarray(levels, float)
    order_l = np.argsort(lev)
    lev = lev[order_l]

    names = [n for n in order if n in sectors]
    if not names:
        raise ValueError("no sector series to draw")

    n = len(times)
    x = np.arange(n)

    fig_w = 13.5
    fig_h = 6.4
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor="white")

    # the panels: two axes side by side, with a gap between them
    left0, width = 0.062, 0.405
    gap = 0.055
    axes = []
    for i in range(len(names)):
        ax = fig.add_axes([left0 + i * (width + gap), 0.175, width, 0.635])
        axes.append(ax)

    for i, name in enumerate(names):
        ax = axes[i]
        ax.set_facecolor("white")
        z = np.asarray(sectors[name], float)[:, order_l].T     # (nlev, ntime)

        mid = n
        if split is not None and 0 < split < n:
            ax.contourf(x, lev, z, levels=edges, cmap=cmap,
                        norm=norm_c, extend="both", alpha=forecast_alpha)
            ax.contourf(x[:split + 1], lev, z[:, :split + 1], levels=edges,
                        cmap=cmap, norm=norm_c, extend="both", alpha=1.0)
        else:
            ax.contourf(x, lev, z, levels=edges, cmap=cmap,
                        norm=norm_c, extend="both", alpha=1.0)

        ax.set_yscale("log")
        ax.set_ylim(1000.0, 10.0)

        have = set(int(v) for v in lev)
        shown = [p for p in (1000, 700, 500, 400, 300, 200, 100, 50, 30, 10)
                 if p in have]
        ax.set_yticks(shown)
        ax.set_yticklabels(["%d" % p for p in shown], fontsize=9.5,
                           color=C_TEXT)
        ax.set_ylabel("Pressure (hPa)", fontsize=10.5, color=C_TEXT, labelpad=6)

        step = max(1, n // 8)
        idx = list(range(0, n, step))
        if idx[-1] != n - 1:
            if (n - 1) - idx[-1] >= step * 0.6:
                idx.append(n - 1)
            else:
                idx[-1] = n - 1
        while len(idx) > 2:
            gaps = [(idx[j + 1] - idx[j]) for j in range(len(idx) - 1)]
            if min(gaps) >= step * 0.75:
                break
            j = int(np.argmin(gaps))
            if j == 0:
                del idx[1]
            elif j == len(gaps) - 1:
                del idx[-2]
            else:
                del idx[j + 1]
        ax.set_xticks(idx)
        ax.set_xticklabels([_short_date(times[k]) for k in idx], fontsize=8.5,
                           color=C_TEXT)
        ax.set_xlim(-0.5, n - 0.5)

        ax.grid(True, color=C_GRID, linestyle=(0, (1, 3)), lw=0.6, alpha=0.8)
        ax.xaxis.grid(True)
        ax.yaxis.grid(True)

        ax.spines["top"].set_visible(False)
        for sname in ("left", "bottom"):
            ax.spines[sname].set_color("#9ca3af")
            ax.spines[sname].set_linewidth(0.9)
        ax.tick_params(length=3, colors=C_TEXT)

        if split is not None and 0 < split < n:
            ax.axvline(split - 0.5, color=C_SPLIT, lw=1.2, ls=(0, (5, 3)),
                       zorder=6)

        # the panel's own name, above it
        fig.text(left0 + i * (width + gap), 0.822,
                 "%s (%.0f°E-%.0f°E)" % (SECTOR_LABELS.get(name, name),
                                         SECTORS[name][0],
                                         SECTORS[name][1]),
                 fontsize=11, fontweight="bold", color=C_TEXT,
                 ha="left", va="bottom")

    # the height axis, on the far right only
    ax2 = axes[-1].twinx()
    ax2.set_yscale("linear")
    ax2.set_ylim(0.0, 33.0)
    hticks = [(0, 0), (8, 5), (16, 10), (24, 15), (32, 20)]
    ax2.set_yticks([t[0] for t in hticks])
    ax2.set_yticklabels([_alt_label(t[0]) for t in hticks], fontsize=8.5,
                        color=C_MUTED)
    ax2.set_ylabel("Approximate height", fontsize=9.5, color=C_MUTED,
                   labelpad=8)
    ax2.tick_params(axis="y", length=3, colors=C_MUTED)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color("#9ca3af")
    ax2.spines["right"].set_linewidth(0.9)

    fig.text(0.052, 0.968, title, fontsize=15.5, fontweight="bold",
             ha="left", va="top", color=C_TEXT)
    if subtitle:
        fig.text(0.052, 0.918, subtitle, fontsize=9.5, color=C_MUTED,
                 ha="left", va="top")

    sm = ScalarMappable(norm=norm_c, cmap=cmap)
    sm.set_array([])
    cax = fig.add_axes([0.245, 0.082, 0.48, 0.018])
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal",
                      boundaries=edges, ticks=edges[1:-1], extend="neither",
                      spacing="uniform")
    cb.ax.set_xticklabels(["%g" % e for e in edges[1:-1]], fontsize=8,
                          color=C_TEXT)
    cb.outline.set_visible(True)
    cb.outline.set_edgecolor("#c8c5c2")
    cb.outline.set_linewidth(0.8)
    cb.ax.tick_params(length=2, colors=C_TEXT)
    fig.text(0.485, 0.034, "Geopotential height anomaly (m)",
             fontsize=10.5, ha="center", va="center", fontweight="bold",
             color=C_TEXT)

    if credit:
        fig.text(0.985, 0.007, credit, fontsize=6.0, color="#777777",
                 ha="right", va="bottom", linespacing=1.35)
    if handle:
        fig.text(0.985, 0.032, handle, fontsize=9.5, fontweight="bold",
                 color=C_TEXT, ha="right", va="bottom")

    fig.savefig(out_path, dpi=150, facecolor="white")
    plt.close(fig)
    return out_path
