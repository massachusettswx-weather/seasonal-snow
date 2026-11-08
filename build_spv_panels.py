"""Render the 10 hPa SPV panels for every seasonal model we have u10 for.

Two data paths:

  * DAILY - the C3S *original* (subdaily) product carries every ensemble member
    at 12-hourly resolution.  This is the path used for every centre now, and
    it is what makes the chart look like the ECMWF one: daily member traces,
    daily ensemble mean, daily ERA5 climatology.
  * MONTHLY - the fallback, one value per lead month.

The u10 files differ between centres, so the monthly reader groups the GRIB
records by their VALID DATE (dataDate + step) rather than by the step alone:
UKMO packs 60 members per lead month with a different step for each member
(the perturbed members are initialised on different days), and grouping by
valid date handles that and gives the true member count.

Model values are plotted on the calendar day they belong to (the 12Z state of
that date), so the model trace and the ERA5 climatology line - which is also a
12Z value - sit on exactly the same x positions.

usage: python3 build_spv_panels.py
"""
import os, sys, json, collections
import numpy as np
from datetime import datetime, timedelta, date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from plot_spv import render_spv, load_era5   # noqa: E402
from u10_daily import load_npz               # noqa: E402

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


def month_table(times, ens, era, same_days=False):
    """Lead-month means: model ensemble mean vs the ERA5 climatology.

    same_days=True  - the model has a value for every day, so compare against
                      the ERA5 mean over exactly those days.
    same_days=False - the model's value for a lead month is the whole-month
                      mean, so it must be compared against the full calendar
                      month of ERA5, not the days that happen to be in the
                      clipped window.
    """
    emap = {t.date(): v for t, v in zip(era["t"], era["mean"])}
    buckets = collections.defaultdict(list)
    ebuck = collections.defaultdict(list)
    for t, e in zip(times, ens):
        buckets[(t.year, t.month)].append(float(e))
        if t.date() in emap:
            ebuck[(t.year, t.month)].append(emap[t.date()])
    rows = []
    for key in sorted(buckets):
        ev = ebuck.get(key)
        if not same_days:
            # full calendar month of ERA5
            yy, mm = key
            sel = [v for t, v in zip(era["t"], era["mean"])
                   if t.year == yy and t.month == mm]
            ev = sel or None
        rows.append(["%s %d" % (MONTHS[key[1] - 1], key[0]),
                     "%.1f" % float(np.nanmean(buckets[key])),
                     "%.1f" % (float(np.nanmean(ev)) if ev else float("nan"))])
    return {"head": ["Model ens. mean (m/s)", "ERA5 clim. (m/s)"], "rows": rows}


def render_daily(tag, name, init, times, m60, mnh, daily_label):
    """Draw the 60N and NH panels from a daily member matrix."""
    for dom, mat, key in (("60", m60, "60N"), ("NH", mnh, "NH")):
        era = load_era5(dom, int(init[:4]))
        label = "60°N" if dom == "60" else "Northern Hemisphere"
        fn = os.path.join(OUT, "SPV_%s_%s.png" % (tag, key))
        render_spv(mat, times, name, fn, domain=dom, era5=era, model_clim=None,
                   n_members=mat.shape[0],
                   subtitle="Run init 01 %s %d · %d daily 12Z steps (%d members)"
                            " · lead months 1–7 · ERA5 climatology 1991–2020"
                            % (MONTHS[int(init[-2:]) - 1], int(init[:4]), len(times),
                               mat.shape[0]),
                   footer="Data: %s seasonal forecast (CDS) · ERA5 climatology "
                          "1991–2020" % name,
                   title="%s · 10 hPa · %s Zonal-Mean Zonal Wind (m/s)"
                         % (name, label))
        json.dump(month_table(times, np.nanmean(mat, axis=0), era, same_days=True),
                  open(os.path.join(OUT, "SPV_%s_%s_table.json" % (tag, key)), "w"),
                  indent=1)
        print("wrote %s  (daily, %d members, %d days)" % (fn, mat.shape[0], len(times)))


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
        json.dump(month_table(times, np.nanmean(mem, axis=0), era, same_days=True),
                  open(os.path.join(OUT, "SPV_ecmwf-seas5_%s_table.json" % key), "w"),
                  indent=1)
        print("wrote %s (daily, %d members)" % (fn, mem.shape[0]))


def main():
    fp = os.path.join(DATA, "models_fetched.json")
    state = json.load(open(fp)) if os.path.exists(fp) else {}

    for tag, meta in sorted(state.items()):
        name = meta.get("name", tag)
        init = meta.get("init", "2026-11")
        try:
            build_one(tag, name, init)
        except Exception as e:
            # one bad download must not stop the other centres from rendering
            print("!! %s failed: %s" % (tag, str(e)[:300]), flush=True)


def build_one(tag, name, init):
        if tag == "ecmwf-seas5" and os.path.exists(
                os.path.join(DATA, "seas5_202611_daily.npz")):
            build_ecmwf_daily(name, init)
            return

        # daily product from the C3S subdaily archive
        npz = os.path.join(MDIR, tag, "u10_daily.npz")
        if os.path.exists(npz):
            dates, m60, mnh, members, m = load_npz(npz)
            times = [datetime(d.year, d.month, d.day) for d in dates]
            render_daily(tag, name, init, times, m60, mnh, "daily")
            return

        # monthly fallback
        ug = os.path.join(MDIR, tag, "u10_monthly.grib")
        if not os.path.exists(ug):
            print("skip %s (no u10)" % tag)
            return
        by_date = read_u10(ug)
        if not by_date:
            print("skip %s (unreadable u10)" % tag)
            return
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
