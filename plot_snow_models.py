"""Render the snowfall panels for every fetched seasonal model.

Reads the per-model GRIBs in data/models/<tag>/ and writes, for each model:
  snow_<tag>_total_run_in.png     accumulation from init to end of run
  snow_<tag>_monthNN_in.png       accumulation for each lead month
  SNOW_<TAG>_<Mon><Yr>_anom_in.png  monthly anomaly vs that model's own
                                    hindcast climate

The anomalies use each model's OWN hindcast_climate_mean, so the baseline is
right for every model rather than borrowed from ECMWF.

usage: python3 plot_snow_models.py
"""
import os, sys, json, glob
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from plot_snow_ref import (load_geo, inside, project, project_path, PathPatch,
                           MONTH_NAMES, LON0, LON1, LAT0, LAT1, PLATE_COS,
                           hillshade)
from plot_snow_totals import (bilinear, month_len, wm_colormap, GRID)
import plot_snow_ref as PSR

DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "output")
MDIR = os.path.join(DATA, "models")

# the house anomaly palette: deep brown -> white -> deep teal
ANOM_LEVELS = np.array([-4, -2, -1, -0.5, -0.25, -0.1, 0,
                         0.1, 0.25, 0.5, 1, 2, 4], dtype=float)


def anom_cmap():
    """Signed-log ladder in the house brown/white/teal palette."""
    stops = ["#3a2006", "#5a3410", "#7d4d1a", "#a06a26", "#c08a3e",
             "#dcb684", "#f4f6f4",
             "#b8ddd4", "#87c4b4", "#4f9c88", "#2a7563", "#164c44",
             "#042720"]
    return ListedColormap(stops, name="house")


def read_grib(path):
    """-> list of (step_hours, lat, lon, values) using eccodes."""
    import eccodes
    out = []
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                step = int(eccodes.codes_get(gid, "step"))
                vals = eccodes.codes_get_array(gid, "values")
                lats = eccodes.codes_get_array(gid, "latitudes")
                lons = eccodes.codes_get_array(gid, "longitudes")
                out.append((step, np.asarray(lats, float),
                            np.asarray(lons, float), np.asarray(vals, float)))
            except Exception:
                pass
            eccodes.codes_release(gid)
    return out


def latlon_to_ij(lat, lon, lats, lons):
    """Match a lat/lon grid onto the file's own grid indices."""
    j = np.abs(lats[:, None] - lat[None, :]).argmin(axis=0)
    i = np.abs(lons[None, :] - lon[:, None]).argmin(axis=0)
    return i, j


def read_snowfall(path):
    """-> dict step -> list of (lat, lon, values) records."""
    recs = read_grib(path)
    if not recs:
        return None
    out = {}
    for step, la, lo, v in recs:
        out.setdefault(step, []).append((la, lo, v.astype(float)))
    return out


def grid_axes(rec):
    """-> (lats descending, lons ascending in -180..180, column order).

    The GRIB carries longitudes 0.5..359.5 while our display grid is
    -125..-65, so the longitudes are normalised to -180..180.  The column
    permutation is returned so that EVERY record of the file can be put in
    the same order - if only the axes are reordered and the values are not,
    the field is silently shifted by 180 degrees.
    """
    lat, lon, v = rec
    lats = np.unique(lat)[::-1]          # descending, like the GRIB
    lons = np.unique(lon)
    order = np.arange(len(lons))
    if lons.max() > 180:                 # 0..360 -> -180..180
        lons_new = np.where(lons > 180, lons - 360, lons)
        order = np.argsort(lons_new)
        lons = lons_new[order]
    return lats, lons, order


def to_2d(rec, lats, lons, order):
    """(lat, lon, flat values) -> 2-D field on the shared axes."""
    v = rec[2].reshape(len(lats), len(lons))
    return v[:, order]


def interp_to(target_lat, target_lon, lats, lons, v):
    """bilinear from the source grid to the target grid."""
    o = np.argsort(lats); lats = lats[o]; v = v[o, :]
    o = np.argsort(lons); lons = lons[o]; v = v[:, o]
    i = np.clip(np.searchsorted(lats, target_lat) - 1, 0, len(lats) - 2)
    dy = (target_lat - lats[i]) / (lats[i + 1] - lats[i])
    j = np.clip(np.searchsorted(lons, target_lon) - 1, 0, len(lons) - 2)
    dx = (target_lon - lons[j]) / (lons[j + 1] - lons[j])
    return ((1 - dy) * ((1 - dx) * v[i, j] + dx * v[i, j + 1]) +
            dy * ((1 - dx) * v[i + 1, j] + dx * v[i + 1, j + 1]))


def load_relief_mask(X, Y):
    rf = np.load(os.path.join(DATA, "relief_025.npz"))
    rlat, rlon, oro = rf["lat"], rf["lon"], rf["oro"]
    rlon = np.where(rlon > 180, rlon - 360, rlon)
    oro_s = bilinear(oro, rlat, rlon, Y.ravel(), X.ravel()).reshape(Y.shape)
    sh = hillshade(oro_s, Y[:, 0], X[0, :] * PLATE_COS)
    base = np.array([0.96, 0.955, 0.945])
    relief = np.clip(base[None, None, :] * (0.80 + 0.24 * sh[:, :, None]), 0, 1)
    return relief


def main():
    os.makedirs(OUT, exist_ok=True)
    state_p = os.path.join(DATA, "models_fetched.json")
    state = json.load(open(state_p)) if os.path.exists(state_p) else {}
    countries, states, provs = load_geo()

    lo = np.arange(LON0, LON1 + GRID / 2, GRID)
    la = np.arange(LAT0, LAT1 + GRID / 2, GRID)
    LON, LAT = np.meshgrid(lo, la)
    X, Y = project(LON, LAT, "plate")
    pts = np.column_stack([LON.ravel(), LAT.ravel()])
    in_us = np.zeros(len(pts), bool)
    for _, pth in states:
        in_us |= inside(pts, pth)
    in_us = in_us.reshape(LAT.shape)
    in_mex = inside(pts, countries["Mexico"]).reshape(LAT.shape)
    relief = load_relief_mask(X, Y)
    relief[~(in_us | in_mex)] = 1.0

    wm_cmap, wm_levels = wm_colormap()
    acmap = anom_cmap()
    anorm = BoundaryNorm(ANOM_LEVELS, acmap.N, clip=True)

    for tag, meta in sorted(state.items()):
        d = os.path.join(MDIR, tag)
        fg = os.path.join(d, "snowfall_monthly.grib")
        cg = os.path.join(d, "snowfall_hindcast.grib")
        if not os.path.exists(fg):
            print("skip %s (no snowfall)" % tag)
            continue
        name = meta.get("name", tag)
        init = meta.get("init", "2026-11")
        iy, im = int(init[:4]), int(init[-2:])

        by_step = read_snowfall(fg)
        if not by_step:
            print("skip %s (unreadable grib)" % tag)
            continue
        steps = sorted(by_step)
        lats, lons, order = grid_axes(by_step[steps[0]][0])
        clim = {}
        if os.path.exists(cg):
            for step, la0, lo0, v in read_grib(cg):
                clim.setdefault(step, []).append((la0, lo0, v))

        # ensemble mean per lead month, in inches
        monthly_in = []
        labels = []
        for k, step in enumerate(steps):
            recs = by_step[step]
            stack = np.array([to_2d(r, lats, lons, order) for r in recs])
            ens = stack.mean(axis=0)
            # the value is m w.e. s-1; convert to inches over the month
            m = (im - 1 + k) % 12 + 1
            y = iy + (im - 1 + k) // 12
            days = month_len(y, m)
            mm = interp_to(LAT.ravel(), LON.ravel(), lats, lons, ens).reshape(LAT.shape)
            monthly_in.append(mm * days * 86400.0 * 1000.0 / 25.4)
            labels.append("%s %d" % (MONTH_NAMES[m - 1], y))

        total_in = np.sum(monthly_in, axis=0)

        # anomaly vs the model's own hindcast climate
        anoms = []
        for k, step in enumerate(steps):
            if step not in clim:
                continue
            recs = clim[step]
            stack = np.array([to_2d(r, lats, lons, order) for r in recs])
            cm = stack.mean(axis=0)
            m = (im - 1 + k) % 12 + 1
            y = iy + (im - 1 + k) // 12
            days = month_len(y, m)
            cm_in = interp_to(LAT.ravel(), LON.ravel(), lats, lons, cm).reshape(LAT.shape)
            cm_in = cm_in * days * 86400.0 * 1000.0 / 25.4
            anoms.append((m, y, monthly_in[k] - cm_in))

        # ---------------- draw ----------------
        initlabel = "%s-%s-01 00Z" % (init[:4], init[4:])
        draw_map(os.path.join(OUT, "snow_%s_total_run_in.png" % tag),
                 "%s  Snowfall Total — Init to End of Run" % name,
                 "Init %s · %d-member ensemble mean · accumulated over %d lead months · "
                 "inches of water equivalent" % (initlabel, len(by_step[steps[0]]), len(steps)),
                 total_in, X, Y, in_us, relief, states, provs, countries,
                 wm_cmap, BoundaryNorm(wm_levels, wm_cmap.N, clip=True), wm_levels,
                 "Accumulated snowfall (in w.e.)")
        for k, lab in enumerate(labels):
            draw_map(os.path.join(OUT, "snow_%s_month%02d_in.png" % (tag, k + 1)),
                     "%s  Snowfall Total — %s" % (name, lab),
                     "Init %s · %d-member ensemble mean · lead month %d · "
                     "inches of water equivalent" % (initlabel, len(by_step[steps[0]]), k + 1),
                     monthly_in[k], X, Y, in_us, relief, states, provs, countries,
                     wm_cmap, BoundaryNorm(wm_levels, wm_cmap.N, clip=True), wm_levels,
                     "Accumulated snowfall (in w.e.)")
        for (m, y, a) in anoms:
            draw_map(os.path.join(OUT, "SNOW_%s_%s%d_anom_in.png" % (tag.upper(), MONTH_NAMES[m - 1], y)),
                     "%s Snowfall Anomaly  %s %d" % (name, MONTH_NAMES[m - 1], y),
                     "Init %s · %d-member ensemble mean · lead month %d · "
                     "anomaly vs %s hindcast climate · in w.e." % (
                         initlabel, len(by_step[steps[0]]),
                         (m - im) % 12 + 1, name),
                     a, X, Y, in_us, relief, states, provs, countries,
                     acmap, anorm, ANOM_LEVELS, "Snowfall anomaly (in w.e.)")
        print("rendered %-16s init=%s  months=%d anomalies=%d"
              % (tag, init, len(monthly_in), len(anoms)), flush=True)


def draw_map(fname, title, subtitle, field, X, Y, in_us, relief, states, provs,
             countries, cmap, norm, levels, cbar_label):
    plt.rcParams.update({"font.family": "DejaVu Sans"})
    xr = float(X.max() - X.min()); yr = float(Y.max() - Y.min())
    fig_w = 13.2
    ax_w = 0.975
    ax_h = ax_w * fig_w / (xr / yr)
    fig_h = ax_h + 1.05 + 1.15
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=130)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.013, 1.15 / fig_h, ax_w, ax_h / fig_h])
    ax.set_aspect("equal"); ax.set_axis_off()

    ax.pcolormesh(X, Y, relief, shading="nearest", rasterized=True, zorder=1,
                  edgecolors="face", linewidth=0.5)
    fl = np.ma.masked_where(~in_us, field)
    pc = ax.pcolormesh(X, Y, fl, cmap=cmap, norm=norm, shading="nearest",
                       rasterized=True, zorder=2, edgecolors="face", linewidth=0.3)

    for _, p in provs:
        ax.add_patch(PathPatch(project_path(p, "plate"), fill=False, ec="#d2d2d2",
                               lw=0.6, zorder=3))
    for _, p in states:
        ax.add_patch(PathPatch(project_path(p, "plate"), fill=False, ec="#101010",
                               lw=0.8, zorder=4))
    for nm, lw, col in (("United States of America", 1.9, "#000000"),
                        ("Canada", 1.1, "#9a9a9a"), ("Mexico", 1.0, "#7a7a7a")):
        if nm in countries:
            ax.add_patch(PathPatch(project_path(countries[nm], "plate"), fill=False,
                                   ec=col, lw=lw, zorder=5))

    dx, dy = 0.018 * xr, 0.035 * yr
    for lonv in [vv for vv in range(-120, -59, 10) if LON0 <= vv <= LON1]:
        ls = np.linspace(LAT0, LAT1, 80)
        xs, ys = project(np.full_like(ls, lonv), ls, "plate")
        ax.plot(xs, ys, color="#a9a9a9", lw=0.65, zorder=2.6)
        xb, yb = project(lonv, LAT0, "plate")
        ax.text(xb, yb - dy, "%d°W" % abs(lonv), fontsize=9.5, color="#2b2b2b",
                ha="center", va="top", zorder=7,
                bbox=dict(fc="white", ec="none", alpha=0.78, pad=1.2))
    for latv in [vv for vv in range(20, 60, 10) if LAT0 <= vv <= LAT1]:
        ls = np.linspace(LON0, LON1, 80)
        xs, ys = project(ls, np.full_like(ls, latv), "plate")
        ax.plot(xs, ys, color="#a9a9a9", lw=0.65, zorder=2.6)
        xl, yl = project(LON0, latv, "plate")
        ax.text(xl - dx, yl, "%d°N" % latv, fontsize=9.5, color="#2b2b2b",
                ha="right", va="center", zorder=7,
                bbox=dict(fc="white", ec="none", alpha=0.78, pad=1.2))
    ax.set_xlim(X.min() - dx * 1.6, X.max() + dx * 1.6)
    ax.set_ylim(Y.min() - dy * 1.7, Y.max() + dy * 0.7)

    fig.text(0.013, 1 - 0.38 / fig_h, title, fontsize=19, fontweight="bold",
             ha="left", va="center", color="#111111")
    fig.text(0.013, 1 - 0.72 / fig_h, subtitle, fontsize=10.5, ha="left",
             va="center", color="#4a4a4a")
    vm = np.where(in_us, field, np.nan)
    if np.isfinite(vm).any():
        fig.text(0.987, 1 - 0.38 / fig_h,
                 "max %+.2f in   min %+.2f in" % (np.nanmax(vm), np.nanmin(vm)),
                 fontsize=11.5, ha="right", va="center", color="#111111")
    cax = fig.add_axes([0.30, 0.62 / fig_h, 0.40, 0.16 / fig_h])
    cb = fig.colorbar(pc, cax=cax, boundaries=levels, spacing="uniform",
                      orientation="horizontal")
    ticks = levels[::2].tolist() if len(levels) > 12 else levels.tolist()
    cb.set_ticks(ticks)
    cb.ax.tick_params(labelsize=9.5, colors="#202020", length=3, width=0.8)
    cb.outline.set_edgecolor("#303030"); cb.outline.set_linewidth(1.0)
    fig.text(0.50, 0.24 / fig_h, cbar_label, fontsize=10.5, ha="center",
             va="center", color="#202020")
    fig.text(0.987, 0.016, "@Massachusettswx", fontsize=13, fontweight="bold",
             ha="right", va="bottom", color="#111111")
    fig.savefig(fname, dpi=130, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
