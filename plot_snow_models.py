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
from plot_snow_ref import (load_geo, load_lakes, inside, project, project_path, PathPatch,
                           MONTH_NAMES, LON0, LON1, LAT0, LAT1, PLATE_COS,
                           hillshade)
from plot_snow_totals import (SNOW_SAT_K, bilinear, boost_saturation, month_len,
                             wm_colormap, GRID)

# The snowfall panels stop here, whatever the model itself runs to: every
# model's snowfall season is shown over the same window, ending 01 July 2027.
from datetime import date, timedelta
SNOW_END = date(2027, 7, 1)
import plot_snow_ref as PSR

DATA = os.path.join(HERE, "data")

# Units.
#   "snow" - inches of SNOW DEPTH, using the standard 10:1 snow-to-water
#            ratio.  This is the unit the 0-300 in snow-depth colour bar is
#            is built for: a 6-month total of 26.7 in w.e. is 267 in of snow,
#            which lands at 89% of that bar, whereas the water equivalent
#            itself sits in the bottom 9% and looks far too low.
#   "we"   - inches of water equivalent (1 in = 25.4 mm), kept as an option.
UNIT = "snow"
SNOW_RATIO = 10.0


def unit_mult():
    return SNOW_RATIO if UNIT == "snow" else 1.0


def unit_label():
    # every panel is in inches of snow (liquid equivalent x 10:1).  The unit
    # note is kept off the graphics - "inches" says it.
    return "inches"


def unit_suffix():
    return "" if UNIT == "snow" else "_we"
OUT = os.path.join(HERE, "output")
MDIR = os.path.join(DATA, "models")

# the ECMWF's attribution, on the graphics made from its data
from ecmwf_credit import ECMWF_CREDIT, ECMWF_TAGS, credit_for  # noqa: E402
import init_info                                    # noqa: E402

# the house anomaly palette: deep brown -> white -> deep teal
ANOM_LEVELS = np.array([-4, -2, -1, -0.5, -0.25, -0.1, 0,
                         0.1, 0.25, 0.5, 1, 2, 4], dtype=float)
# The two ECCC systems are shown on the site as the official canSIPS
# multi-model ensemble, so they are not rendered on their own.
POOLED_INTO = {"eccc-canesm5": "eccc-cansips", "eccc-gem5": "eccc-cansips"}

# A snowfall anomaly is only meaningful where the model's own climate expects
# real snow.  Below this much (inches of snow depth, liquid equiv x 10:1) the
# anomaly is masked to white, so places that never see snow are not painted
# as "drier than normal".
ANOM_MASK_CLIM = 0.5


def _nice_ceil(v):
    """Smallest 'nice' number (1/2/2.5/5 x 10^n) that is >= v."""
    if v <= 0:
        return 0.0
    e = np.floor(np.log10(v))
    for m in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.5, 10.0):
        c = m * 10.0 ** e
        if c >= v - 1e-12:
            return float(c)
    return float(10.0 ** (e + 1))


def panel_scale(hi, lo=0.02):
    """Log ladder + colour list fitted to one panel's own range.

    The snow-depth ladder spans 0.01-300 in, which is right for
    a six-month total but leaves a single month crammed into its bottom three
    bins (a monthly maximum of ~5 in lands under the '1 in' tick, so the map
    looks empty and cannot be compared with the total).  This stretches the
    SAME colour ramp over the panel's own range so the structure is visible.

    Returns (levels, colors): the levels are rounded to round numbers so the
    colourbar ticks stay readable, and the colours are the reference ramp
    resampled evenly over those levels so the panel keeps the same palette.
    """
    d = json.load(open(os.path.join(DATA, "snow_depth_scale.json")))
    ref = np.array(d["levels"], dtype=float)[::-1]      # ascending
    ref_colors = list(d["colors"])[::-1]                # ascending with it
    n = len(ref)
    if not np.isfinite(hi) or hi <= lo:
        hi = lo * 2.0
    lo_ref, hi_ref = np.log10(ref[0]), np.log10(ref[-1])
    t = (np.log10(ref) - lo_ref) / (hi_ref - lo_ref)
    raw = 10.0 ** (np.log10(lo) + t * (np.log10(hi) - np.log10(lo)))
    out = []
    for v in raw:
        nv = _nice_ceil(v)
        if not out or nv > out[-1] * (1 + 1e-9):
            out.append(nv)
    if out[-1] < hi:
        out.append(_nice_ceil(hi * 1.0000001))
    levels = np.array(out, dtype=float)
    # resample the reference ramp evenly over the fitted levels
    idx = np.clip(np.round(np.linspace(0, n - 1, len(levels))).astype(int),
                  0, n - 1)
    colors = [ref_colors[i] for i in idx]
    colors = boost_saturation(colors)
    colors[0] = "#ffffff"          # 0 of snow is white
    return levels, colors


def anom_cmap():
    """Signed-log ladder in the house brown/white/teal palette."""
    stops = ["#3a2006", "#5a3410", "#7d4d1a", "#a06a26", "#c08a3e",
             "#dcb684", "#f4f6f4",
             "#b8ddd4", "#87c4b4", "#4f9c88", "#2a7563", "#164c44",
             "#042720"]
    return ListedColormap(stops, name="house")


def read_grib(path):
    """-> list of (step_hours, valid_datetime, lat, lon, values).

    The valid time is dataDate + step.  A "monthly mean" covers the period
    [dataDate, valid), so the month it represents is the month containing
    (valid - 1 day).  This is what lets one reader cope with centres that
    initialise their members on different days (UKMO perturbs the start
    date, so each member has a different step for the same valid month).
    """
    import eccodes
    from datetime import datetime as _dt, timedelta as _td
    out = []
    # The grid is the same for every member of a model, so the 64800-point
    # latitude and longitude arrays are read once and then reused.  Reading
    # them again for every record was the slowest part of a render.
    grid_cache = {}
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
                dd = int(eccodes.codes_get(gid, "dataDate"))
                vals = eccodes.codes_get_array(gid, "values")
                try:
                    key = (int(eccodes.codes_get(gid, "Ni")),
                           int(eccodes.codes_get(gid, "Nj")))
                except Exception:
                    key = None
                if key is not None and key in grid_cache:
                    lats, lons = grid_cache[key]
                else:
                    lats = eccodes.codes_get_array(gid, "latitudes")
                    lons = eccodes.codes_get_array(gid, "longitudes")
                    if key is not None:
                        grid_cache[key] = (lats, lons)
                d0 = _dt(dd // 10000, (dd // 100) % 100, dd % 100)
                valid = d0 + _td(hours=step)
                month = (valid - _td(days=1))
                out.append((step, (month.year, month.month),
                            np.asarray(lats, float), np.asarray(lons, float),
                            np.asarray(vals, float)))
            except Exception:
                pass
            eccodes.codes_release(gid)
    return out


def latlon_to_ij(lat, lon, lats, lons):
    """Match a lat/lon grid onto the file's own grid indices."""
    j = np.abs(lats[:, None] - lat[None, :]).argmin(axis=0)
    i = np.abs(lons[None, :] - lon[:, None]).argmin(axis=0)
    return i, j


def read_any(path):
    """GRIB or npz -> list of (step, (year, month), lat, lon, values).

    The NOAA systems do not come through the C3S archive, so their fields are
    stored as .npz in exactly the same convention (a rate in m w.e. s-1, the
    latitudes descending) instead of as GRIB.
    """
    if path.endswith(".npz"):
        d = np.load(path, allow_pickle=True)
        months = [tuple(int(x) for x in str(m).split("-")) for m in d["months"]]
        lat = np.asarray(d["lat"], float)
        lon = np.asarray(d["lon"], float)
        vals = np.asarray(d["values"], float)
        out = []
        for i, ym in enumerate(months):
            for j in range(vals.shape[0]):
                out.append((0, ym, lat, lon, vals[j, i].ravel()))
        return out
    return read_grib(path)


def read_snowfall(path):
    """-> dict (year, month) -> list of (lat, lon, values) records."""
    recs = read_any(path)
    if not recs:
        return None
    out = {}
    for step, ym, la, lo, v in recs:
        out.setdefault(ym, []).append((la, lo, v.astype(float)))
    return out


def read_extended(path):
    """-> dict (year, month) -> (lat, lon, metres of water equivalent, days).

    The lead months past the sixth only exist in the sub-daily product, where
    each step carries its own accumulation; the decoder there has already
    added the steps up into calendar months, so the values here are
    accumulations in metres rather than a rate in m s-1.

    The fourth item is how many days the month actually covers.  A system
    that runs to day 184 delivers only four days of the seventh month, and
    a four-day accumulation must not be shown as a whole month.
    """
    d = np.load(path, allow_pickle=True)
    months = [tuple(int(x) for x in str(m).split("-")) for m in d["months"]]
    lat = np.asarray(d["lat"], float)
    lon = np.asarray(d["lon"], float)
    acc = np.asarray(d["acc"], float)          # (members, months, lat, lon)
    ndays = []
    if "ndays" in d.files:
        ndays = [int(x) for x in d["ndays"]]
    out = {}
    for i, ym in enumerate(months):
        nd = ndays[i] if i < len(ndays) else 0
        # the axes are one-dimensional (the latitudes and the longitudes) and
        # the field is indexed [latitude, longitude], like the monthly one
        out[ym] = (lat, lon, acc[:, i].mean(axis=0), nd)
    return out


def grid_res(lats, lons):
    """The grid resolution of the field being plotted, in degrees."""
    def f(v):
        v = abs(float(v))
        return ("%g" % round(v, 3)) + "\u00b0"
    dy = abs(lats[1] - lats[0]) if len(lats) > 1 else 0.0
    dx = abs(lons[1] - lons[0]) if len(lons) > 1 else 0.0
    if dx == 0 or dy == 0:
        return ""
    return "%s \u00d7 %s" % (f(dx), f(dy))


def month_end(ym):
    import calendar
    y, m = ym
    return date(y, m, calendar.monthrange(y, m)[1])


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


def setup_grid():
    """The display grid, the US mask and the basemap pieces."""
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
    # The US state polygons include the Great Lakes, so the field was being
    # painted over Lake Michigan / Superior / Huron / Erie and Michigan came
    # out as one solid blob instead of a mitten beside a lake.
    in_lake = np.zeros(len(pts), bool)
    for nm, pth in load_lakes():
        if nm in ("Lake Michigan", "Lake Superior", "Lake Huron", "Lake Erie",
                  "Lake Ontario", "Lake St. Clair", "Lake Winnipeg",
                  "Lake Nipigon", "Lake Temagami", "Lake Simcoe",
                  "Green Bay", "Lake George", "Lake Champlain"):
            in_lake |= inside(pts, pth)
    in_lake = in_lake.reshape(LAT.shape)
    in_us &= ~in_lake
    # Flat white basemap: the hillshade used to sit under the no-snow areas
    # and made them impossible to tell apart from a light snowfall.
    relief = np.ones(LAT.shape + (3,), float)
    return X, Y, LAT, LON, in_us, in_mex, relief, countries, states, provs


def main():
    global UNIT
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", default="snow", choices=["snow", "we"],
                    help="snow = inches of snow depth (10:1), we = water equivalent")
    ap.add_argument("--only", default="", help="comma separated model tags")
    args = ap.parse_args()
    only = [x for x in args.only.split(",") if x]
    UNIT = args.unit
    print("unit: %s (%s)" % (UNIT, unit_label()), flush=True)
    os.makedirs(OUT, exist_ok=True)
    manifest = {}
    state_p = os.path.join(DATA, "models_fetched.json")
    state = json.load(open(state_p)) if os.path.exists(state_p) else {}
    X, Y, LAT, LON, in_us, in_mex, relief, countries, states, provs = setup_grid()

    wm_cmap, wm_levels = wm_colormap()
    acmap = anom_cmap()
    anorm = BoundaryNorm(ANOM_LEVELS * unit_mult(), acmap.N, clip=True)

    for tag, meta in sorted(state.items()):
        if only and tag not in only:
            continue
        if tag in POOLED_INTO and not only:
            # pooled into the official canSIPS ensemble - its own panels are
            # not published, and rendering them would only waste a cycle
            continue
        d = os.path.join(MDIR, tag)
        fg = os.path.join(d, "snowfall_monthly.grib")
        cg = os.path.join(d, "snowfall_hindcast.grib")
        if not os.path.exists(fg):          # the NOAA systems arrive as npz
            fg = os.path.join(d, "snowfall_monthly.npz")
        if not os.path.exists(cg):
            cg = os.path.join(d, "snowfall_hindcast.npz")
        if not os.path.exists(fg):
            print("skip %s (no snowfall)" % tag)
            continue
        name = meta.get("name", tag)
        init = meta.get("init") or init_info.recorded_init(tag)
        iy, im = int(init[:4]), int(init[-2:])

        by_step = read_snowfall(fg)
        if not by_step:
            print("skip %s (unreadable grib)" % tag)
            continue
        yms = [ym for ym in sorted(by_step) if month_end(ym) < SNOW_END]
        # the lead months past the sixth come from the sub-daily product
        ext = {}
        xp = os.path.join(d, "snowfall_ext.npz")
        if os.path.exists(xp):
            try:
                ext = read_extended(xp)
            except Exception as e:
                print("  %s: unreadable extended months (%s)" % (tag, e))
        # A lead month the system only covered for a few days is not a month
        # - a four-day accumulation shown as May's snowfall would be wrong,
        # and the total is the sum of the monthly panels, so it would be
        # wrong there too.  It is left out of both.
        ext_yms = [ym for ym in sorted(ext) if ym not in yms
                   and month_end(ym) < SNOW_END
                   and (not ext[ym][3] or ext[ym][3] >= 20)]
        for ym in sorted(ext):
            if ym not in yms and ym not in ext_yms and ext[ym][3]:
                print("  %s: %04d-%02d has only %d day(s) - not shown"
                      % (tag, ym[0], ym[1], ext[ym][3]), flush=True)
        yms = yms + ext_yms
        if not yms:
            print("skip %s (nothing before %s)" % (tag, SNOW_END))
            continue
        lats, lons, order = grid_axes(by_step[yms[0]][0])
        res = grid_res(lats, lons)
        clim = {}
        if os.path.exists(cg):
            for step, ym, la0, lo0, v in read_any(cg):
                clim.setdefault(ym, []).append((la0, lo0, v))

        # ensemble mean per lead month, in inches
        monthly_in = []
        labels = []
        for k, ym in enumerate(yms):
            y, m = ym
            if ym in ext_yms:
                # an accumulation in metres, not a rate
                la, lo, v, nd = ext[ym]
                ens = interp_to(LAT.ravel(), LON.ravel(), la, lo,
                                 v).reshape(LAT.shape)
                monthly_in.append(ens * 1000.0 / 25.4 * unit_mult())
            else:
                recs = by_step[ym]
                stack = np.array([to_2d(r, lats, lons, order) for r in recs])
                ens = stack.mean(axis=0)
                # the value is m w.e. s-1; convert to inches over the month
                days = month_len(y, m)
                mm = interp_to(LAT.ravel(), LON.ravel(), lats, lons,
                               ens).reshape(LAT.shape)
                monthly_in.append(mm * days * 86400.0 * 1000.0 / 25.4
                                  * unit_mult())
            labels.append("%s %d" % (MONTH_NAMES[m - 1], y))

        total_in = np.sum(monthly_in, axis=0)

        # anomaly vs the model's own hindcast climate
        anoms = []
        for k, ym in enumerate(yms):
            if ym not in clim:
                continue
            recs = clim[ym]
            stack = np.array([to_2d(r, lats, lons, order) for r in recs])
            cm = stack.mean(axis=0)
            y, m = ym
            days = month_len(y, m)
            cm_in = interp_to(LAT.ravel(), LON.ravel(), lats, lons, cm).reshape(LAT.shape)
            cm_in = cm_in * days * 86400.0 * 1000.0 / 25.4 * unit_mult()
            anoms.append((m, y, k + 1, monthly_in[k] - cm_in, cm_in))

        # ---------------- draw ----------------
        initlabel = "%s-%s-01 00Z" % (init[:4], init[5:7])
        # the ECMWF's attribution, on its own systems' graphics
        credit = credit_for(tag)
        # the accumulation window covered by the run: 1st of the first lead
        # month -> last day of the last lead month
        y0, m0 = yms[0]
        y1, m1 = yms[-1]
        # the run covers the init day up to the end of the last lead month,
        # and never past the hard 01 July 2027 end
        end_date = min(SNOW_END, month_end((y1, m1)) + timedelta(days=1))
        init_date = date(iy, im, 1)
        window = "%d %s %d to %d %s %d" % (init_date.day, MONTH_NAMES[im - 1], iy,
                                          end_date.day, MONTH_NAMES[end_date.month - 1],
                                          end_date.year)
        title_prefix = "Experimental " if meta.get("experimental") else ""
        dstr = "%02d/%02d/%04d" % (init_date.month, init_date.day, init_date.year)
        estr = "%02d/%02d/%04d" % (end_date.month, end_date.day, end_date.year)
        resnote = (" · %s grid" % res) if res else ""
        draw_map(os.path.join(OUT, "snow_%s_total_run_in%s.png" % (tag, unit_suffix())),
                 "%s  Snowfall Total — %s to %s" % (name, dstr, estr),
                 "Init %s · %d-member ensemble mean%s · accumulated %s (%d lead months) · "
                 "%s" % (initlabel, int(meta.get("members", len(by_step[yms[0]]))),
                         resnote, window, len(yms), unit_label()),
                 total_in, X, Y, in_us, relief, states, provs, countries,
                 wm_cmap, BoundaryNorm(wm_levels, wm_cmap.N, clip=True), wm_levels,
                 "Accumulated snowfall (%s)" % unit_label(),
                 white_below=float(wm_levels[0]), prefix=title_prefix,
                 credit=credit)
        for k, lab in enumerate(labels):
            mf = "snow_%s_month%02d_in%s.png" % (tag, k + 1, unit_suffix())
            manifest[mf] = {"label": lab, "lead": k + 1}
            vmax = float(np.nanmax(np.where(in_us, monthly_in[k], np.nan)))
            if UNIT == "snow":
                # the 0-300 in bar is a SNOW DEPTH bar, so the
                # depth panels are drawn on that fixed ladder
                lv, pcmap = wm_levels, wm_cmap
                cnote = ""
            else:
                lv, cols = panel_scale(vmax)
                pcmap = ListedColormap(cols, name="wm_fitted")
                cnote = " · colour scale fitted to this month"
            draw_map(os.path.join(OUT, mf),
                     "%s  Snowfall Total — %s" % (name, lab),
                     "Init %s · %d-member ensemble mean%s · lead month %d · "
                     "%s%s" % (initlabel, int(meta.get("members", len(by_step[yms[0]]))),
                               resnote, k + 1, unit_label(), cnote),
                     monthly_in[k], X, Y, in_us, relief, states, provs, countries,
                     pcmap, BoundaryNorm(lv, pcmap.N, clip=True), lv,
                     "Accumulated snowfall (%s)" % unit_label(),
                     white_below=float(lv[0]), prefix=title_prefix,
                     credit=credit)
        for (m, y, lead, a, cl_in) in anoms:
            # An anomaly where the model itself expects essentially no snow is
            # noise, not signal: it made the Gulf Coast and Florida look "dry"
            # on the maps.  Mask it to white below ANOM_MASK_CLIM inches.
            a = np.where(cl_in >= ANOM_MASK_CLIM, a, np.nan)
            af = "SNOW_%s_%s%d_anom_in%s.png" % (tag.upper(), MONTH_NAMES[m - 1], y, unit_suffix())
            manifest[af] = {"label": "%s %d" % (MONTH_NAMES[m - 1], y),
                            "lead": lead}
            draw_map(os.path.join(OUT, af),
                     "%s Snowfall Anomaly  %s %d" % (name, MONTH_NAMES[m - 1], y),
                     "Init %s · %d-member ensemble mean%s · lead month %d · "
                     "anomaly vs %s hindcast climate · %s" % (
                         initlabel, int(meta.get("members", len(by_step[yms[0]]))),
                         resnote, lead, name, unit_label()),
                     a, X, Y, in_us, relief, states, provs, countries,
                     acmap, anorm, ANOM_LEVELS * unit_mult(),
                     "Snowfall anomaly (%s)" % unit_label(),
                     prefix=title_prefix, credit=credit)
        # drop any panel left over from an earlier, longer run
        keep = set(manifest.keys())
        keep.add("snow_%s_total_run_in%s.png" % (tag, unit_suffix()))
        for f in os.listdir(OUT):
            if (f.startswith("snow_%s_" % tag) or
                    f.startswith("SNOW_%s_" % tag.upper())) and f.endswith(".png"):
                if f not in keep:
                    os.remove(os.path.join(OUT, f))
                    print("  removed stale", f)
        print("rendered %-16s init=%s  months=%d anomalies=%d"
              % (tag, init, len(monthly_in), len(anoms)), flush=True)

    mp = os.path.join(DATA, "render_manifest.json")
    allm = {}
    if os.path.exists(mp):
        try:
            allm = json.load(open(mp))
        except Exception:
            allm = {}
    allm.update(manifest)
    json.dump(allm, open(mp, "w"), indent=1)
    print("manifest: %d files" % len(allm))


def draw_map(fname, title, subtitle, field, X, Y, in_us, relief, states, provs,
             countries, cmap, norm, levels, cbar_label, white_below=None,
             prefix="", credit=""):
    plt.rcParams.update({"font.family": "DejaVu Sans"})
    xr = float(X.max() - X.min()); yr = float(Y.max() - Y.min())
    fig_w = 14.0
    ax_w = 0.975
    ax_h = ax_w * fig_w / (xr / yr)
    # the margins are kept tight: the title block above and the colour bar
    # below are all the space the figure needs
    fig_h = ax_h + 0.95 + 0.95
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=130)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0.013, 0.95 / fig_h, ax_w, ax_h / fig_h])
    ax.set_aspect("equal"); ax.set_axis_off()

    ax.pcolormesh(X, Y, relief, shading="nearest", rasterized=True, zorder=1,
                  edgecolors="face", linewidth=0.5)
    fl = np.ma.masked_where(~in_us, field)
    if white_below is not None:
        # no snowfall = white, so only real accumulation takes a colour
        fl = np.ma.masked_where(fl < white_below, fl)
    cmap = cmap.copy(); cmap.set_bad("white")
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

    # the title has to stay clear of the max/min stamp in the top right, so it
    # is measured and shrunk until it fits.  A coloured prefix ("Experimental ")
    # is drawn first and the rest of the title follows it.
    vm = np.where(in_us, field, np.nan)
    stamp = ""
    if np.isfinite(vm).any():
        stamp = "max %+.2f in   min %+.2f in" % (np.nanmax(vm), np.nanmin(vm))
    base_fs = 21.0
    trest = fig.text(0.013, 1 - 0.40 / fig_h, title, fontsize=base_fs,
                     fontweight="bold", ha="left", va="center", color="#111111")
    tpre = None
    if prefix:
        tpre = fig.text(0.013, 1 - 0.40 / fig_h, prefix, fontsize=base_fs,
                        fontweight="bold", ha="left", va="center", color="#c00000")
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    fp = trest.get_fontproperties()
    maxw = (0.987 - 0.013) * fig_w * 72.0 - 12.0
    if stamp:
        sw = rend.get_text_width_height_descent(stamp, fp, ismath=False)[0] * 10.5 / base_fs
        maxw -= sw + 18.0
    tw = rend.get_text_width_height_descent(title, fp, ismath=False)[0]
    pw = 0.0
    if tpre is not None:
        pw = rend.get_text_width_height_descent(prefix, fp, ismath=False)[0]
    if tw + pw > maxw:
        k = maxw / (tw + pw)
        fs = max(12.0, base_fs * k)
        trest.set_fontsize(fs)
        if tpre is not None:
            tpre.set_fontsize(fs)
    if tpre is not None:
        # the rest of the title starts where the coloured prefix actually ends
        fig.canvas.draw()
        bb = tpre.get_window_extent(rend)
        trest.set_x(bb.x1 / (fig_w * fig.dpi))
        fig.canvas.draw()
    # the descriptor line is long (model list, window, resolution) and must
    # never run off the right edge
    sub_t = fig.text(0.013, 1 - 0.76 / fig_h, subtitle, fontsize=10.5, ha="left",
                     va="center", color="#4a4a4a")
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    sfp = sub_t.get_fontproperties()
    smaxw = (0.987 - 0.013) * fig_w * 72.0
    sw = rend.get_text_width_height_descent(subtitle, sfp, ismath=False)[0]
    if sw > smaxw:
        sub_t.set_fontsize(max(7.5, 10.5 * smaxw / sw))
    if stamp:
        fig.text(0.987, 1 - 0.40 / fig_h, stamp,
                 fontsize=10.5, ha="right", va="center", color="#111111")
    cax = fig.add_axes([0.30, 0.56 / fig_h, 0.40, 0.16 / fig_h])
    cb = fig.colorbar(pc, cax=cax, boundaries=levels, spacing="uniform",
                      orientation="horizontal")
    ticks = levels[::2].tolist() if len(levels) > 12 else levels.tolist()
    cb.set_ticks(ticks)
    cb.ax.tick_params(labelsize=9.5, colors="#202020", length=3, width=0.8)
    cb.outline.set_edgecolor("#303030"); cb.outline.set_linewidth(1.0)
    fig.text(0.50, 0.30 / fig_h, cbar_label, fontsize=10.5, ha="center",
             va="center", color="#202020")
    fig.text(0.987, 0.13 / fig_h, "@Massachusettswx", fontsize=13,
             fontweight="bold", ha="right", va="bottom", color="#111111")
    if credit:
        # the ECMWF's own attribution, on the bottom right inside the graphic
        fig.text(0.987, 0.015 / fig_h, credit, fontsize=7.6, ha="right",
                 va="bottom", color="#4a4a4a")
    fig.savefig(fname, dpi=130, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
