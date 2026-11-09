"""Snowfall accumulation maps for the seasonal site.

Produces, for one seasonal run:
  * the accumulation from the init to the END of the run (inches w.e.), drawn
    with the 0-300 in snow-depth colour bar
  * the accumulation for each lead month (inches w.e.), same colourbar

Both use the same CONUS frame as plot_snow_ref.py so the site can show them
side by side with the anomaly panels.

Usage: python3 plot_snow_totals.py --init 202611 [--tag ecmwf-seas5]
"""
import os, json, argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import FancyBboxPatch

from plot_snow_ref import (load_geo, inside, compound, project, project_path,
                           PathPatch, MONTH_NAMES, LON0, LON1, LAT0, LAT1,
                           PLATE_COS, hillshade, box3)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "output")
GRID = 0.05


SNOW_SAT_K = 1.35   # the user's colour bar is pastel; this is the boldness factor


def boost_saturation(colors, k=None):
    """Make the sampled ramp bolder without changing its hue path.

    The colour bar was sampled from a published bar whose colours are pastel
    (mean saturation ~0.31), which makes the maps read as washed out.  The
    hues and the lightness ramp are left exactly as sampled; only the
    saturation is pushed, and a near-neutral grey stays grey because it has
    no hue to push.
    """
    import colorsys
    k = SNOW_SAT_K if k is None else k
    out = []
    for c in colors:
        r, g, b = [int(c[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
        h, sat, v = colorsys.rgb_to_hsv(r, g, b)
        if sat > 0.05:
            sat = min(1.0, sat * k)
        r2, g2, b2 = colorsys.hsv_to_rgb(h, sat, v)
        out.append("#%02x%02x%02x" % (int(r2 * 255 + 0.5), int(g2 * 255 + 0.5),
                                      int(b2 * 255 + 0.5)))
    return out


def wm_colormap():
    """The snow-depth scale.  The bar runs 300 -> 0.01,
    so both the levels and the colours are reversed here to give matplotlib an
    ascending norm."""
    d = json.load(open(os.path.join(DATA, "snow_depth_scale.json")))
    levels = np.array(d["levels"], dtype=float)[::-1]
    colors = list(d["colors"])[::-1]
    # "no snow" must read as white: the bottom of the ramp is white so a
    # trace of snowfall does not paint the map purple
    colors = ["#ffffff"] + list(colors[1:])
    colors = boost_saturation(colors)
    cmap = ListedColormap(colors, name="snow_depth")
    return cmap, levels


def load_run(init):
    sn = np.load(os.path.join(DATA, "seas5_%s_snow.npz" % init))
    rates = sn["rates"]                       # [member, lead, lat, lon] m w.e. s-1
    slat = np.asarray(sn["lat"], float)
    slon = np.asarray(sn["lon"], float)
    slon = np.where(slon > 180, slon - 360, slon)
    return rates, slat, slon


def bilinear(src_vals, src_lat, src_lon, tgt_lat, tgt_lon):
    src_vals = np.asarray(src_vals, dtype=float)
    slat = np.asarray(src_lat, float); slon = np.asarray(src_lon, float)
    o = np.argsort(slat); slat = slat[o]; src_vals = src_vals[o, :]
    o = np.argsort(slon); slon = slon[o]; src_vals = src_vals[:, o]
    i = np.clip(np.searchsorted(slat, tgt_lat) - 1, 0, len(slat) - 2)
    dy = (tgt_lat - slat[i]) / (slat[i + 1] - slat[i])
    j = np.clip(np.searchsorted(slon, tgt_lon) - 1, 0, len(slon) - 2)
    dx = (tgt_lon - slon[j]) / (slon[j + 1] - slon[j])
    return ((1 - dy) * ((1 - dx) * src_vals[i, j] + dx * src_vals[i, j + 1]) +
            dy * ((1 - dx) * src_vals[i + 1, j] + dx * src_vals[i + 1, j + 1]))


def month_len(y, m):
    return [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]


def accumulations(rates, slat, slon, init_year, init_month):
    """-> (total_in [lat,lon], monthly_in [lead,lat,lon], labels)"""
    ens = rates.mean(axis=0)                       # m w.e. s-1
    lo = np.arange(LON0, LON1 + GRID / 2, GRID)
    la = np.arange(LAT0, LAT1 + GRID / 2, GRID)
    LON, LAT = np.meshgrid(lo, la)
    monthly = np.zeros((ens.shape[0],) + LAT.shape)
    labels = []
    for k in range(ens.shape[0]):
        m = (init_month - 1 + k) % 12 + 1
        y = init_year + (init_month - 1 + k) // 12
        d = month_len(y, m)
        mm = bilinear(ens[k], slat, slon, LAT.ravel(), LON.ravel()).reshape(LAT.shape)
        monthly[k] = mm * d * 86400.0 * 1000.0 / 25.4      # inches w.e.
        labels.append("%s %d" % (MONTH_NAMES[m - 1], y))
    return monthly.sum(axis=0), monthly, labels, LON, LAT


def frame(ax, X, Y, states, provs, countries, proj):
    for _, p in provs:
        ax.add_patch(PathPatch(project_path(p, proj), fill=False, ec="#d2d2d2", lw=0.6, zorder=3))
    for _, p in states:
        ax.add_patch(PathPatch(project_path(p, proj), fill=False, ec="#101010", lw=0.8, zorder=4))
    for nm, lw, col in (("United States of America", 1.9, "#000000"),
                        ("Canada", 1.1, "#9a9a9a"), ("Mexico", 1.0, "#7a7a7a")):
        if nm in countries:
            ax.add_patch(PathPatch(project_path(countries[nm], proj), fill=False,
                                   ec=col, lw=lw, zorder=5))


def draw(fname, title, subtitle, field, X, Y, states, provs, countries, proj,
         cmap, levels, unit="in", relief=None, in_us=None):
    plt.rcParams.update({"font.family": "DejaVu Sans"})
    xr = float(X.max() - X.min()); yr = float(Y.max() - Y.min())
    fig_w = 13.2
    ax_w = 0.975
    ax_h = ax_w * fig_w / (xr / yr)
    top_in, bot_in = 1.05, 1.15
    fig_h = ax_h + top_in + bot_in
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=130)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.013, bot_in / fig_h, ax_w, ax_h / fig_h])
    ax.set_aspect("equal"); ax.set_axis_off()

    if relief is not None:
        ax.pcolormesh(X, Y, relief, shading="nearest", rasterized=True, zorder=1,
                      edgecolors="face", linewidth=0.5)
    norm = BoundaryNorm(levels, cmap.N, clip=True)
    fl = np.ma.masked_where(~in_us, field) if in_us is not None else field
    if in_us is not None:
        # no snowfall = white
        fl = np.ma.masked_where(fl < float(levels[0]), fl)
    cmap = cmap.copy(); cmap.set_bad("white")
    pc = ax.pcolormesh(X, Y, fl, cmap=cmap, norm=norm, shading="nearest",
                       rasterized=True, zorder=2, edgecolors="face", linewidth=0.3)
    frame(ax, X, Y, states, provs, countries, proj)

    dx, dy = 0.018 * xr, 0.035 * yr
    for lo in [v for v in range(-120, -59, 10) if LON0 <= v <= LON1]:
        ls = np.linspace(LAT0, LAT1, 80)
        xs, ys = project(np.full_like(ls, lo), ls, proj)
        ax.plot(xs, ys, color="#a9a9a9", lw=0.65, zorder=2.6)
        xb, yb = project(lo, LAT0, proj)
        ax.text(xb, yb - dy, "%d°W" % abs(lo), fontsize=9.5, color="#2b2b2b",
                ha="center", va="top", zorder=7,
                bbox=dict(fc="white", ec="none", alpha=0.78, pad=1.2))
    for la in [v for v in range(20, 60, 10) if LAT0 <= v <= LAT1]:
        ls = np.linspace(LON0, LON1, 80)
        xs, ys = project(ls, np.full_like(ls, la), proj)
        ax.plot(xs, ys, color="#a9a9a9", lw=0.65, zorder=2.6)
        xl, yl = project(LON0, la, proj)
        ax.text(xl - dx, yl, "%d°N" % la, fontsize=9.5, color="#2b2b2b",
                ha="right", va="center", zorder=7,
                bbox=dict(fc="white", ec="none", alpha=0.78, pad=1.2))
    ax.set_xlim(X.min() - dx * 1.6, X.max() + dx * 1.6)
    ax.set_ylim(Y.min() - dy * 1.7, Y.max() + dy * 0.7)

    fig.text(0.013, 1 - 0.38 / fig_h, title, fontsize=19, fontweight="bold",
             ha="left", va="center", color="#111111")
    fig.text(0.013, 1 - 0.72 / fig_h, subtitle, fontsize=10.5, ha="left",
             va="center", color="#4a4a4a")
    cax = fig.add_axes([0.30, 0.62 / fig_h, 0.40, 0.16 / fig_h])
    cb = fig.colorbar(pc, cax=cax, boundaries=levels, spacing="uniform",
                      orientation="horizontal")
    cb.set_ticks(levels[::4].tolist() + [levels[-1]])
    cb.ax.tick_params(labelsize=9.5, colors="#202020", length=3, width=0.8)
    cb.outline.set_edgecolor("#303030"); cb.outline.set_linewidth(1.0)
    fig.text(0.50, 0.24 / fig_h, "Accumulated snowfall (%s w.e.)" % unit,
             fontsize=10.5, ha="center", va="center", color="#202020")
    fig.text(0.987, 0.016, "@Massachusettswx", fontsize=13, fontweight="bold",
             ha="right", va="bottom", color="#111111")
    fig.savefig(fname, dpi=130, facecolor="white")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", default="202611")
    ap.add_argument("--tag", default="ecmwf-seas5")
    ap.add_argument("--name", default="ECMWF SEAS5")
    args = ap.parse_args()
    rates, slat, slon = load_run(args.init)
    total, monthly, labels, LON, LAT = accumulations(
        rates, slat, slon, int(args.init[:4]), int(args.init[4:]))
    X, Y = project(LON, LAT, "plate")
    countries, states, provs = load_geo()
    cmap, levels = wm_colormap()

    # US mask (field stops at the international border) + relief basemap
    pts = np.column_stack([LON.ravel(), LAT.ravel()])
    in_us = np.zeros(len(pts), bool)
    for _, pth in states:
        in_us |= inside(pts, pth)
    in_us = in_us.reshape(LAT.shape)
    rf = np.load(os.path.join(DATA, "relief_025.npz"))
    rlat, rlon, oro = rf["lat"], rf["lon"], rf["oro"]
    rlon = np.where(rlon > 180, rlon - 360, rlon)
    oro_s = bilinear(oro, rlat, rlon, LAT.ravel(), LON.ravel()).reshape(LAT.shape)
    sh = hillshade(oro_s, LAT[:, 0], LON[0, :] * PLATE_COS)
    base = np.array([0.96, 0.955, 0.945])
    relief = np.clip(base[None, None, :] * (0.80 + 0.24 * sh[:, :, None]), 0, 1)
    in_mex = inside(pts, countries["Mexico"]).reshape(LAT.shape)
    relief[~(in_us | in_mex)] = 1.0

    draw(os.path.join(OUT, "snow_%s_total_run_in.png" % args.tag),
         "%s  Snowfall Total — Init to End of Run" % args.name,
         "Init %s-%s-01 00Z · 51-member ensemble mean · accumulated over %d lead months · "
         "inches of water equivalent" % (args.init[:4], args.init[4:], len(labels)),
         total, X, Y, states, provs, countries, "plate", cmap, levels,
         relief=relief, in_us=in_us)

    for k, lab in enumerate(labels):
        draw(os.path.join(OUT, "snow_%s_month%02d_in.png" % (args.tag, k + 1)),
             "%s  Snowfall Total — %s" % (args.name, lab),
             "Init %s-%s-01 00Z · 51-member ensemble mean · lead month %d · inches of water equivalent"
             % (args.init[:4], args.init[4:], k + 1),
             monthly[k], X, Y, states, provs, countries, "plate", cmap, levels,
             relief=relief, in_us=in_us)
    print("wrote total + %d monthly accumulation maps for %s" % (len(labels), args.name))


if __name__ == "__main__":
    main()
