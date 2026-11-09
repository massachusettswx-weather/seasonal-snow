"""Audit the modelled snowfall: provenance + regional dry-bias check.

Re-uses the exact reader/interpolation path of plot_snow_models.py, so the
numbers here are the numbers that are rendered.

    python3 audit_snow.py
"""
import os
import numpy as np

from plot_snow_models import grid_axes, interp_to, read_snowfall, to_2d
from plot_snow_ref import LON0, LON1, LAT0, LAT1
from plot_snow_totals import GRID, month_len

_lo = np.arange(LON0, LON1 + GRID / 2, GRID)
_la = np.arange(LAT0, LAT1 + GRID / 2, GRID)
LON, LAT = np.meshgrid(_lo, _la)

DATA = "data"
MDIR = os.path.join(DATA, "models")
SNOW_END = (2027, 7, 1)

# regions: name, lat0, lat1, lon0, lon1  (lon negative = west)
REGIONS = [
    ("Gulf coast TX-LA",  28.5, 31.0,  -97.0, -92.0),
    ("Florida",           26.5, 30.0,  -83.0, -80.0),
    ("SE interior",       31.5, 35.0,  -88.0, -83.0),
    ("Sierra/Rockies",    36.5, 41.0, -114.0, -106.0),
    ("Appalachians",      36.0, 39.0,  -83.0, -79.0),
    ("Central Plains",    40.0, 45.0, -100.0, -95.0),
    ("CONUS total",       24.5, 50.0, -125.0, -66.5),
]


def model_total(tag):
    """-> (forecast_in, climate_in, months, label) on the common CONUS grid."""
    fg = os.path.join(MDIR, tag, "snowfall_monthly.grib")
    fg = fg if os.path.exists(fg) else os.path.join(MDIR, tag, "snowfall_monthly.npz")
    cg = os.path.join(MDIR, tag, "snowfall_hindcast.grib")
    cg = cg if os.path.exists(cg) else os.path.join(MDIR, tag, "snowfall_hindcast.npz")
    by_step = read_snowfall(fg)
    if not by_step:
        return None
    yms = [ym for ym in sorted(by_step)
           if (ym[0], ym[1]) < SNOW_END or
           (ym[0], ym[1]) == SNOW_END[:2] and SNOW_END[2] > 1]
    lats, lons, order = grid_axes(by_step[yms[0]][0])

    def total(path, key):
        recs = read_snowfall(path) or {}
        acc = None
        for ym in yms:
            if ym not in recs:
                continue
            stack = np.array([to_2d(r, lats, lons, order) for r in recs[ym]])
            ens = stack.mean(axis=0)
            g = interp_to(LAT.ravel(), LON.ravel(), lats, lons, ens).reshape(LAT.shape)
            y, m = ym
            v = g * month_len(y, m) * 86400.0 * 1000.0 / 25.4 * 10.0   # -> in of snow depth
            acc = v if acc is None else acc + v
        return acc

    fc = total(fg, "f")
    cl = total(cg, "c") if os.path.exists(cg) else None
    return fc, cl, yms


def era5_clim():
    p = os.path.join(DATA, "era5_snow_clim_arco_conus.npz")
    if not os.path.exists(p):
        return None
    z = np.load(p, allow_pickle=True)
    c = z["clim"]                       # mm w.e. per month (ARCO derivation)
    la = np.asarray(z["lat"], float)
    lo = np.asarray(z["lon"], float)
    if lo.max() > 180:                       # 0..360 -> -180..180
        lo = np.where(lo > 180, lo - 360, lo)
    tot = None
    for i in range(c.shape[0]):
        m = int(z["months"][i])
        days = month_len(2027 if m >= 11 else 2026, m)
        g = interp_to(LAT.ravel(), LON.ravel(), la, lo, c[i]).reshape(LAT.shape)
        v = g / 25.4 * 10.0               # mm w.e. -> in w.e. -> in of snow depth
        tot = v if tot is None else tot + v
    return tot


def region_mean(field, r):
    _, la0, la1, lo0, lo1 = r
    m = (LAT >= la0) & (LAT <= la1) & (LON >= lo0) & (LON <= lo1)
    if not m.any():
        return float("nan")
    return float(field[m].mean())


def main():
    e = era5_clim()
    print("ERA5 (ARCO) 1991-2020 climatology, Nov-Apr, inches of snow depth:\n")
    hdr = "%-16s %8s" % ("region", "ERA5")
    rows = []
    for r in REGIONS:
        rows.append((r[0], region_mean(e, r) if e is not None else float("nan")))
    for n, v in rows:
        print("%-16s %8.1f" % (n, v))

    tags = sorted(os.listdir(MDIR))
    print("\n" + "=" * 100)
    for tag in tags:
        res = model_total(tag)
        if not res:
            continue
        fc, cl, yms = res
        name = os.path.basename(tag)
        print("\n### %s   months %s" % (name,
              ", ".join("%d/%02d" % (y, m) for y, m in yms)))
        print("%-16s %9s %9s %9s %8s %8s" % ("region", "fcst(in)", "clim(in)",
                                            "ERA5(in)", "f/c", "f/ERA5"))
        for r in REGIONS:
            f = region_mean(fc, r)
            c = region_mean(cl, r) if cl is not None else float("nan")
            ev = region_mean(e, r) if e is not None else float("nan")
            fc_ = f / c if c and abs(c) > 1e-6 else float("nan")
            fe = f / ev if ev and abs(ev) > 1e-6 else float("nan")
            print("%-16s %9.1f %9.1f %9.1f %8s %8s" %
                  (r[0], f, c, ev,
                   ("%.2f" % fc_) if fc_ == fc_ else "-",
                   ("%.2f" % fe) if fe == fe else "-"))


if __name__ == "__main__":
    main()
