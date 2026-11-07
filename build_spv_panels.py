"""Render the 10 hPa SPV panels for every seasonal model we have u10 for.

The u10 files differ between centres, so the reader groups the GRIB records by
their VALID DATE (dataDate + step) rather than by the step alone:

  * UKMO packs 60 members per lead month with a different step for each
    member (the perturbed members are initialised on different days);
  * the other centres use one step per lead month with N members.

Grouping by valid date handles both and gives the true member count.

For each model the fields are reduced to the zonal mean at 60N and over the
Northern Hemisphere, then drawn in the house style: every ensemble member,
the ensemble mean, the ERA5 1991-2020 climatology with percentile bands and
record bounds.

usage: python3 build_spv_panels.py
"""
import os, sys, json, collections
import numpy as np
from datetime import datetime, timedelta, date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from plot_spv import render_spv, load_era5   # noqa: E402

DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "output")
MDIR = os.path.join(DATA, "models")
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def zonal_mean(v, lats):
    w = np.cos(np.deg2rad(lats))[:, None]
    return float((v * w).sum() / w.sum())


def point_mean(v, lats, lat0):
    m = np.abs(lats - lat0) <= 0.5
    return float(v[m, :].mean()) if m.any() else np.nan


def read_u10(path):
    """-> {valid_date: [(s60, sNH), ...]} plus the member count."""
    import eccodes
    by_date = collections.defaultdict(list)
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                dd = int(eccodes.codes_get(gid, "dataDate"))
                st = int(eccodes.codes_get(gid, "step"))
                la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                lo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                lats = np.unique(la)[::-1]
                lons = np.unique(lo)
                v = v.reshape(len(lats), len(lons))
                d = date(dd // 10000, (dd // 100) % 100, dd % 100) + timedelta(hours=st)
                by_date[d].append((point_mean(v, lats, 60.0), zonal_mean(v, lats)))
            except Exception:
                pass
            eccodes.codes_release(gid)
    return by_date


def month_table(times, ens, era):
    eramean = np.asarray(era["mean"], float)
    rows = []
    for t, e in zip(times, ens):
        eidx = [i for i, et in enumerate(era["t"])
                if et.year == t.year and et.month == t.month]
        ev = float(np.nanmean(eramean[eidx])) if eidx else np.nan
        rows.append(["%s %d" % (MONTHS[t.month - 1], t.year), "%.1f" % float(e), "%.1f" % ev])
    return {"head": ["Model ens. mean (m/s)", "ERA5 clim. (m/s)"], "rows": rows}


def build_ecmwf_daily(name, init):
    """The ECMWF run has daily 12Z members -> the full daily SPV chart."""
    from plot_seas5_daily import model_climate_curve
    d = np.load(os.path.join(DATA, "seas5_202611_daily.npz"))
    steps = d["steps"]
    init_dt = datetime(int(init[:4]), int(init[-2:]), 1)
    times = [init_dt + timedelta(hours=int(s)) for s in steps]
    clim = np.load(os.path.join(DATA, "seas5_202611_clim.npz"))
    p7 = os.path.join(DATA, "model_clim_m7_month%02d.npz" % int(init[-2:]))
    m7 = np.load(p7) if os.path.exists(p7) else None
    for dom, key in (("60", "60N"), ("NH", "NH")):
        mem = d["members60"] if dom == "60" else d["members_nh"]
        era = load_era5(dom, int(init[:4]))
        mc = None
        if clim is not None:
            mcv = clim["clim60"] if dom == "60" else clim["clim_nh"]
            m7v = None
            if m7 is not None:
                m7v = m7["clim60"] if dom == "60" else m7["clim_nh"]
            mc = model_climate_curve(int(init[:4]), int(init[-2:]), mcv, m7v)
        label = "60°N" if dom == "60" else "Northern Hemisphere"
        fn = os.path.join(OUT, "SPV_ecmwf-seas5_%s.png" % key)
        render_spv(mem, times, name, fn, domain=dom, era5=era, model_clim=mc,
                   model_clim_label="ECMWF model-climate mean (init Nov)",
                   n_members=mem.shape[0],
                   subtitle="Run init 01 %s %d · %d daily 12Z steps (%d members)"
                            " · lead months 1–7 · ERA5 climatology 1991–2020"
                            % (MONTHS[int(init[-2:]) - 1], int(init[:4]), len(times),
                               mem.shape[0]),
                   footer="Data: ECMWF seasonal forecast (CDS) · ERA5 climatology "
                          "1991–2020 · lead month 7 model climate reconstructed from "
                          "the model's own past runs",
                   title="%s · 10 hPa · %s Zonal-Mean Zonal Wind (m/s)" % (name, label))
        json.dump(month_table(times, np.nanmean(mem, axis=0), era),
                  open(os.path.join(OUT, "SPV_ecmwf-seas5_%s_table.json" % key), "w"),
                  indent=1)
        print("wrote %s (daily, %d members)" % (fn, mem.shape[0]))


def main():
    fp = os.path.join(DATA, "models_fetched.json")
    state = json.load(open(fp)) if os.path.exists(fp) else {}

    for tag, meta in sorted(state.items()):
        name = meta.get("name", tag)
        init = meta.get("init", "2026-11")

        if tag == "ecmwf-seas5" and os.path.exists(
                os.path.join(DATA, "seas5_202611_daily.npz")):
            build_ecmwf_daily(name, init)
            continue

        ug = os.path.join(MDIR, tag, "u10_monthly.grib")
        if not os.path.exists(ug):
            print("skip %s (no u10)" % tag)
            continue
        by_date = read_u10(ug)
        if not by_date:
            print("skip %s (unreadable u10)" % tag)
            continue
        dates = sorted(by_date)
        nmem = max(len(v) for v in by_date.values())
        times = [datetime(d.year, d.month, d.day) for d in dates]

        for dom, idx, key in (("60", 0, "60N"), ("NH", 1, "NH")):
            arr = np.full((nmem, len(dates)), np.nan)
            for j, d in enumerate(dates):
                vals = [r[idx] for r in by_date[d]]
                arr[:len(vals), j] = vals
            ens = np.nanmean(arr, axis=0)

            era = load_era5(dom, int(init[:4]))
            t0, t1 = times[0] - timedelta(days=15), times[-1] + timedelta(days=15)
            keep = [i for i, t in enumerate(era["t"]) if t0 <= t <= t1]
            era_cut = {k: [era[k][i] for i in keep]
                       for k in ("t", "mean", "p10", "p30", "p70", "p90",
                                 "rmin", "rmax")}

            label = "60°N" if dom == "60" else "Northern Hemisphere"
            fn = os.path.join(OUT, "SPV_%s_%s.png" % (tag, key))
            render_spv(arr, times, name, fn, domain=dom, era5=era_cut,
                       model_clim=None, n_members=nmem,
                       subtitle="Run init 01 %s %d · %d members · monthly means at "
                                "10 hPa · ERA5 climatology 1991–2020"
                                % (MONTHS[int(init[-2:]) - 1], int(init[:4]), nmem),
                       footer="Data: %s seasonal forecast (CDS) · ERA5 climatology "
                              "1991–2020" % name,
                       title="%s · 10 hPa · %s Zonal-Mean Zonal Wind (m/s)"
                             % (name, label))
            json.dump(month_table(times, ens, era_cut),
                      open(os.path.join(OUT, "SPV_%s_%s_table.json" % (tag, key)),
                           "w"), indent=1)
            print("wrote %s  (%d members, %d lead months)" % (fn, nmem, len(dates)))


if __name__ == "__main__":
    main()
