"""Compare the seasonal models' snowfall against ERA5 observed snowfall.

The ERA5 reference (data/era5_snow_clim_conus.npz) is the official
monthly_averaged_reanalysis snowfall climatology for 1991-2020 over the
CONUS box, in mm w.e. per calendar month.

For every model we compute the ensemble-mean monthly accumulation on the
model's own grid, put it on the ERA5 grid and report:
  * the ratio model/ERA5 over the wet points (ERA5 > 10 mm/month)
  * the spatial maximum of both over the same domain
  * the ratio over the Sierra / Cascades / Rocky-Mountain boxes

usage: python3 compare_snow_era5.py
"""
import os, sys, json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from plot_snow_totals import month_len
from plot_snow_models import read_snowfall, grid_axes, to_2d, interp_to

DATA = os.path.join(HERE, "data")
ERA = os.path.join(DATA, "era5_snow_clim_conus.npz")
MN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

BOXES = {
    "Sierra  118-121W 37-40N": (37, 40, 238, 242),
    "Cascades 121-124W 45-49N": (45, 49, 236, 239),
    "Colorado 106-109W 39-41N": (39, 41, 251, 254),
    "GreatLakes 85-90W 43-47N": (43, 47, 270, 275),
}


def boxes_for(lat, lon):
    out = {}
    for name, (la0, la1, lo0, lo1) in BOXES.items():
        m = (lat >= la0) & (lat <= la1) & (lon >= lo0) & (lon <= lo1)
        out[name] = m
    return out


def main():
    if not os.path.exists(ERA):
        print("missing", ERA)
        return
    e = np.load(ERA)
    clim, elat, elon = e["clim"], e["lat"], e["lon"]
    emons = list(e["months"])
    elon = np.where(elon > 180, elon - 360.0, elon)
    print("ERA5 reference: %d lat x %d lon, lat %.2f..%.2f lon %.2f..%.2f"
          % (len(elat), len(elon), elat.min(), elat.max(), elon.min(), elon.max()))
    print("calendar months:", [MN[(m - 1) % 12] for m in emons])
    print("ERA5 max per month (mm):", np.round(clim.reshape(6, -1).max(axis=1), 1))
    bx = boxes_for(elat, elon)
    for name, m in bx.items():
        if m.any():
            print("   %-30s n=%3d  ERA5 max %6.1f mm" %
                  (name, int(m.sum()), clim[:, m].max()))
    print()

    glat, glon = np.meshgrid(elat, elon, indexing="ij")
    pts = np.column_stack([glon.ravel(), glat.ravel()])

    state = json.load(open(os.path.join(DATA, "models_fetched.json")))
    for tag, meta in sorted(state.items()):
        fg = os.path.join(DATA, "models", tag, "snowfall_monthly.grib")
        if not os.path.exists(fg):
            continue
        by = read_snowfall(fg)
        if not by:
            continue
        yms = sorted(by)
        lats, lons, order = grid_axes(by[yms[0]][0])
        # ERA5 calendar month for each lead month
        lead_mon = []
        for ym in yms:
            y, m = ym
            lead_mon.append(m)
        rows = []
        for k, ym in enumerate(yms):
            ens = np.array([to_2d(r, lats, lons, order) for r in by[ym]]).mean(axis=0)
            y, m = ym
            mm = ens * month_len(y, m) * 86400.0 * 1000.0      # mm/month
            g = interp_to(pts[:, 0], pts[:, 1], lats, lons, mm).reshape(clim.shape[1:])
            # ERA5 reference for the SAME calendar month
            j = emons.index(m) if m in emons else None
            if j is None:
                continue
            c = clim[j]
            wet = c > 10.0
            rat = g[wet] / c[wet]
            rows.append((m, float(np.median(rat)), float(g[wet].max()),
                         float(c[wet].max()),
                         {n: (float(g[m2].mean() / c[m2].mean())
                              if m2.any() and c[m2].mean() > 0 else np.nan)
                          for n, m2 in bx.items()}))
        print("=== %-16s init=%s" % (tag, meta.get("init")))
        for m, rat, gmax, cmax, bxr in rows:
            print("   %-4s  model/ERA5 median %5.2f   max model %6.1f mm  ERA5 %6.1f mm   %s"
                  % (MN[(m - 1) % 12], rat, gmax, cmax,
                     "  ".join("%s %.2f" % (n.split()[0], v) for n, v in bxr.items())))


if __name__ == "__main__":
    main()
