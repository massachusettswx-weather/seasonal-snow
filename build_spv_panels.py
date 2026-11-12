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
import glob
import os, sys, json, collections, calendar
import numpy as np
from datetime import datetime, timedelta, date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from plot_spv import render_spv, load_era5   # noqa: E402
from ecmwf_credit import credit_for           # noqa: E402
import init_info                             # noqa: E402
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


def grid_res(path):
    """The model's source grid resolution in degrees, from its u10 GRIB."""
    import eccodes
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                return ""
            try:
                la = np.unique(np.asarray(eccodes.codes_get_array(gid, "latitudes"), float))
                lo = np.unique(np.asarray(eccodes.codes_get_array(gid, "longitudes"), float))
                lo = np.where(lo > 180, lo - 360, lo)
                lo = np.sort(lo)
                dy = abs(la[1] - la[0])
                dx = abs(lo[1] - lo[0])
                return "%g° × %g°" % (round(dx, 3), round(dy, 3))
            finally:
                eccodes.codes_release(gid)
    except Exception:
        return ""


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
    # A lead month the run only covered for a couple of days is not a lead
    # month: the ECCC's run ends two days into June, and calling that eight
    # lead months would overstate what the chart shows.  The count is of
    # whole months, and the end date is given so the reader can see exactly
    # how far the run goes.
    from collections import Counter as _C
    _cnt = _C((t.year, t.month) for t in times)
    nlead = sum(1 for k, v in _cnt.items() if v >= 20)
    last = times[-1]
    res = grid_res(os.path.join(MDIR, tag, "u10_monthly.grib"))
    resnote = (" · %s grid" % res) if res else ""
    for dom, mat, key in (("60", m60, "60N"), ("NH", mnh, "NH")):
        era = load_era5(dom, int(init[:4]))
        label = "60°N" if dom == "60" else "Northern Hemisphere"
        fn = os.path.join(OUT, "SPV_%s_%s.png" % (tag, key))
        render_spv(mat, times, name, fn, domain=dom, era5=era, model_clim=None,
                   n_members=mat.shape[0], credit=credit_for(tag),
                   subtitle="Run init 01 %s %d · %d daily 12Z steps (%d members)%s"
                            " · lead months 1–%d (through %d %s %d) · "
                            "ERA5 climatology 1991–2020"
                            % (MONTHS[int(init[-2:]) - 1], int(init[:4]), len(times),
                               mat.shape[0], resnote, nlead,
                               last.day, MONTHS[last.month - 1], last.year),
                   footer="Data: %s seasonal forecast (CDS) · ERA5 climatology "
                          "1991–2020" % name,
                   title="%s · 10 hPa · %s Zonal-Mean Zonal Wind (m/s)"
                         % (name, label))
        json.dump(month_table(times, np.nanmean(mat, axis=0), era, same_days=True),
                  open(os.path.join(OUT, "SPV_%s_%s_table.json" % (tag, key)), "w"),
                  indent=1)
        print("wrote %s  (daily, %d members, %d days)" % (fn, mat.shape[0], len(times)))


def seas5_daily_file(kind="daily"):
    """The newest SEAS5 daily file on disk.

    The file is named for its init (seas5_202611_daily.npz), so the
    December run is found by looking for the newest one rather than by
    having the name written into this script.
    """
    best = None
    for p in glob.glob(os.path.join(DATA, "seas5_*_%s.npz" % kind)):
        tag = os.path.basename(p)[len("seas5_"):-len("_%s.npz" % kind)]
        if best is None or tag > best[0]:
            best = (tag, p)
    return best


def build_ecmwf_daily(name, init):
    """The ECMWF run has daily 12Z members -> the full daily SPV chart."""
    from plot_spv import model_climate_curve
    got = seas5_daily_file("daily")
    if not got:
        print("  no SEAS5 daily series on disk")
        return
    if got[0] != init.replace("-", ""):
        print("  the SEAS5 daily series is the %s init, the model is on %s"
              % (got[0], init))
    d = np.load(got[1])
    steps = d["steps"]
    init_dt = datetime(int(init[:4]), int(init[-2:]), 1)
    times = [init_dt + timedelta(hours=int(s)) for s in steps]
    clim = np.load(seas5_daily_file("clim")[1]
                   if seas5_daily_file("clim") else got[1])
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
                   credit=credit_for("ecmwf-seas5"),
                   n_members=mem.shape[0],
                   subtitle="Run init 01 %s %d · %d daily 12Z steps (%d members)%s"
                            " · lead months 1–%d · ERA5 climatology 1991–2020"
                            % (MONTHS[int(init[-2:]) - 1], int(init[:4]), len(times),
                               mem.shape[0],
                               (" · %s grid" % grid_res(
                                   os.path.join(MDIR, "ecmwf-seas5",
                                                "u10_monthly.grib")))
                               if os.path.exists(os.path.join(MDIR, "ecmwf-seas5",
                                                             "u10_monthly.grib")) else "",
                               len({(t.year, t.month) for t in times})),
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
        if tag in POOLED_INTO:
            # pooled into the official canSIPS ensemble - its own wind chart
            # is not published
            continue
        name = meta.get("name", tag)
        init = meta.get("init") or init_info.recorded_init(tag)
        try:
            build_one(tag, name, init)
        except Exception as e:
            # one bad download must not stop the other centres from rendering
            print("!! %s failed: %s" % (tag, str(e)[:300]), flush=True)


# The two ECCC systems are shown on the site as the official canSIPS
# multi-model ensemble, so they are not rendered on their own.
POOLED_INTO = {"eccc-canesm5": "eccc-cansips", "eccc-gem5": "eccc-cansips"}

KIND_FILE = os.path.join(DATA, "spv_panel_kind.json")


def panel_kind(tag):
    """-> "daily" or "monthly" for the panel that is published for a centre."""
    p = os.path.join(DATA, "spv_panel_kind.json")
    if os.path.exists(p):
        try:
            return json.load(open(p)).get(tag)
        except Exception:
            return None
    return None


def set_panel_kind(tag, kind):
    p = os.path.join(DATA, "spv_panel_kind.json")
    d = json.load(open(p)) if os.path.exists(p) else {}
    d[tag] = kind
    json.dump(d, open(p, "w"), indent=1)


def build_one(tag, name, init):
        if tag == "ecmwf-seas5" and seas5_daily_file("daily"):
            build_ecmwf_daily(name, init)
            return

        # daily product from the C3S subdaily archive
        npz = os.path.join(MDIR, tag, "u10_daily.npz")
        if os.path.exists(npz):
            dates, m60, mnh, members, m = load_npz(npz)
            # A daily series with only a couple of members in it is worse
            # than the monthly one: the UKMO's sub-daily product serves two
            # of its sixty members, and a chart of two lines would read as
            # the whole ensemble.  The monthly series is used instead.
            nmem_d = len(members) if hasattr(members, "__len__") else 0
            if nmem_d < 10:
                print("   %s: the daily series has only %d members - using "
                      "the monthly wind instead" % (tag, nmem_d), flush=True)
                npz = None
        if npz and os.path.exists(npz):
            dates, m60, mnh, members, m = load_npz(npz)
            times = [datetime(d.year, d.month, d.day) for d in dates]
            # The init comes from the DATA, not from the fetch state: a
            # centre whose wind is still on the older init must not have a
            # panel that claims the newer one.  The first lead month of a
            # seasonal run is the init month.
            dinit = "%04d-%02d" % (times[0].year, times[0].month)
            render_daily(tag, name, dinit, times, m60, mnh, "daily")
            set_panel_kind(tag, "daily")
            return

        # monthly fallback - but only when there is nothing published yet.
        # A centre whose daily series has not been re-pulled keeps the daily
        # panel it already has; the monthly fallback would be a step back.
        pub = os.path.join(OUT, "SPV_%s_60N.png" % tag)
        if os.path.exists(pub) and panel_kind(tag) == "daily":
            # keep the published daily panel only if the daily series behind
            # it is usable - a couple of members is not an ensemble
            npz0 = os.path.join(MDIR, tag, "u10_daily.npz")
            nmem0 = 0
            if os.path.exists(npz0):
                try:
                    nmem0 = len(load_npz(npz0)[3])
                except Exception:
                    nmem0 = 0
            if nmem0 >= 10:
                print("keep the published daily panel for %s (no daily series "
                      "yet)" % tag, flush=True)
                return

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
        # A monthly_mean GRIB field is valid at the END of the averaging
        # period (step = 720 h from a 1 Oct init is valid 1 Nov and therefore
        # describes OCTOBER).  The lead month is the month of (valid - 1 day),
        # which is the same rule the snowfall panels use - without it every
        # non-ECMWF model is labelled one month late.
        rep = [d - timedelta(days=1) for d in dates]
        times = [datetime(r.year, r.month, 1) for r in rep]
        # the init comes from the data - the first lead month is the init
        # month, so a centre still on the October init cannot have a panel
        # that claims November
        init = "%04d-%02d" % (rep[0].year, rep[0].month)

        set_panel_kind(tag, "monthly")
        for dom, idx, key in (("60", 0, "60N"), ("NH", 1, "NH")):
            arr = np.full((nmem, len(dates)), np.nan)
            for j, d in enumerate(dates):
                vals = [r[idx] for r in by_date[d]]
                arr[:len(vals), j] = vals
            ens = np.nanmean(arr, axis=0)

            era = load_era5(dom, int(init[:4]))
            # the ERA5 window must cover the WHOLE of the first and the last
            # lead month, otherwise the monthly mean is taken over a partial
            # month
            t0 = datetime(rep[0].year, rep[0].month, 1)
            t1 = datetime(rep[-1].year, rep[-1].month,
                          calendar.monthrange(rep[-1].year, rep[-1].month)[1])
            keep = [i for i, t in enumerate(era["t"]) if t0 <= t <= t1]
            era_cut = {k: [era[k][i] for i in keep]
                       for k in ("t", "mean", "p10", "p30", "p70", "p90",
                                 "rmin", "rmax")}

            label = "60°N" if dom == "60" else "Northern Hemisphere"
            fn = os.path.join(OUT, "SPV_%s_%s.png" % (tag, key))
            res = grid_res(ug)
            resnote = (" · %s grid" % res) if res else ""
            render_spv(arr, times, name, fn, domain=dom, era5=era_cut,
                       model_clim=None, n_members=nmem, credit=credit_for(tag),
                       subtitle="Run init 01 %s %d · %d members · monthly means at "
                                "10 hPa%s · ERA5 climatology 1991–2020"
                                % (MONTHS[int(init[-2:]) - 1], int(init[:4]), nmem,
                                   resnote),
                       footer="Data: %s seasonal forecast (CDS) · ERA5 climatology "
                              "1991–2020" % name,
                       title="%s · 10 hPa · %s Zonal-Mean Zonal Wind (m/s)"
                             % (name, label))
            json.dump(month_table(times, ens, era_cut),
                      open(os.path.join(OUT, "SPV_%s_%s_table.json" % (tag, key)),
                           "w"), indent=1)
            print("wrote %s  (%d members, %d lead months)" % (fn, nmem, len(dates)))


def prune_stale_panels(state):
    """Drop panels that no longer have any data behind them.

    Two kinds of orphan:

    * a panel for a domain that is no longer published - the Northern
      Hemisphere 0-90 option was removed;
    * a panel whose source data has gone - the CMCC and DWD daily wind
      files were removed in the disk clean-up, which left their charts on
      the site with nothing behind them.  A chart that cannot be rebuilt
      and whose init label cannot be checked is worse than no chart, so it
      goes.  The daily wind is queued, and the charts come back with it.
    """
    def has_data(tag):
        return (os.path.exists(os.path.join(MDIR, tag, "u10_daily.npz")) or
                os.path.exists(os.path.join(MDIR, tag, "u10_monthly.grib")) or
                (tag == "ecmwf-seas5" and seas5_daily_file("daily")))

    n = 0
    for d in (OUT, os.path.join(HERE, "docs", "assets", "spv")):
        if not os.path.isdir(d):
            continue
        for dead in sorted(os.listdir(d)):
            if not dead.startswith("SPV_") or not dead.endswith(".png"):
                continue
            tag = dead[4:].rsplit("_", 1)[0]
            if "_NH." in dead or (tag not in state or not has_data(tag)):
                os.remove(os.path.join(d, dead))
                print("   removed the orphan %s" % dead)
                n += 1
    if not n:
        print("   no stale panels")


if __name__ == "__main__":
    main()
    _fp = os.path.join(DATA, "models_fetched.json")
    prune_stale_panels(json.load(open(_fp)) if os.path.exists(_fp) else {})
