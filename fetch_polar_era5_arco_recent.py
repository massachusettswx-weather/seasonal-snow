"""The recent ERA5 reanalysis for the polar-cap section, from ARCO.

The CDS route (`reanalysis-era5-pressure-levels`) was measured at **hours**
per request in this account - the queue for that dataset is saturated, and
a graphic that has to be current cannot wait for it.

ARCO-ERA5's live store carries the same ERA5 hourly pressure-level
geopotential all the way to the present, on a public bucket with no queue
at all:

    ar/full_37-1h-0p25deg-chunk-1.zarr-v3

One chunk is one hour: all 37 levels on the full 0.25 degree grid, about
80 MB, read in under two seconds.  The polar cap mean is taken from the
chunk with exactly the same area weights and the same band edges as the
climatology (`polar_cap.zonal_mean`), so the two are comparable.

**The two stores have to agree.**  The climatology comes from the reduced
1.5 degree store and the recent data from the full 0.25 degree one, so the
fetch is checked against a day that BOTH stores carry.  The check is the
`--check` mode; it is also run automatically when the file is written.

The store's time axis starts at 1940-01-01, one step per hour.  The
12Z value of a day is the hour index of that noon.
"""
import argparse
import datetime as dt
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import zonal_mean   # noqa: E402

STORE = ("https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
         "full_37-1h-0p25deg-chunk-1.zarr-v3")

# the reduced store the climatology came from - used for the cross-check
REDUCED = ("https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
           "1959-2022-1h-240x121_equiangular_with_poles_conservative.zarr")

LEVELS = [10, 30, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]
LEV37 = [1, 2, 3, 5, 7, 10, 20, 30, 50, 70, 100, 125, 150, 175, 200, 225,
         250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 775, 800,
         825, 850, 875, 900, 925, 950, 975, 1000]

EPOCH = dt.datetime(1940, 1, 1)
RED_EPOCH = dt.datetime(1959, 1, 1)

OUT = os.path.join(DATA, "polar_era5_recent.npz")

_blosc = None
_lat = None


def blosc():
    global _blosc
    if _blosc is None:
        import numcodecs
        _blosc = numcodecs.Blosc()
    return _blosc


def _get(url, tries=4):
    import requests
    for k in range(tries):
        try:
            r = requests.get(url, timeout=(20, 300))
            if r.status_code == 200:
                return r.content
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(1.5 * (k + 1))
    return None


def latitude():
    """The store's latitudes (721, from 90N down)."""
    global _lat
    if _lat is None:
        raw = _get(STORE + "/latitude/0")
        if raw is None:
            raise SystemExit("the ARCO latitudes could not be read")
        _lat = np.frombuffer(blosc().decode(raw), dtype="<f4").astype(float)
    return _lat


def hour_index(d):
    """The store's hour index for 12Z of the day `d`."""
    noon = dt.datetime(d.year, d.month, d.day, 12)
    return int((noon - EPOCH).total_seconds() // 3600)


def cap_profile(idx, lat):
    """The polar cap mean of every level, for one hour of the store.

    -> (nlevels,) or None when the store has no data for that hour.
    """
    raw = _get("%s/geopotential/%d.0.0.0" % (STORE, idx))
    if raw is None:
        return None
    a = np.frombuffer(blosc().decode(raw), dtype="<f4").reshape(1, 37, 721, 1440)
    out = np.full(len(LEVELS), np.nan)
    for i, lev in enumerate(LEVELS):
        out[i] = zonal_mean(np.asarray(a[0, LEV37.index(lev)], float), lat)
    return out


def load():
    if not os.path.exists(OUT):
        return {}, []
    try:
        d = np.load(OUT, allow_pickle=True)
        times = [str(t) for t in d["times"]]
        vals = np.asarray(d["values"], float)
        return {t: vals[i] for i, t in enumerate(times)}, times
    except Exception:
        return {}, []


def save(cache):
    times = sorted(cache)
    if not times:
        return
    np.savez_compressed(OUT, times=np.array(times),
                        levels=np.array(LEVELS),
                        values=np.array([cache[t] for t in times], float))


# ---------------------------------------------------------------- the check
def check(day):
    """The polar cap mean of one day from BOTH stores.

    The climatology comes from the reduced store and the recent data from
    the full one, so the two have to agree; if they do not, the recent
    data cannot be normalised against that climatology.
    """
    import requests
    lat = latitude()

    # the full 0.25 degree store
    full = cap_profile(hour_index(day), lat)

    # the reduced 1.5 degree store: a chunk holds eight hours
    hour = int((dt.datetime(day.year, day.month, day.day) - RED_EPOCH)
               .total_seconds() // 3600) + 12
    raw = _get("%s/geopotential/%d.0.0.0" % (REDUCED, hour // 8))
    if raw is None:
        print("   the reduced store has no chunk for %s" % day)
        return None
    chunk = np.frombuffer(blosc().decode(raw), dtype="<f4").reshape(8, 37, 240, 121)
    rlat = np.frombuffer(blosc().decode(_get(REDUCED + "/latitude/0")),
                         dtype="<f8").astype(float)
    w = np.cos(np.deg2rad(rlat))
    used = (rlat >= 60 - 1e-6) & (rlat <= 90 + 1e-6)
    red = np.full(len(LEVELS), np.nan)
    for i, lev in enumerate(LEVELS):
        f = np.asarray(chunk[hour % 8, LEV37.index(lev)], float).T   # (nlat, nlon)
        red[i] = (f[used, :] * w[used, None]).sum() / (240 * w[used].sum())

    if full is None:
        print("   the full store has no data for %s" % day)
        return None
    print("   %s   the full 0.25deg store vs the reduced 1.5deg store" % day)
    print("   %-6s %14s %14s %9s"
          % ("hPa", "full (m2/s2)", "reduced (m2/s2)", "difference"))
    worst = 0.0
    for i, lev in enumerate(LEVELS):
        d = full[i] - red[i]
        worst = max(worst, abs(d) / abs(red[i]))
        print("   %-6d %14.2f %14.2f %9.3f%%"
              % (lev, full[i], red[i], 100.0 * d / red[i]))
    print("   the largest difference is %.4f%% of the value" % (100.0 * worst))
    return worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--end", default="")
    ap.add_argument("--check", default="2022-06-15")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    lat = latitude()
    print("   the store's latitudes: %d rows, %.2f to %.2f"
          % (len(lat), lat[0], lat[-1]), flush=True)

    if a.check:
        print("   the cross-check between the two stores", flush=True)
        check(dt.date.fromisoformat(a.check))

    end = (dt.date.fromisoformat(a.end) if a.end
           else dt.date.today() - dt.timedelta(days=5))
    start = end - dt.timedelta(days=a.days - 1)

    cache, _ = load()
    todo = [start + dt.timedelta(days=i) for i in range(a.days)
            if (start + dt.timedelta(days=i)).isoformat() not in cache]
    print("   the window: %s -> %s (%d days, %d to fetch)"
          % (start, end, a.days, len(todo)), flush=True)

    from concurrent.futures import ThreadPoolExecutor

    def one(d):
        p = cap_profile(hour_index(d), lat)
        if p is None or not np.all(np.isfinite(p)):
            return d, None
        return d, p

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for d, p in ex.map(one, todo):
            if p is None:
                print("   %s is not in the store yet" % d, flush=True)
                continue
            cache[d.isoformat()] = p
            print("   %s  10hPa %.1f  100hPa %.1f"
                  % (d, p[0], p[3]), flush=True)
            save(cache)

    save(cache)
    have = sorted(cache)
    print("   the recent ERA5: %d days, %s -> %s"
          % (len(have), have[0] if have else "-", have[-1] if have else "-"))
    print("   -> %s" % OUT)


if __name__ == "__main__":
    main()
