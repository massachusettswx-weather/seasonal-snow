"""Reference-style SEAS5 snow-anomaly maps (eastern U.S.).

Look: Lambert-conformal basemap with real 0.25 deg ERA5 hillshade, flat
filled-contour bands of the monthly snowfall anomaly, black state borders,
field clipped at the US/Canada border, vertical colourbar, dark title bar
and a "max/min in view" box.

Data:
  data/seas5_202611_snow.npz     SEAS5 monthly-mean snowfall rates [51,6,180,360] m w.e. s-1
  data/era5_snow_clim_arco.npz   ERA5 1991-2020 monthly snow climatology [6,17,23] mm
  data/relief_025.npz            ARCO-ERA5 orography (0.25 deg) for the hillshade
  data/ne_50m_admin_*.geojson    Natural Earth borders

Usage:  python3 plot_snow_ref.py --init 202611 [--palette house|ref] [--all]
"""
import os, sys, json, argparse, datetime
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.path import Path
from matplotlib.patches import PathPatch, FancyBboxPatch
from matplotlib.colors import LinearSegmentedColormap, BoundaryNorm

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "output")

# view window (eastern U.S. + southern Canada, as in the reference)
LON0, LON1 = -125.0, -65.0
LAT0, LAT1 = 24.5, 50.0
GRID = 0.05                       # display grid (deg)

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


# --------------------------------------------------------------------------- geo
def _paths_from_geom(geom):
    t = geom["type"]
    polys = geom["coordinates"] if t == "MultiPolygon" else [geom["coordinates"]]
    verts, codes = [], []
    for poly in polys:
        for ring in poly:
            r = list(ring)
            if r[0] != r[-1]:
                r.append(r[0])
            verts.extend(r)
            codes.extend([Path.MOVETO] + [Path.LINETO] * (len(r) - 2) + [Path.CLOSEPOLY])
    return Path(verts, codes)


def _geom_path(g):
    if g is None:
        return None
    if g["type"] == "Polygon":
        return _paths_from_geom(g)
    if g["type"] == "MultiPolygon":
        return _paths_from_geom(g)
    return None


def load_geo():
    a0 = json.load(open(os.path.join(DATA, "ne_50m_admin_0_countries.geojson")))
    a1 = json.load(open(os.path.join(DATA, "ne_50m_admin_1_states_provinces.geojson")))
    countries = {}
    for f in a0["features"]:
        nm = f["properties"].get("NAME")
        p = _geom_path(f["geometry"])
        if nm and p is not None:
            countries[nm] = p
    states, provs = [], []
    for f in a1["features"]:
        adm = f["properties"].get("adm0_a3")
        p = _geom_path(f["geometry"])
        if p is None or not in_view(p):
            continue                      # drops Alaska/Hawaii (antimeridian rings)
        if adm == "USA":
            states.append((f["properties"].get("name"), p))
        elif adm == "CAN":
            provs.append((f["properties"].get("name"), p))
    return countries, states, provs


def in_view(path, lon0=LON0, lon1=LON1, lat0=LAT0, lat1=LAT1, margin=2.0):
    """True if any vertex of the path falls inside (expanded) view window."""
    v = path.vertices
    m = ((v[:, 0] > lon0 - margin) & (v[:, 0] < lon1 + margin) &
         (v[:, 1] > lat0 - margin) & (v[:, 1] < lat1 + margin))
    return bool(m.any())


def compound(paths):
    verts, codes = [], []
    for p in paths:
        verts.append(p.vertices)
        codes.append(p.codes)
    return Path(np.concatenate(verts), np.concatenate(codes))


def inside(pts, path):
    return path.contains_points(pts)


# ------------------------------------------------------------------- projection
def lcc(lon, lat, lat1=33.0, lat2=45.0, lat0=39.0, lon0=-96.0):
    """Spherical Lambert conformal conic -> x, y (Earth radii)."""
    phi = np.deg2rad(np.asarray(lat, dtype=float))
    lam = np.deg2rad(np.asarray(lon, dtype=float))
    p1, p2, p0 = np.deg2rad([lat1, lat2, lat0])
    l0 = np.deg2rad(lon0)
    if abs(p1 - p2) < 1e-9:
        n = np.sin(p1)
    else:
        n = (np.log(np.cos(p1) / np.cos(p2)) /
             np.log(np.tan(np.pi / 4 + p2 / 2) / np.tan(np.pi / 4 + p1 / 2)))
    F = np.cos(p1) ** n * np.tan(np.pi / 4 + p1 / 2) ** n / n
    rho0 = F / np.tan(np.pi / 4 + p0 / 2) ** n
    rho = F / np.tan(np.pi / 4 + phi / 2) ** n
    theta = n * (lam - l0)
    return rho * np.sin(theta), rho0 - rho * np.cos(theta)


PLATE_COS = np.cos(np.deg2rad(37.0))


def plate(lon, lat):
    """Flat equirectangular map (x compressed by cos 37N so the scale is true
    at the CONUS mid-latitude) - a rectangular, undistorted-looking map."""
    return np.asarray(lon, dtype=float) * PLATE_COS, np.asarray(lat, dtype=float)


def project(lon, lat, mode="lcc"):
    if mode == "plate":
        return plate(lon, lat)
    return lcc(lon, lat)


def project_path(path, mode="lcc"):
    """Project a lon/lat matplotlib Path into LCC space (keeps vertex codes)."""
    v = path.vertices
    x, y = project(v[:, 0], v[:, 1], mode)
    return Path(np.column_stack([x, y]), path.codes)


# ------------------------------------------------------------------ interpolation
def bilinear(src_vals, src_lat, src_lon, tgt_lat, tgt_lon):
    """Bilinear sample of a 2-D field (any lat/lon ordering) at target points."""
    src_vals = np.asarray(src_vals, dtype=float)
    slat = np.asarray(src_lat, dtype=float)
    slon = np.asarray(src_lon, dtype=float)
    olat = np.argsort(slat)
    slat = slat[olat]
    src_vals = src_vals[olat, :]
    olon = np.argsort(slon)
    slon = slon[olon]
    src_vals = src_vals[:, olon]
    i = np.clip(np.searchsorted(slat, tgt_lat) - 1, 0, len(slat) - 2)
    dy = (tgt_lat - slat[i]) / (slat[i + 1] - slat[i])
    j = np.clip(np.searchsorted(slon, tgt_lon) - 1, 0, len(slon) - 2)
    dx = (tgt_lon - slon[j]) / (slon[j + 1] - slon[j])
    v00 = src_vals[i, j]; v01 = src_vals[i, j + 1]
    v10 = src_vals[i + 1, j]; v11 = src_vals[i + 1, j + 1]
    return ((1 - dy) * ((1 - dx) * v00 + dx * v01) +
            dy * ((1 - dx) * v10 + dx * v11))


def box3(a):
    """3x3 boxcar on the last two axes (native-resolution smoothing)."""
    a = np.asarray(a, dtype=float)
    p = np.pad(a, [(0, 0)] * (a.ndim - 2) + [(1, 1), (1, 1)], mode="edge")
    out = np.zeros_like(a)
    for i in range(3):
        for j in range(3):
            sl = [slice(None)] * a.ndim
            sl[-2] = slice(i, i + a.shape[-2])
            sl[-1] = slice(j, j + a.shape[-1])
            out += p[tuple(sl)]
    return out / 9.0


def make_levels(vmax, base=(1.0, 2.5, 5, 10, 20, 40, 80, 120)):
    """default ladder is in mm; scale it to the plotting unit."""
    """Signed-log ladder: fine steps near zero, coarse at the extremes."""
    mags = [b for b in base if b < vmax]
    if not mags or mags[-1] < vmax:
        mags.append(vmax)
    return np.array([-m for m in reversed(mags)] + [0.0] + mags)


def smooth2d(a, w=0.25):
    """mild separable smoothing (0.25,0.5,0.25) of the last two axes."""
    a = np.asarray(a, dtype=float)
    k = np.array([w, 0.5, w])
    def one(x, axis):
        pw = [(0, 0)] * x.ndim
        pw[axis] = (1, 1)
        p = np.pad(x, pw, mode="edge")
        out = 0.0
        for i in range(3):
            sl = [slice(None)] * x.ndim
            sl[axis] = slice(i, i + x.shape[axis])
            out = out + k[i] * p[tuple(sl)]
        return out
    return one(one(a, -1), -2)


# --------------------------------------------------------------------- palettes
def cmap_house():
    """The user's house colourbar (brown -> white -> teal), vivid version:
    same hue path as their pasted bar but pushed to full saturation so the
    bands read clearly on the map."""
    stops = ["#3a2006", "#5c3410", "#7b4715", "#9a5c1c", "#b67427", "#c88f45",
             "#daae70", "#e8cb9f", "#f2e2c4", "#f8f2e2", "#fdfdfb",
             "#ffffff",
             "#d8efea", "#a3dacf", "#6ec2b1", "#3fa18f", "#1f7f6f", "#0e5f53",
             "#073f37", "#042720"]
    return LinearSegmentedColormap.from_list("house", stops, N=256)


def cmap_ref():
    return LinearSegmentedColormap.from_list("ref", [
        "#2a1a5e", "#123a8a", "#0b5fbe", "#3d8fd8", "#9cc7e8", "#d6e8f5",
        "#ffffff",
        "#f7d9c4", "#f0a983", "#e2683f", "#c8281c", "#8f1010", "#4a0512"])


# ----------------------------------------------------------------------- relief
def hillshade(oro, lat, lon, azimuth=315.0, zenith=45.0, z=1.0):
    dy = (lat[1] - lat[0]) * 111320.0
    dx = (lon[1] - lon[0]) * 111320.0 * np.cos(np.deg2rad(lat))[:, None]
    dzdx = np.gradient(oro, axis=1) / dx
    dzdy = np.gradient(oro, axis=0) / dy
    slope = np.pi / 2 - np.arctan(z * np.sqrt(dzdx ** 2 + dzdy ** 2))
    aspect = np.arctan2(-dzdx, dzdy)
    hs = (np.sin(np.deg2rad(zenith)) * np.cos(slope) +
          np.cos(np.deg2rad(zenith)) * np.sin(slope) *
          np.cos(np.deg2rad(azimuth) - aspect))
    return np.clip(hs, 0, 1)


# ------------------------------------------------------------------------ main
def build(init="202611", palette="house", outdir=OUT,
          era5="era5_snow_clim_arco.npz", baseline="hc", suffix="",
          unit="in", window=1, proj="plate"):
    sn = np.load(os.path.join(DATA, "seas5_%s_snow.npz" % init))
    ec = np.load(os.path.join(DATA, era5))
    rf = np.load(os.path.join(DATA, "relief_025.npz"))

    rates, slat, slon = sn["rates"], np.asarray(sn["lat"], float), np.asarray(sn["lon"], float)
    clim, elat, elon, clim_months = ec["clim"], np.asarray(ec["lat"], float), np.asarray(ec["lon"], float), ec["months"]
    ens_raw = rates.mean(axis=0)                               # [lead, lat, lon] (1 deg)
    ens = box3(ens_raw)                                        # smoothed for display
    clim_s = box3(clim)                                        # 0.75 deg, smoothed

    # lon conventions -> -180..180 for every source
    slon = np.where(slon > 180, slon - 360, slon)
    elon = np.where(elon > 180, elon - 360, elon)

    # target display grid (lon/lat) -> projected
    lo = np.arange(LON0, LON1 + GRID / 2, GRID)
    la = np.arange(LAT0, LAT1 + GRID / 2, GRID)
    LON, LAT = np.meshgrid(lo, la)
    X, Y = project(LON, LAT, proj)

    # ---- SEAS5 monthly accumulation (mm w.e.) on the display grid
    y0 = int(init[:4]); m0 = int(init[4:])
    leads = []
    for k in range(6):
        mm = (m0 - 1 + k) % 12 + 1
        yy = y0 + (m0 - 1 + k) // 12
        days = [31, 29 if yy % 4 == 0 and (yy % 100 != 0 or yy % 400 == 0) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mm - 1]
        leads.append((mm, yy, days))
    seas_mm = np.zeros((6,) + LAT.shape)
    for k, (mm, yy, days) in enumerate(leads):
        seas_mm[k] = bilinear(ens[k], slat, slon, LAT.ravel(), LON.ravel()).reshape(LAT.shape) \
            * days * 86400.0 * 1000.0

    # ---- climatology baseline -> anomaly on the display grid
    if baseline == "hc":
        # ECMWF's own SEAS5 hindcast climatology for the lead month; both
        # fields live on the same 1 deg SEAS5 grid, so difference them natively
        hc = np.load(os.path.join(DATA, "seas5_%s_snow_hc.npz" % init))
        hclat, hclon, hcrates = hc["lat"], hc["lon"], hc["rates"]
        hclon = np.where(hclon > 180, hclon - 360, hclon)
        anom = np.zeros((6,) + LAT.shape)
        for k, (mm, yy, days) in enumerate(leads):
            nat = (ens_raw[k] - hcrates[k]) * days * 86400.0 * 1000.0   # mm
            anom[k] = bilinear(nat, slat, slon, LAT.ravel(), LON.ravel()).reshape(LAT.shape)
        base_name = "SEAS5 hindcast climatology (ECMWF)"
    else:
        base_mm = np.zeros((6,) + LAT.shape)
        for k, (mm, yy, days) in enumerate(leads):
            j = int(np.where(clim_months == mm)[0][0])
            base_mm[k] = bilinear(clim_s[j], elat, elon, LAT.ravel(), LON.ravel()).reshape(LAT.shape)
        anom = seas_mm - base_mm
        base_name = "ERA5 1991-2020 snow climatology"

    # ---- relief
    rlat, rlon, oro = rf["lat"], rf["lon"], rf["oro"]
    rlon = np.where(rlon > 180, rlon - 360, rlon)
    oro_s = box3(box3(oro))
    sh_native = hillshade(oro_s, rlat, rlon)
    sh = bilinear(sh_native, rlat, rlon, LAT.ravel(), LON.ravel()).reshape(LAT.shape)
    base = np.array([0.96, 0.955, 0.945])
    relief = np.clip(base[None, None, :] * (0.80 + 0.24 * sh[:, :, None]), 0, 1)

    # ---- geometry
    countries, states, provs = load_geo()
    us_path = compound([p for _, p in states])
    us_proj = project_path(us_path, proj)
    land_paths = []
    for nm in ("United States of America", "Canada", "Mexico"):
        if nm in countries:
            land_paths.append(project_path(countries[nm], proj))
    land_proj = compound(land_paths)

    pts = np.column_stack([LON.ravel(), LAT.ravel()])
    in_us = np.zeros(len(pts), bool)
    for _, p in states:
        in_us |= inside(pts, p)
    in_us = in_us.reshape(LAT.shape)
    in_land = np.zeros(len(pts), bool)
    for nm in ("United States of America", "Canada", "Mexico"):
        if nm in countries:
            in_land |= inside(pts, countries[nm])
    in_land = in_land.reshape(LAT.shape)
    # the shaded relief is only drawn over the forecast domain; Canada is left
    # white (its province boundaries still show as a faint glimpse)
    relief_dom = in_us.copy()
    if "Mexico" in countries:
        relief_dom |= inside(pts, countries["Mexico"]).reshape(LAT.shape)

    # outside the forecast domain (ocean, Canada) -> plain white
    relief[~relief_dom] = 1.0

    # ---- colours
    cmap = cmap_house() if palette == "house" else cmap_ref()

    os.makedirs(outdir, exist_ok=True)
    month_titles = ["Nov 2026", "Dec 2026", "Jan 2027", "Feb 2027", "Mar 2027", "Apr 2027"]

    # ---- unit conversion (1 in = 25.4 mm of water equivalent)
    conv = 1.0 / 25.4 if unit == "in" else 1.0
    anom = anom * conv
    u_label = "in w.e." if unit == "in" else "mm w.e."
    base_ladder = ((0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0) if unit == "in"
                   else (1.0, 2.5, 5, 10, 20, 40, 80))

    # ---- assemble the panels: 6 single months, or the rolling 3-month means
    if window == 3:
        windows = [(0, 1, 2, "NDJ", "Nov 2026 - Jan 2027"),
                   (1, 2, 3, "DJF", "Dec 2026 - Feb 2027"),
                   (2, 3, 4, "JFM", "Jan 2027 - Mar 2027"),
                   (3, 4, 5, "FMA", "Feb 2027 - Apr 2027")]
        items = []
        for i0, i1, i2, tag, span in windows:
            items.append(dict(field=anom[[i0, i1, i2]].mean(axis=0),
                              title="%s  %s" % (tag, "2026/27" if tag in ("NDJ", "DJF") else "2027"),
                              span=span, leads=(i0 + 1, i2 + 1),
                              fname="SEAS5_%s_snow_anomaly_3mo_%s" % (init, tag)))
    else:
        items = []
        for k in range(6):
            mm, yy, days = leads[k]
            items.append(dict(field=anom[k], title=month_titles[k],
                              span=month_titles[k], leads=(k + 1, k + 1),
                              fname="SEAS5_%s_snow_anomaly_%s%s" % (init, MONTH_NAMES[mm - 1][:3], yy)))

    for it in items:
        f_anom = np.ma.masked_where(~in_us, it["field"])
        amax = float(np.nanmax(it["field"][in_us])) if in_us.any() else 0.0
        amin = float(np.nanmin(it["field"][in_us])) if in_us.any() else 0.0
        fname = os.path.join(outdir, it["fname"] + ".png")
        if palette != "house":
            fname = fname.replace(".png", "_%s.png" % palette)
        if suffix:
            fname = fname.replace(".png", "_%s.png" % suffix)
        vmax = 100.0 * conv
        if in_us.any():
            vmax = max(vmax, float(np.nanmax(np.abs(it["field"][in_us]))))
        # a nice round ceiling that just covers the data (no clipping, no waste)
        amax_abs = float(np.nanmax(np.abs(it["field"][in_us]))) if in_us.any() else 0.0
        nice = [0.05, 0.1, 0.2, 0.25, 0.4, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0,
                4.0, 5.0, 6.0, 8.0, 10.0]
        cands = [v for v in nice if v >= amax_abs * 0.999]
        vmax_used = cands[0] if cands else nice[-1]
        levels = make_levels(vmax_used, base_ladder)
        norm = BoundaryNorm(levels, cmap.N, clip=True)
        mags = [m for m in levels if m > 0]
        tick_small = mags[int(np.argmin(np.abs(np.array(mags) - vmax_used / 4.0)))]
        cticks = [-vmax_used, -tick_small, 0.0, tick_small, vmax_used]
        draw_map(fname, it, init, f_anom, relief, X, Y, us_proj, states, provs,
                 countries, cmap, norm, levels, amax, amin, in_us, base_name,
                 cticks, it["leads"], u_label, proj)
        print("wrote", fname)


def _proj_paths_for(states, provs, countries):
    out = []
    for nm, p in states:
        out.append((nm, project_path(p)))
    return out


def draw_map(fname, item, init, f_anom, relief, X, Y, us_proj, states, provs,
             countries, cmap, norm, levels, amax, amin, in_us, base_name="baseline",
             cticks=None, leads=(1, 1), u_label="in w.e.", proj="plate"):
    """House format: plain white canvas, bold far-left title + descriptor line,
    horizontal colourbar under the map, max/min stamp top-right, credit
    bottom-right.  No banner, no tag box, no dark min/max box."""
    plt.rcParams.update({"font.family": "DejaVu Sans"})
    xr = float(X.max() - X.min()); yr = float(Y.max() - Y.min())
    A = xr / yr
    fig_w = 13.2
    ax_w = 0.975
    ax_h = ax_w * fig_w / A                     # map height in inches
    top_in, bot_in = 1.05, 0.95                 # title rows / colourbar rows
    fig_h = ax_h + top_in + bot_in
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=130)
    fig.patch.set_facecolor("#ffffff")

    ax = fig.add_axes([0.013, bot_in / fig_h, ax_w, ax_h / fig_h])
    ax.set_facecolor("white")
    ax.set_aspect("equal")
    ax.set_axis_off()

    # relief basemap
    ax.pcolormesh(X, Y, relief, shading="nearest", rasterized=True, zorder=1,
                   edgecolors="face", linewidth=0.5)
    # anomaly bands (vivid)
    pc = ax.pcolormesh(X, Y, f_anom, cmap=cmap, norm=norm, shading="nearest",
                       rasterized=True, zorder=2, alpha=0.93,
                       edgecolors="face", linewidth=0.35)

    # borders: black states, heavier national outline (= the US-Canada border)
    for nm, p in provs:
        ax.add_patch(PathPatch(project_path(p, proj), fill=False, ec="#d2d2d2", lw=0.6, zorder=3))
    for nm, p in states:
        ax.add_patch(PathPatch(project_path(p, proj), fill=False, ec="#101010", lw=0.8, zorder=4))
    for nm, lw, col in (("United States of America", 1.9, "#000000"),
                        ("Canada", 1.1, "#9a9a9a"), ("Mexico", 1.0, "#7a7a7a")):
        if nm in countries:
            ax.add_patch(PathPatch(project_path(countries[nm], proj), fill=False,
                                   ec=col, lw=lw, zorder=5))

    # ---- graticule with labelled parallels and meridians
    xspan = float(X.max() - X.min()); yspan = float(Y.max() - Y.min())
    dx, dy = 0.018 * xspan, 0.035 * yspan
    lons = [v for v in range(-120, -59, 10) if LON0 <= v <= LON1]
    lats = [v for v in range(20, 60, 10) if LAT0 <= v <= LAT1]
    for lo in lons:
        ls = np.linspace(LAT0, LAT1, 80)
        xs, ys = project(np.full_like(ls, lo), ls, proj)
        ax.plot(xs, ys, color="#a9a9a9", lw=0.65, zorder=2.6)
        xb, yb = project(lo, LAT0, proj)
        ax.text(xb, yb - dy, "%d\u00b0W" % abs(lo), fontsize=9.5, color="#2b2b2b",
                ha="center", va="top", zorder=7,
                bbox=dict(fc="white", ec="none", alpha=0.78, pad=1.2))
    for la in lats:
        ls = np.linspace(LON0, LON1, 80)
        xs, ys = project(ls, np.full_like(ls, la), proj)
        ax.plot(xs, ys, color="#a9a9a9", lw=0.65, zorder=2.6)
        xl, yl = project(LON0, la, proj)
        ax.text(xl - dx, yl, "%d\u00b0N" % la, fontsize=9.5, color="#2b2b2b",
                ha="right", va="center", zorder=7,
                bbox=dict(fc="white", ec="none", alpha=0.78, pad=1.2))

    ax.set_xlim(X.min() - dx * 1.6, X.max() + dx * 1.6)
    ax.set_ylim(Y.min() - dy * 1.7, Y.max() + dy * 0.7)

    # ---- title block (house style: bold far-left title + smaller descriptor)
    multi = leads[1] != leads[0]
    unit_word = "in" if u_label.startswith("in") else "mm"
    period = "3-month mean" if multi else "per month"
    ltxt = ("lead months %d-%d" % leads) if multi else ("lead month %d" % leads[0])
    fig.text(0.013, 1 - 0.38 / fig_h,
             "ECMWF SEAS5 Snowfall Anomaly  %s" % item["title"],
             fontsize=19, fontweight="bold", ha="left", va="center", color="#111111")
    fig.text(0.013, 1 - 0.72 / fig_h,
             "Init %s-%s-01 00Z  ·  51-member ensemble mean  ·  %s  ·  %s  ·  "
             "anomaly vs %s  ·  %s %s"
             % (init[:4], init[4:], item["span"], ltxt, base_name, u_label, period),
             fontsize=10.5, ha="left", va="center", color="#4a4a4a")

    # ---- max / min stamp (top-right, plain text - not the reference's box)
    fig.text(0.987, 1 - 0.38 / fig_h,
             "max %+.2f %s   min %+.2f %s   in view" % (amax, unit_word, amin, unit_word),
             fontsize=12, fontweight="bold", ha="right", va="center", color="#111111")

    # ---- horizontal colourbar under the map
    cax = fig.add_axes([0.30, 0.50 / fig_h, 0.40, 0.15 / fig_h])
    cb = fig.colorbar(pc, cax=cax, boundaries=levels, spacing="proportional",
                      orientation="horizontal")
    cb.set_ticks(cticks if cticks is not None else
                 [levels[0], -levels[0] / 2, 0, levels[-1] / 2, levels[-1]])
    cb.ax.tick_params(labelsize=10, colors="#202020", length=3, width=0.8)
    cb.outline.set_edgecolor("#303030")
    cb.outline.set_linewidth(1.0)
    fig.text(0.50, 0.12 / fig_h,
             "Snowfall anomaly (%s, %s)" % (u_label, period), fontsize=10.5,
             ha="center", va="center", color="#202020")

    # ---- credit (house convention: bold, bottom-right)
    fig.text(0.987, 0.016, "@Massachusettswx", fontsize=13, fontweight="bold",
             ha="right", va="bottom", color="#111111")

    fig.savefig(fname, dpi=130, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", default="202611")
    ap.add_argument("--palette", default="house", choices=["house", "ref"])
    ap.add_argument("--suffix", default="")
    ap.add_argument("--unit", default="in", choices=["in", "mm"])
    ap.add_argument("--proj", default="plate", choices=["plate", "lcc"],
                    help="plate = flat equirectangular CONUS map; lcc = conic")
    ap.add_argument("--window", type=int, default=1, choices=[1, 3],
                    help="1 = six single-month panels, 3 = rolling 3-month means")
    ap.add_argument("--baseline", default="hc", choices=["hc", "era5"],
                    help="hc = ECMWF SEAS5 hindcast climatology; era5 = ERA5 baseline")
    ap.add_argument("--era5", default="era5_snow_clim_arco.npz",
                    help="climatology npz (era5_snow_clim_arco.npz | era5_snow_clim_cds.npz)")
    args = ap.parse_args()
    build(args.init, args.palette, era5=args.era5, baseline=args.baseline,
          suffix=args.suffix, unit=args.unit, window=args.window, proj=args.proj)
