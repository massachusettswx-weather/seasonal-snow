"""Render the site's 10 hPa SPV panels for every seasonal model we have data
for, and write the lead-month tables that go with them.

For each model the daily member traces at 60N and over the Northern
Hemisphere are turned into the house-style SPV chart (members, ensemble mean,
ERA5 1991-2020 climatology with percentile bands and record bounds, and the
model's own climate mean where one exists).

usage: python3 build_spv_panels.py
"""
import os, sys, json
import numpy as np
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from plot_spv import render_spv, load_era5, MONTHS  # noqa: E402

DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "output")


def era5_window(init_dt, ndays):
    """ERA5 climatology clipped to the model's own lead window."""
    e = load_era5("60", init_dt.year)
    t0, t1 = e["t"][0], e["t"][-1]
    return {"t": e["t"], "mean": e["mean"], "sd": e["sd"],
            "p10": e["p10"], "p30": e["p30"], "p70": e["p70"], "p90": e["p90"],
            "rmin": e["rmin"], "rmax": e["rmax"]}


def month_table(mem, times, era5, model_clim=None, label=""):
    """Lead-month means for the model, ERA5 and (optionally) the model climate."""
    eramean = np.asarray(era5["mean"], dtype=float)
    rows = []
    seen = []
    for t in times:
        key = (t.year, t.month)
        if key not in seen:
            seen.append(key)
    for key in seen:
        idx = [i for i, t in enumerate(times) if (t.year, t.month) == key]
        ens = float(np.nanmean(mem[:, idx]))
        eidx = [i for i, t in enumerate(era5["t"]) if (t.year, t.month) == key]
        era = float(np.nanmean(eramean[eidx])) if eidx else np.nan
        rows.append(["%s %d" % (MONTHS[key[1] - 1], key[0]),
                     "%.1f" % ens, "%.1f" % era])
    return {"head": ["Model ens. mean (m/s)", "ERA5 clim. (m/s)"], "rows": rows}


def build_ecmwf():
    tag = "ecmwf-seas5"
    init = "202611"
    d = np.load(os.path.join(DATA, "seas5_%s_daily.npz" % init))
    steps = d["steps"]
    init_dt = datetime(2026, 11, 1)
    times = [init_dt + timedelta(hours=int(s)) for s in steps]

    cpath = os.path.join(DATA, "seas5_%s_clim.npz" % init)
    clim = np.load(cpath) if os.path.exists(cpath) else None
    m7p = os.path.join(DATA, "model_clim_m7_month11.npz")
    m7 = np.load(m7p) if os.path.exists(m7p) else None

    from plot_seas5_daily import model_climate_curve

    out = {}
    for dom, key in (("60", "60N"), ("NH", "NH")):
        mem = d["members60"] if dom == "60" else d["members_nh"]
        era = load_era5(dom, 2026)
        mc = None
        if clim is not None:
            mcv = clim["clim60"] if dom == "60" else clim["clim_nh"]
            m7v = None
            if m7 is not None:
                m7v = m7["clim60"] if dom == "60" else m7["clim_nh"]
            mc = model_climate_curve(2026, 11, mcv, m7v)
        label = "60&deg;N" if dom == "60" else "Northern Hemisphere"
        fn = os.path.join(OUT, "SPV_%s_%s.png" % (tag, key))
        render_spv(
            mem, times, "ECMWF SEAS5", fn, domain=dom, era5=era,
            model_clim=mc,
            model_clim_label="ECMWF model-climate mean (init Nov)",
            n_members=mem.shape[0],
            subtitle="Run init 01 Nov 2026 &middot; %d daily 12Z steps (51 members) "
                     "&middot; lead months 1&ndash;7 &middot; ERA5 climatology 1991&ndash;2020" % len(times),
            footer="Data: ECMWF seasonal forecast (CDS) &middot; ERA5 climatology 1991&ndash;2020 "
                   "&middot; lead month 7 model climate reconstructed from the model's own past runs",
            title="ECMWF SEAS5  &middot;  10 hPa  &middot;  %s Zonal-Mean Zonal Wind (m/s)" % label)
        tbl = month_table(mem, times, era, mc)
        json.dump(tbl, open(os.path.join(OUT, "SPV_%s_%s_table.json" % (tag, key)), "w"), indent=1)
        print("wrote", fn)


def main():
    build_ecmwf()


if __name__ == "__main__":
    main()
