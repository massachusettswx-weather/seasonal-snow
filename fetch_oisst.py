"""The analysis segment of the ENSO plumes from NOAA OI SST v2.1.

OI SST v2.1 is NOAA's operational sea surface temperature analysis - the
same source NOAA builds the Nino indices from.  Its near-real-time
(preliminary) files are produced every day with a one-day latency, so the
observed line can run right up to today instead of stopping at the end of
last month.  That is the whole point of this file: ERSST v6 is monthly, so
it left a hole of about a month and a half between the last observation and
the forecast.

For every month it gives
  * the area-weighted mean SST of the four ENSO basins,
  * the tropical-mean (20S-20N) SST,
both as absolute values and as anomalies against the 1991-2020 climatology
of the same calendar month - computed from OI SST itself, so the observed
line is a true OI SST anomaly and not a difference between two different
reanalyses.

The current month is incomplete, so the mean is over the days that have
been published and the number of days is recorded, so the chart can say
how much of the month it is standing on.

    python3 fetch_oisst.py [--from YYYY-MM] [--to YYYY-MM]
"""
import os
import sys
import json
import time
import datetime
import argparse
import urllib.error
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BIAS_FROM = 2016
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(DATA, "oisst_daily.json")
OUT = os.path.join(DATA, "oisst_enso.npz")
BASE = ("https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-"
        "interpolation/v2.1/access/avhrr")
UA = {"User-Agent": "seas5 seasonal-graphics pipeline"}
sys.path.insert(0, HERE)
from enso_common import BASINS, BASIN_NAMES  # noqa: E402

# the tropical band that carries every basin, so one slice of the file is
# enough: Nino 3.4, Nino 3, Nino 4 and Nino 1+2 all sit inside 20S-20N
BAND = (-20.0, 20.0)


def log(msg):
    print("   %s" % msg, flush=True)


def fetch_day(y, m, d):
    """-> (lat, lon, sst, ice) for one day, or None if it is not there."""
    for suff in ("", "_preliminary"):
        name = "oisst-avhrr-v02r01.%04d%02d%02d%s.nc" % (y, m, d, suff)
        url = "%s/%04d%02d/%s" % (BASE, y, m, name)
        for attempt in range(3):
            try:
                raw = urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=90).read()
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raw = None
                    break
                if attempt == 2:
                    return None
                time.sleep(3 * (attempt + 1))
            except Exception:
                if attempt == 2:
                    return None
                time.sleep(3 * (attempt + 1))
        if raw is None:
            continue
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as f:
                f.write(raw)
                tmp = f.name
            import h5netcdf
            with h5netcdf.File(tmp, "r") as fh:
                sst = np.asarray(fh["sst"][0, 0], float)
                lat = np.asarray(fh["lat"][:], float)
                lon = np.asarray(fh["lon"][:], float)
                ice = None
                if "ice" in fh.variables:
                    ice = np.asarray(fh["ice"][0, 0], float)
            os.unlink(tmp)
            # the netCDF attributes do the decoding: scale_factor 0.01 and
            # a _FillValue of -999, so the land is -9.99 degC
            return lat, lon, sst, ice
        except Exception:
            continue
    return None


def scale(arr, attrs):
    sc = attrs.get("scale_factor", 1.0)
    off = attrs.get("add_offset", 0.0)
    sc = float(np.asarray(sc).ravel()[0]) if np.ndim(sc) else float(sc)
    off = float(np.asarray(off).ravel()[0]) if np.ndim(off) else float(off)
    return np.asarray(arr, float) * sc + off


def basin_means(lat, lon, sst, ice):
    """-> (the four basin means, the tropical mean) for one day."""
    ok = sst > -1.0
    if ice is not None:
        ok = ok & (ice <= 0.0)
    out = []
    for name, la0, la1, lo0, lo1 in BASINS:
        m = ((lat[:, None] >= min(la0, la1)) & (lat[:, None] <= max(la0, la1)) &
             (lon[None, :] >= min(lo0, lo1)) & (lon[None, :] <= max(lo0, lo1)) &
             ok)
        w = np.broadcast_to(np.cos(np.deg2rad(lat[:, None])), sst.shape)
        ww = w * m
        tot = ww.sum()
        out.append(float((sst * ww).sum() / tot) if tot > 0 else np.nan)
    band = (lat[:, None] >= BAND[0]) & (lat[:, None] <= BAND[1]) & ok
    w = np.broadcast_to(np.cos(np.deg2rad(lat[:, None])), sst.shape) * band
    tot = w.sum()
    tm = float((sst * w).sum() / tot) if tot > 0 else np.nan
    return out, tm


def load_cache():
    if os.path.exists(CACHE):
        try:
            return json.load(open(CACHE))
        except Exception:
            return {}
    return {}


def save_cache(c):
    tmp = CACHE + ".tmp"
    json.dump(c, open(tmp, "w"))
    os.replace(tmp, CACHE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="y0", default="1991-01")
    ap.add_argument("--to", dest="y1", default="")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--bias-from", type=int, default=2016,
                    help="the first year of the ERSST overlap used for "
                         "the bias correction (the OI SST v2.1 in-situ "
                         "correction changed in 2016)")
    args = ap.parse_args()

    today = datetime.date.today()
    y1 = args.y1 or "%04d-%02d" % (today.year, today.month)
    y0 = args.y0

    def months(a, b):
        out = []
        ya, ma = int(a[:4]), int(a[5:7])
        yb, mb = int(b[:4]), int(b[5:7])
        while (ya, ma) <= (yb, mb):
            out.append((ya, ma))
            ma += 1
            if ma > 12:
                ma = 1
                ya += 1
        return out

    want = months(y0, y1)
    cache = {} if args.no_cache else load_cache()
    log("the OI SST days wanted: %s .. %s" % (want[0], want[-1]))

    # every day from the first wanted month to today
    d = datetime.date(want[0][0], want[0][1], 1)
    end = datetime.date(today.year, today.month, today.day)
    ndays = (end - d).days + 1
    log("the days to fetch: %d (the cache holds %d)" % (ndays, len(cache)))

    got = 0
    miss = 0
    t0 = time.time()
    while d <= end:
        key = d.strftime("%Y-%m-%d")
        if key not in cache:
            r = fetch_day(d.year, d.month, d.day)
            if r is None:
                cache[key] = None
                miss += 1
            else:
                lat, lon, sst, ice = r
                # the scaling has to be applied here: fetch_day returns the
                # decoded array only if the attributes were found, so redo it
                # from the raw values when they look unscaled
                if float(np.nanmax(sst)) > 100.0:
                    sst = sst * 0.01
                bm, tm = basin_means(lat, lon, sst, ice)
                cache[key] = {"b": [round(x, 5) for x in bm], "t": round(tm, 5)}
            got += 1
            time.sleep(0.12)     # be polite to the archive
            if got % 50 == 0:
                save_cache(cache)
                el = time.time() - t0
                log("  %d days fetched (%.1f s, %.1f min left)"
                    % (got, el, (ndays - got) * el / max(got, 1) / 60.0))
        d += datetime.timedelta(days=1)
    save_cache(cache)

    # ---------------- build the monthly series ----------------
    ms = []
    for (y, m) in want:
        days = []
        for (dd, rec) in cache.items():
            if rec is None:
                continue
            if dd.startswith("%04d-%02d" % (y, m)):
                days.append((dd, rec))
        if not days:
            continue
        days.sort()
        n = len(days)
        b = np.array([r["b"] for _, r in days], float)
        t = np.array([r["t"] for _, r in days], float)
        ms.append(("%04d-%02d" % (y, m), b.mean(axis=0), t.mean(), n,
                    days[0][0], days[-1][0]))
    log("the months built: %d" % len(ms))

    mnames = [x[0] for x in ms]
    bas = np.array([x[1] for x in ms], float)
    tm = np.array([x[2] for x in ms], float)
    ndays = [x[3] for x in ms]

    # the 1991-2020 climatology, from OI SST itself
    sel = [i for i, mm in enumerate(mnames) if 1991 <= int(mm[:4]) <= 2020]
    clim_b = np.zeros((12, len(BASIN_NAMES)))
    clim_t = np.zeros(12)
    for mm in range(1, 13):
        idx = [i for i in sel if int(mnames[i][5:7]) == mm]
        if idx:
            clim_b[mm - 1] = np.mean(bas[idx], axis=0)
            clim_t[mm - 1] = np.mean(tm[idx])
    cal = np.array([int(mm[5:7]) - 1 for mm in mnames])
    anom_b = bas - clim_b[cal]
    anom_t = tm - clim_t[cal]

    # the relative index: the basin anomaly minus the tropical mean, rescaled
    # so its spread matches the absolute index (CPC's renormalisation)
    rel = anom_b[:, 0] - anom_t
    k = float(np.std(anom_b[:, 0]) / np.std(rel)) if np.std(rel) > 0 else 1.242

    # ------------------------------------------------------------------
    # The bias correction onto ERSST.
    #
    # OI SST and ERSST are two different analyses of the same ocean and
    # they do not agree: over the last two months OI SST runs 0.4-0.9 degC
    # warmer than ERSST in the Nino 3 and Nino 3.4 boxes and about 0.1 degC
    # cooler in Nino 4.  The chart's observed line has always been ERSST,
    # and ERSST is what NOAA builds the published Nino indices from, so the
    # OI SST is corrected onto it before it is used: for every calendar
    # month the mean difference over the overlap is removed.  The result
    # keeps the ERSST scale - so the plume values do not move at all - and
    # the observed line can run right up to today.
    # ------------------------------------------------------------------
    bias_b = np.zeros((12, len(BASIN_NAMES)))
    bias_t = np.zeros(12)
    bas_bc = bas.copy()
    tm_bc = tm.copy()
    have_ersst = False
    ep = os.path.join(DATA, "ersst_enso.npz")
    if os.path.exists(ep):
        e = np.load(ep, allow_pickle=True)
        em = [str(x) for x in e["months"]]
        idx = {m: i for i, m in enumerate(em)}
        pair_b = []
        pair_t = []
        for i, m in enumerate(mnames):
            if m not in idx:
                continue
            if int(m[:4]) < BIAS_FROM:
                continue
            pair_b.append(e["basin"][idx[m]] - bas[i])
            pair_t.append(float(e["tm"][idx[m]] - tm[i]))
        if pair_b:
            have_ersst = True
            pb = np.array(pair_b, float)
            for mm in range(1, 13):
                rows = [j for j, m in enumerate(mnames)
                        if int(m[5:7]) == mm and int(m[:4]) >= BIAS_FROM
                        and m in idx]
                if not rows:
                    continue
                dif = np.array([e["basin"][idx[mnames[j]]] - bas[j]
                                for j in rows], float)
                bias_b[mm - 1] = dif.mean(axis=0)
                dt = np.array([float(e["tm"][idx[mnames[j]]] - tm[j])
                                for j in rows], float)
                bias_t[mm - 1] = dt.mean()
            for i, m in enumerate(mnames):
                cal2 = int(m[5:7]) - 1
                bas_bc[i] = bas[i] + bias_b[cal2]
                tm_bc[i] = tm[i] + bias_t[cal2]
            log("the bias correction onto ERSST, from %d:" % BIAS_FROM)
            for bi, b in enumerate(BASIN_NAMES):
                log("   %-9s %+0.3f degC (the monthly spread %.3f)"
                    % (b, bias_b[:, bi].mean(), bias_b[:, bi].std()))
            log("   the tropical mean %+0.3f degC" % bias_t.mean())

    anom_bc = bas_bc - clim_b[cal]
    anom_t_bc = tm_bc - clim_t[cal]
    rel_bc = anom_bc[:, 0] - anom_t_bc
    k_bc = (float(np.std(anom_bc[:, 0]) / np.std(rel_bc))
            if np.std(rel_bc) > 0 else k)

    np.savez_compressed(
        OUT, months=np.array(mnames), basin=bas, tm=tm,
        basin_anom=anom_b, tm_anom=anom_t,
        basin_clim=clim_b, tm_clim=clim_t,
        basins=np.array(BASIN_NAMES), k=k,
        basin_bc=bas_bc, tm_bc=tm_bc,
        basin_anom_bc=anom_bc, tm_anom_bc=anom_t_bc,
        bias_basin=bias_b, bias_tm=bias_t, k_bc=k_bc,
        bias_from=np.array([BIAS_FROM]),
        bias_applied=np.array([1 if have_ersst else 0]),
        ndays=np.array(ndays),
        first_day=np.array([x[4] for x in ms]),
        last_day=np.array([x[5] for x in ms]),
        source=np.array(["NOAA OI SST v2.1 (AVHRR)"]))
    log("saved %s" % os.path.relpath(OUT, HERE))
    log("the last month: %s, %d day(s) (%s .. %s)"
        % (mnames[-1], ndays[-1], ms[-1][4], ms[-1][5]))

    # ---------------- validation ----------------
    # 1) how closely does the bias-corrected OI SST sit on the ERSST?
    if have_ersst:
        e = np.load(ep, allow_pickle=True)
        em = [str(x) for x in e["months"]]
        idx = {m: i for i, m in enumerate(em)}
        rows = [i for i, m in enumerate(mnames) if m in idx]
        d = np.array([bas_bc[i, 0] - e["basin"][idx[mnames[i]], 0]
                      for i in rows], float)
        log("the bias-corrected OI SST against the ERSST, Nino 3.4:")
        log("   the mean %+0.3f degC, the RMS %.3f degC over %d months"
            % (d.mean(), np.sqrt((d ** 2).mean()), len(d)))
    # 2) against CPC's own published RONI
    cp = os.path.join(DATA, "oni", "indices.json")
    if os.path.exists(cp):
        cpc = json.load(open(cp)).get("roni_monthly", {})
        rel = anom_bc[:, 0] - anom_t_bc
        ours = []
        for i, m in enumerate(mnames):
            if m in cpc:
                ours.append(float(rel[i] * k_bc) - float(cpc[m]))
        if ours:
            a = np.array(ours)
            log("against CPC's published monthly RONI: the mean %+0.3f, "
                "the mean |difference| %.3f, the worst %.3f (%d months)"
                % (a.mean(), np.abs(a).mean(), np.abs(a).max(), len(a)))

    # how does the OI SST climatology compare with ERA5's?
    p = os.path.join(DATA, "era5_enso_clim.npz")
    if os.path.exists(p):
        c = np.load(p, allow_pickle=True)
        era = np.asarray(c["sst"], float) - 273.15
        for i, b in enumerate(BASIN_NAMES):
            d2 = clim_b[:, i] - era[:, i]
            log("  the OI SST minus ERA5, %-9s %+0.3f degC" % (b, d2.mean()))


if __name__ == "__main__":
    main()
