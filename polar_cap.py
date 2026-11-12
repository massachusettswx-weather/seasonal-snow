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
    """The area weights (cos(lat)) for the polar cap band."""
    lat = np.asarray(lat, float)
    w = np.cos(np.deg2rad(lat))
    w = np.where((lat >= CAP_S) & (lat <= CAP_N), w, 0.0)
    return w


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
    """
    import eccodes
    from datetime import datetime, timedelta
    out = {}
    times = []
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
                dd = int(eccodes.codes_get(gid, "dataDate"))
                st = int(eccodes.codes_get(gid, "step", 0) or 0)
                valid = datetime(dd // 10000, (dd // 100) % 100, dd % 100) \
                    + timedelta(hours=st)
                lev = int(eccodes.codes_get(gid, "level"))
                key = valid.strftime("%Y-%m-%d %H")
                out.setdefault(key, {})[lev] = zonal_mean(v, lats)
                if key not in times:
                    times.append(key)
            except Exception:
                pass
            finally:
                eccodes.codes_release(gid)
    times.sort()
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
def plot_section(times, norm, levels, out_path, title, subtitle,
                 split=None, split_label="", credit=None, handle="@Massachusettswx",
                 vmax=5.0):
    """Draw the time-height section.

    times:  (n,)   ISO strings
    norm:   (n, nlev) the normalised anomaly
    levels: (nlev,) the pressure levels, hPa
    split:  the index where the forecast begins, or None
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap

    # the colour ladder, the same shape the reference uses: blue through
    # white to red, with the steps closer together near zero
    edges = np.array([-6, -5, -4, -3, -2, -1.5, -1, -0.5, -0.2,
                      0.2, 0.5, 1, 1.5, 2, 3, 4, 5, 6])
    cmap = plt.get_cmap("RdBu_r").resampled(len(edges) - 1)
    cmap = cmap.reversed()
    norm_c = BoundaryNorm(edges, cmap.N)

    # the section is drawn on a pressure axis that runs log, so the plot
    # has to be built in index space and the labels set on the axis
    lev = np.asarray(levels, float)
    order = np.argsort(-lev)            # 10 hPa at the top
    lev = lev[order]
    z = np.asarray(norm, float)[:, order].T      # (nlev, ntime)

    n = len(times)
    x = np.arange(n)
    y = np.arange(len(lev))

    fig_w = 13.0
    fig_h = 8.2
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor="white")
    ax = fig.add_axes([0.075, 0.145, 0.80, 0.70])
    ax.set_facecolor("white")

    im = ax.pcolormesh(x, y, z, cmap=cmap, norm=norm_c, shading="nearest")

    # the pressure axis: the labels are the real levels, the positions are
    # evenly spaced
    ax.set_yticks(y)
    ax.set_yticklabels(["%d" % l for l in lev], fontsize=10)
    ax.set_ylim(len(lev) - 0.5, -0.5)
    ax.set_xlim(-0.5, n - 0.5)

    # the date labels: about eight of them
    step = max(1, n // 8)
    idx = list(range(0, n, step))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    ax.set_xticks(idx)
    ax.set_xticklabels([times[i][:10] for i in idx], fontsize=9, rotation=0)
    ax.set_xlabel("Date", fontsize=11)

    # the approximate altitude on the right, the reference's second axis
    ax2 = ax.twinx()
    alt_km = [0.0] * len(lev)
    for i, l in enumerate(lev):
        alt_km[i] = 0.0 if l >= 1000 else 7.2 * np.log(1000.0 / l)
    ax2.set_ylim(len(lev) - 0.5, -0.5)
    ax2.set_yticks(y)
    ax2.set_yticklabels(["%d km" % a for a in alt_km], fontsize=9, color="#444444")
    ax2.set_ylabel("Approx. altitude", fontsize=11, color="#444444")

    ax.set_ylabel("Pressure (hPa)", fontsize=11)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax.tick_params(length=3)

    # the boundary between the analysis and the forecast
    if split is not None and 0 < split < n:
        ax.axvline(split - 0.5, color="#c0392b", lw=1.6, ls=(0, (5, 3)))
        ax.text(split - 0.5, -0.62, "  forecast starts", color="#c0392b",
                fontsize=10, ha="left", va="center", fontweight="bold")

    # the titles
    fig.text(0.075, 0.955, title, fontsize=15, fontweight="bold", ha="left",
             va="top")
    fig.text(0.075, 0.918, subtitle, fontsize=10, color="#333333", ha="left",
             va="top")

    # the colour bar, below the panel
    cax = fig.add_axes([0.28, 0.075, 0.44, 0.022])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal",
                      boundaries=edges, ticks=edges[1:-1])
    cb.ax.set_xticklabels(["%g" % e for e in edges[1:-1]], fontsize=8)
    cb.outline.set_visible(False)
    cb.ax.tick_params(length=2)
    fig.text(0.50, 0.038, "Polar cap (60-90N) normalised geopotential height "
             "anomaly (sigma)", fontsize=10, ha="center", va="center",
             fontweight="bold")

    if credit:
        fig.text(0.965, 0.055, credit, fontsize=6.5, color="#555555",
                 ha="right", va="bottom", wrap=True)
    if handle:
        fig.text(0.965, 0.022, handle, fontsize=9.5, fontweight="bold",
                 color="#111111", ha="right", va="bottom")

    fig.savefig(out_path, dpi=150, facecolor="white")
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    print("the levels:", LEVELS)
    print("the module is meant to be imported")
