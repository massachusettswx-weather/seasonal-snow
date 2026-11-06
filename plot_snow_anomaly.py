"""Snowfall anomaly maps from SEAS5 against the ERA5 1991-2020 climatology.

One single-panel figure per lead month (1-month forecasts) for the eastern
U.S.:  green = above the ERA5 monthly mean, brown = below.

usage: python3 plot_snow_anomaly.py --init 202611 [--lead 1..6] [--all]
"""
import os, json, argparse, calendar, urllib.request
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Polygon, Rectangle
import matplotlib.colors as mcolors

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "output")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
STATES_JSON = os.path.join(DATA, "us-states.json")

C_TEXT = "#1f2937"
C_SUB = "#4b5563"


def get_states():
    if not os.path.exists(STATES_JSON):
        url = ("https://raw.githubusercontent.com/PublicaMundi/MappingAPI/"
               "master/data/geojson/us-states.json")
        urllib.request.urlretrieve(url, STATES_JSON)
    with open(STATES_JSON) as f:
        return json.load(f)


def bilinear(src_vals, src_lat, src_lon, tgt_lat, tgt_lon):
    """Bilinear sample of a 2-D field (lat descending, lon ascending) at points."""
    o = np.argsort(src_lat)                      # order-agnostic: ascending lat
    lat_asc = src_lat[o]
    vals_asc = src_vals[o]
    ol = np.argsort(src_lon)
    src_lon = src_lon[ol]
    vals_asc = vals_asc[:, ol]
    i = np.clip(np.searchsorted(lat_asc, tgt_lat) - 1, 0, len(lat_asc) - 2)
    dy = (tgt_lat - lat_asc[i]) / (lat_asc[i + 1] - lat_asc[i])
    j = np.clip(np.searchsorted(src_lon, tgt_lon) - 1, 0, len(src_lon) - 2)
    dx = (tgt_lon - src_lon[j]) / (src_lon[j + 1] - src_lon[j])
    v00 = vals_asc[i, j]; v01 = vals_asc[i, j + 1]
    v10 = vals_asc[i + 1, j]; v11 = vals_asc[i + 1, j + 1]
    return ((1 - dy) * ((1 - dx) * v00 + dx * v01) +
            dy * ((1 - dx) * v10 + dx * v11))


def land_mask(lon, lat):
    """True where a grid cell falls inside a US state (with a small buffer)."""
    from matplotlib.path import Path
    gj = get_states()
    pts = np.column_stack([np.asarray(lon).ravel(), np.asarray(lat).ravel()])
    inside = np.zeros(pts.shape[0], dtype=bool)
    for feat in gj["features"]:
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            ring = np.asarray(poly[0], dtype=float)
            inside |= Path(ring).contains_points(pts)
    return inside.reshape(np.asarray(lon).shape)


def state_patches(ax, extent, fc="none", ec="#9ca3af", lw=0.6):
    gj = get_states()
    patches = []
    for feat in gj["features"]:
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            ring = poly[0]
            xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
            if min(xs) > extent[1] or max(xs) < extent[0] or min(ys) > extent[3] or max(ys) < extent[2]:
                continue
            patches.append(Polygon(list(zip(xs, ys)), closed=True, facecolor=fc,
                                   edgecolor=ec, lw=lw, zorder=8))
    ax.add_collection(PatchCollection(patches, match_original=True, zorder=8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", default="202611")
    ap.add_argument("--lead", type=int, default=1)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--extent", default="-100,-65,24,49", help="W,E,S,N")
    ap.add_argument("--era5", default="era5_snow_clim.npz")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    tag = args.init
    w, e, s, n = [float(x) for x in args.extent.split(",")]

    sn = np.load(os.path.join(DATA, "seas5_%s_snow.npz" % tag))
    ec = np.load(os.path.join(DATA, args.era5))
    rates, slat, slon = sn["rates"], sn["lat"], sn["lon"]
    clim, elat, elon, clim_months = ec["clim"], ec["lat"], ec["lon"], ec["months"]
    elon = np.asarray(elon, dtype=float)
    if elon.max() > 180.0:                      # ARCO stores lon 0..360
        elon = np.where(elon > 180.0, elon - 360.0, elon)
        elon = np.sort(elon)
    elat = np.asarray(elat, dtype=float)

    # eastern-US window of the SEAS5 grid
    lon360 = slon % 360
    j0 = int(np.argmin(np.abs(lon360 - (w % 360))))
    j1 = int(np.argmin(np.abs(lon360 - (e % 360))))
    i0 = int(np.argmin(np.abs(slat - n)))
    i1 = int(np.argmin(np.abs(slat - s)))
    lat_w = slat[i0:i1 + 1]
    lon_w = lon360[j0:j1 + 1]
    lon_w = np.where(lon_w > 180.0, lon_w - 360.0, lon_w)         # -> -180..180
    lat_w = lat_w if lat_w[0] > lat_w[-1] else lat_w[::-1]      # north -> south
    flip = slat[i0:i1 + 1][0] < slat[i0:i1 + 1][-1]
    sub = rates[:, :, i0:i1 + 1, j0:j1 + 1]
    if flip:
        sub = sub[:, :, ::-1, :]
    sub = np.roll(sub, -j0, axis=3)                             # lon starts at w

    leads = range(1, 7) if args.all else [args.lead]
    for lead in leads:
        cal_month = (11 + lead - 1 - 1) % 12 + 1                # init month = 11
        mi = int(np.where(clim_months == cal_month)[0][0])
        # ERA5 climatology (mm/month) sampled onto the SEAS5 grid
        TY, TX = np.meshgrid(lat_w, lon_w, indexing="ij")
        era = bilinear(clim[mi], elat, elon, TY.ravel(), TX.ravel()).reshape(TY.shape)
        year = 2026 + (11 + lead - 1 - 1) // 12
        secs = calendar.monthrange(year, cal_month)[1] * 86400.0
        seas = rates[:, lead - 1, i0:i1 + 1, j0:j1 + 1]
        if flip:
            seas = seas[:, ::-1, :]
        seas = np.roll(seas, -j0, axis=2)
        ens_mm = seas.mean(axis=0) * 1000.0 * secs
        sd_mm = seas.std(axis=0) * 1000.0 * secs
        anom = ens_mm - era
        land = land_mask(TX, TY)
        # one-cell dilation so coastal cells are not dropped
        dil = land.copy()
        dil[1:, :] |= land[:-1, :]; dil[:-1, :] |= land[1:, :]
        dil[:, 1:] |= land[:, :-1]; dil[:, :-1] |= land[:, 1:]
        anom = np.ma.masked_where(~dil, anom)

        fig = plt.figure(figsize=(11.4, 8.0), dpi=150, facecolor="white")
        ax = fig.add_axes([0.075, 0.085, 0.80, 0.79])
        avals = np.asarray(anom.filled(np.nan), dtype=float)
        lim = max(5.0, float(np.nanpercentile(np.abs(avals), 99)))
        levels = np.linspace(-lim, lim, 21)
        norm = mcolors.TwoSlopeNorm(vmin=-lim, vcenter=0.0, vmax=lim)
        ax.set_facecolor("#ffffff")
        cf = ax.pcolormesh(lon_w, lat_w, anom, cmap="BrBG", norm=norm,
                           shading="nearest", zorder=2)
        try:
            ax.contour(lon_w, lat_w, np.ma.filled(anom, np.nan),
                       levels=[0.0], colors="k", linewidths=0.8, alpha=0.5, zorder=6)
        except Exception:
            pass
        state_patches(ax, (w, e, s, n), ec="#ffffff", lw=0.45)
        ax.add_patch(Rectangle((w, s), e - w, n - s, fill=False, ec="#374151", lw=1.0, zorder=9))
        ax.set_xlim(w, e); ax.set_ylim(s, n)
        ax.set_xlabel("Longitude", fontsize=10.5, color=C_TEXT)
        ax.set_ylabel("Latitude", fontsize=10.5, color=C_TEXT)
        ax.tick_params(labelsize=9.5, colors=C_TEXT)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            ax.spines[sp].set_color("#9ca3af")
        cb = fig.colorbar(cf, ax=ax, fraction=0.032, pad=0.02)
        cb.set_label("Snowfall anomaly (mm w.e. per month)", fontsize=10, color=C_TEXT)
        cb.ax.tick_params(labelsize=9, colors=C_TEXT)
        cb.outline.set_edgecolor("#9ca3af")

        mlbl = "%s %d" % (MONTHS[cal_month - 1], year)
        fig.text(0.075, 0.955, "SEAS5  ·  1-Month Snowfall Anomaly  ·  %s  ·  Eastern U.S."
                 % mlbl, fontsize=15.5, fontweight="bold", color=C_TEXT, va="center")
        fig.text(0.075, 0.905,
                 "Lead month %d of the 1 Nov 2026 init  ·  51-member ensemble mean  ·  "
                 "anomaly vs the ERA5 1991–2020 monthly snow climatology" % lead,
                 fontsize=9.8, color=C_SUB, va="center")
        dom_anom = float(np.nanmean(avals))
        dom_sd = float(np.nanmean(sd_mm))
        fig.text(0.075, 0.028,
                 "Domain-mean anomaly %+.1f mm w.e.  ·  mean member sd %.1f mm  ·  "
                 "ERA5 climatology: ARCO-ERA5  ·  snow = precip with 2 m T < 0 °C" % (dom_anom, dom_sd),
                 fontsize=8.0, color="#6b7280", ha="left", va="center")
        fig.text(0.975, 0.028, "@Massachusettswx", fontsize=10.5, fontweight="bold",
                 color=C_TEXT, ha="right", va="center")
        out = args.out or os.path.join(OUT, "SEAS5_%s_snow_anomaly_%s.png" % (tag, mlbl.replace(" ", "")))
        fig.savefig(out, facecolor="white")
        plt.close(fig)
        print("wrote", out, "| domain anomaly %+.1f mm, mean member sd %.1f mm" % (dom_anom, dom_sd))


if __name__ == "__main__":
    main()
