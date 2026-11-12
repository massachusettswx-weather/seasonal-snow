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
# The colour ladder, sampled from the reference figure's own colour bar.
# Sixteen bands with pointed ends: the breaks are the reference's tick
# values, and the colours are the reference's, read out of its colour bar
# pixel by pixel.  The palette runs deep blue -> blue -> pale blue ->
# white -> yellow -> orange -> red -> dark red, which is NOT RdBu (that
# goes straight from blue to red through a grey-white and has no yellow).
REF_BREAKS = [-6, -5, -4, -3, -2, -1.5, -1, -0.5, -0.2,
              0.2, 0.5, 1, 1.5, 2, 3, 4, 5, 6]
REF_COLORS = [
    "#000e4e", "#00238c", "#0045b5", "#0c6fd3", "#359fe8", "#6bbef0",
    "#a8daf5", "#daeef8", "#ffffff", "#fff685", "#ffff00", "#ffb700",
    "#ff7300", "#ff3300", "#e20000", "#ac0202", "#6b0000",
]

# the reference's right-hand axis: the approximate altitude of each pressure
# level, in km and miles.  These are the reference's own numbers, not a
# computed barometric height.  The right axis is LINEAR in altitude over the
# same box as the log-pressure axis, so the two are independent scales.
REF_ALT_TICKS = [(0, 0), (8, 5), (16, 10), (24, 15), (32, 20)]
REF_ALT_TOP = 32.2          # the top of the box, a shade above the 32 km tick


def _alt_label(km, mi):
    return "%d km · %d mi" % (km, mi)


def plot_section(times, norm, levels, out_path, title, subtitle,
                 split=None, split_label="", credit=None, handle="@Massachusettswx",
                 vmax=5.0, analysis_label=None, forecast_label=None):
    """Draw the time-height section.

    times:  (n,)   ISO strings
    norm:   (n, nlev) the normalised anomaly
    levels: (nlev,) the pressure levels, hPa
    split:  the index where the forecast begins, or None

    The geometry follows the reference: a LOG pressure axis with 10 hPa at
    the top and 1000 hPa at the bottom, a separate LINEAR altitude axis on
    the right, the section filled with smooth contours (not blocky cells),
    and the colour bar below with pointed ends.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap

    cmap = ListedColormap(REF_COLORS)
    edges = np.array(REF_BREAKS, float)
    norm_c = BoundaryNorm(edges, cmap.N, clip=False)

    lev = np.asarray(levels, float)
    order = np.argsort(lev)               # ascending, for the contour
    lev = lev[order]
    z = np.asarray(norm, float)[:, order].T      # (nlev, ntime)

    n = len(times)
    x = np.arange(n)

    fig_w = 13.6
    fig_h = 8.4
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor="white")
    ax = fig.add_axes([0.068, 0.175, 0.805, 0.665])
    ax.set_facecolor("white")

    # the reference draws smooth contours on a log pressure axis
    pcol = ax.contourf(x, lev, z, levels=edges, cmap=cmap, norm=norm_c,
                        extend="both")
    ax.set_yscale("log")
    ax.set_ylim(1000.0, 10.0)

    # the pressure ticks: the reference's own set
    have = set(int(x) for x in lev)
    shown = [p for p in (1000, 700, 500, 300, 200, 100, 50, 30, 10) if p in have]
    ax.set_yticks(shown)
    ax.set_yticklabels(["%d" % p for p in shown], fontsize=10)
    ax.set_ylabel("Pressure (hPa)", fontsize=11)

    # the date labels: about nine of them, and never two that overlap
    step = max(1, n // 9)
    idx = list(range(0, n, step))
    # the last tick is the final day, but only if it is far enough from the
    # one before it - otherwise the two labels collide.  The test is against
    # the tick that would be second to last, not the one currently there.
    if idx[-1] != n - 1:
        if (n - 1) - idx[-1] >= step * 0.6:
            idx.append(n - 1)
        else:
            idx[-1] = n - 1
    # and no two labels may sit closer than the space a date needs: a label
    # is about ten characters, so the gap has to be a real fraction of the
    # panel.  The last tick always stays.
    while len(idx) > 2:
        gaps = [(idx[i + 1] - idx[i]) for i in range(len(idx) - 1)]
        if min(gaps) >= step * 0.75:
            break
        # drop the tighter of the two neighbours of the worst gap, keeping
        # the first and the last
        j = int(np.argmin(gaps))
        if j == 0:
            del idx[1]
        elif j == len(gaps) - 1:
            del idx[-2]
        else:
            del idx[j + 1]
    ax.set_xticks(idx)
    ax.set_xticklabels([times[i][:10] for i in idx], fontsize=9)
    ax.set_xlim(-0.5, n - 0.5)

    # the light dotted grid the reference has
    ax.grid(True, color="#bbbbbb", linestyle=(0, (1, 3)), lw=0.6, alpha=0.7)

    # the approximate altitude on the right: a LINEAR scale over the same
    # box, so it does not share the log-pressure geometry
    ax2 = ax.twinx()
    ax2.set_yscale("linear")
    ax2.set_ylim(0.0, REF_ALT_TOP)
    ax2.set_yticks([t[0] for t in REF_ALT_TICKS])
    ax2.set_yticklabels([_alt_label(*t) for t in REF_ALT_TICKS],
                        fontsize=9, color="#333333")
    ax2.set_ylabel("Approx. Altitude (km / miles)", fontsize=10.5, color="#333333")

    ax.spines["top"].set_visible(False)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax.tick_params(length=3)

    # the boundary between the analysis and the forecast
    if split is not None and 0 < split < n:
        ax.axvline(split - 0.5, color="#c0392b", lw=1.6, ls=(0, (5, 3)))
    # the reference labels the two sides along the top
    if analysis_label and split:
        ax.text((split - 0.5) / 2.0, 1.02, "◄ %s" % analysis_label,
                transform=ax.get_xaxis_transform(), fontsize=10.5,
                color="#12467f", ha="center", va="bottom", fontweight="bold")
    if forecast_label and split and split < n:
        ax.text((split - 0.5 + n) / 2.0, 1.02, "%s ►" % forecast_label,
                transform=ax.get_xaxis_transform(), fontsize=10.5,
                color="#c0392b", ha="center", va="bottom", fontweight="bold")

    # the titles, centred over the panel the way the reference has them
    fig.text(0.4705, 0.962, title, fontsize=15, fontweight="bold", ha="center",
             va="top")
    fig.text(0.4705, 0.925, subtitle, fontsize=10, color="#333333", ha="center",
             va="top")

    # the colour bar, below the panel, with pointed ends like the reference
    cax = fig.add_axes([0.225, 0.085, 0.50, 0.022])
    cb = fig.colorbar(pcol, cax=cax, orientation="horizontal",
                      boundaries=edges, ticks=edges[1:-1], extend="both",
                      spacing="uniform")
    cb.ax.set_xticklabels(["%g" % e for e in edges[1:-1]], fontsize=8)
    cb.outline.set_visible(False)
    cb.ax.tick_params(length=2)
    fig.text(0.475, 0.050, "Polar Cap (60°-90°N) Normalized Geopotential "
             "Height Anomaly (σ)", fontsize=10.5, ha="center", va="center",
             fontweight="bold")

    if credit:
        fig.text(0.975, 0.018, credit, fontsize=6.0, color="#555555",
                 ha="right", va="bottom", linespacing=1.35)
    if handle:
        fig.text(0.975, 0.046, handle, fontsize=9.5, fontweight="bold",
                 color="#111111", ha="right", va="bottom")

    fig.savefig(out_path, dpi=150, facecolor="white")
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    print("the levels:", LEVELS)
    print("the module is meant to be imported")
