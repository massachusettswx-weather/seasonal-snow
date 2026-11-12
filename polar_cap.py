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


def read_grib_levels(path, levels=None):
    """-> (times, {level: polar cap mean geopotential height}).

    Reads a GRIB with geopotential on pressure levels and reduces each
    field to the polar cap mean.  Returns the times as ISO date strings
    (hourly resolution kept in the key) and the values in m**2 s**-2.

    An ENSEMBLE file carries every member at the same valid time and level,
    so the member values are averaged: the section shows the ensemble mean,
    and a file with one member (a control run) comes through unchanged.
    """
    import eccodes
    from datetime import datetime, timedelta
    from collections import defaultdict
    acc = defaultdict(lambda: defaultdict(list))
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
                    v = v.reshape(nj, ni)
                else:
                    lats = np.unique(la)[::-1]
                    lons = np.unique(lo)
                    if v.size != lats.size * lons.size:
                        continue
                    v = v.reshape(len(lats), len(lons))
                    lat2d = np.repeat(lats[:, None], len(lons), axis=1)
                lats = lat2d[:, 0]
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
            except Exception:
                pass
            finally:
                eccodes.codes_release(gid)
    out = {t: {lev: float(np.mean(vals)) for lev, vals in d.items()}
           for t, d in acc.items()}
    times = sorted(out)
    return times, out


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
# The colour ladder is this site's own: a navy-to-white-to-orange diverging
# ramp built from the colours the rest of the site already uses (the navy of
# the ensemble mean, the orange of the ERA5 trace).  It is NOT the ramp of
# any published figure.
BREAKS = [-6, -5, -4, -3, -2, -1.5, -1, -0.5, -0.2,
          0.2, 0.5, 1, 1.5, 2, 3, 4, 5, 6]
COLORS = [
    # nine blues, from the site's navy out to a pale tint
    "#071a33", "#0b2545", "#123a63", "#1a4f7d", "#27659a",
    "#3d80b6", "#5f9dcd", "#8bb9de", "#cfe3f2",
    # the white centre
    "#ffffff",
    # seven warms, into the site's orange
    "#fbe3c4", "#f4c184", "#e89a4a", "#dc7a26", "#c85c17",
    "#a53f10", "#7d2409",
]

# the house colours, the same ones the zonal-wind panels use
C_TEXT = "#1f2937"
C_MUTED = "#6b7280"
C_GRID = "#d6d3d1"
C_SPLIT = "#12263f"
C_TODAY = "#9d174d"

# the approximate height of the pressure levels, for the right-hand axis.
# A standard atmosphere, not a table lifted from anywhere.
def _height_km(p):
    import math
    return 0.288 * 1000.0 * math.log(1013.25 / p) / 0.0065 / 1000.0 * 10.0


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

    fig_w = 13.5
    fig_h = 7.6
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor="white")
    ax = fig.add_axes([0.058, 0.165, 0.855, 0.645])
    ax.set_facecolor("white")

    # The panel is drawn in three pieces so the reader can tell them apart:
    # the reanalysis is what happened and is drawn at full strength, the
    # model's own days that have already passed are drawn a little lighter,
    # and the days the model is still forecasting are lighter still.
    segs = []
    if split is not None and 0 < split < n:
        segs.append((0, split, 1.0))
        mid = today if (today is not None and split < today < n) else n
        segs.append((split, mid, 0.82))
        if mid < n:
            segs.append((mid, n, 0.58))
    else:
        mid = today if (today is not None and 0 < today < n) else n
        if mid < n:
            segs.append((0, mid, 0.82))
            segs.append((mid, n, 0.58))
        else:
            segs.append((0, n, 0.82))

    p1 = None
    for a, b, alpha in segs:
        if b <= a:
            continue
        p1 = ax.contourf(x[a:b], lev, z[:, a:b], levels=edges, cmap=cmap,
                         norm=norm_c, extend="both", alpha=alpha)  # the ends are drawn, the bar is not pointed

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
    ax.set_xticklabels([times[i][:10] for i in idx], fontsize=9, color=C_TEXT)
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
    if today is not None and 0 <= today < n:
        ax.axvline(today, color=C_TODAY, lw=1.1, ls=(0, (1.5, 2.5)), zorder=6)

    # the titles: left aligned, the way the rest of the site does it
    fig.text(0.058, 0.968, title, fontsize=15.5, fontweight="bold",
             ha="left", va="top", color=C_TEXT)
    if subtitle:
        fig.text(0.058, 0.921, subtitle, fontsize=9.5, color=C_MUTED,
                 ha="left", va="top")

    # the two sides are named above the panel
    if analysis_label and split:
        fig.text(0.062, 0.845, analysis_label, fontsize=10,
                 fontweight="bold", color=C_SPLIT, ha="left", va="bottom")
    if forecast_label:
        fig.text(0.908, 0.845, forecast_label, fontsize=10,
                 fontweight="bold", color=C_SPLIT, ha="right", va="bottom")
    if today is not None and 0 <= today < n:
        ax.text(today, 1.004, "now", transform=ax.get_xaxis_transform(),
                fontsize=9, color=C_TODAY, ha="center", va="bottom")

    # the colour bar, below the panel.  It is drawn from a clean mappable so
    # that it always shows the colours at full strength, whatever the
    # shading of the panel above.
    from matplotlib.cm import ScalarMappable
    sm = ScalarMappable(norm=norm_c, cmap=cmap)
    sm.set_array([])
    cax = fig.add_axes([0.245, 0.082, 0.48, 0.019])
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal",
                      boundaries=edges, ticks=edges[1:-1], extend="neither",
                      spacing="uniform")
    cb.ax.set_xticklabels(["%g" % e for e in edges[1:-1]], fontsize=8,
                          color=C_TEXT)
    cb.outline.set_visible(True)
    cb.outline.set_edgecolor("#c8c5c2")
    cb.outline.set_linewidth(0.8)
    cb.ax.tick_params(length=2, colors=C_TEXT)
    fig.text(0.485, 0.040, "Normalised geopotential height anomaly (σ)",
             fontsize=10.5, ha="center", va="center", fontweight="bold",
             color=C_TEXT)

    if credit:
        fig.text(0.985, 0.016, credit, fontsize=6.0, color="#777777",
                 ha="right", va="bottom", linespacing=1.35)
    if handle:
        fig.text(0.985, 0.044, handle, fontsize=9.5, fontweight="bold",
                 color=C_TEXT, ha="right", va="bottom")

    fig.savefig(out_path, dpi=150, facecolor="white")
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    print("the levels:", LEVELS)
    print("the module is meant to be imported")
