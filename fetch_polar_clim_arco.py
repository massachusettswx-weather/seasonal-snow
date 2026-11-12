"""The native-grid polar-cap climatology, built from ARCO's live store.

The first climatology was built from ARCO's *reduced* 1.5 degree store.
That store is ARCO's own conservative remap of the ERA5 pressure-level
product, and the remap moves the polar-cap mean by 0.2-0.8% - by a
different amount on different days, because it depends on how the field is
shaped.  At 10 hPa the polar-cap mean is about 293,000 m2/s2, so 0.7% is
2,000 m2/s2, while the day-to-day spread of the polar cap in October is
only about 800.  A native-grid reanalysis drawn against that climatology
came out two to three sigma too cold on every single day.

So the climatology is rebuilt from the **native** 0.25 degree store - the
same product the recent reanalysis and the seasonal models are on.

**The cost.**  The native store's chunk is one hour: all 37 levels on the
full 0.25 degree grid, about 81 MB, and it covers the whole globe.  A
full 30-year daily climatology would be 10,957 chunks and 890 GB, which is
a lot of traffic for a statistic that does not need it.  Two sample days a
month - the 8th and the 22nd - over the 30 years is 720 chunks, about
58 GB, and the climate between the samples is a straight line, which is
far finer than the day-to-day spread it is used against.

The result has the same shape as the old climatology file (a day of the
year, a level, a mean and a sigma), so everything downstream is unchanged.

    python3 fetch_polar_clim_arco.py [--workers 6]
"""
import datetime as dt
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import zonal_mean   # noqa: E402

STORE = ("https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
         "full_37-1h-0p25deg-chunk-1.zarr-v3")

LEVELS = [10, 30, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]
LEV37 = [1, 2, 3, 5, 7, 10, 20, 30, 50, 70, 100, 125, 150, 175, 200, 225,
         250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 775, 800,
         825, 850, 875, 900, 925, 950, 975, 1000]

EPOCH = dt.datetime(1940, 1, 1)
YEARS = list(range(1991, 2021))
SAMPLE_DAYS = (8, 22)          # the two sample days of every month

OUT = os.path.join(DATA, "polar_cap_clim_native.npz")
CACHE = os.path.join(DATA, "polar_cap_clim_native_cache.json")

_blosc = None
_lat = None


def blosc():
    global _blosc
    if _blosc is None:
        import numcodecs
        _blosc = numcodecs.Blosc()
    return _blosc


def _get(url, tries=5):
    import requests
    for k in range(tries):
        try:
            r = requests.get(url, timeout=(20, 300))
            if r.status_code == 200 and len(r.content) > 0:
                return r.content
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(1.2 * (k + 1))
    return None


def latitude():
    global _lat
    if _lat is None:
        raw = _get(STORE + "/latitude/0")
        if raw is None:
            raise SystemExit("the ARCO latitudes could not be read")
        _lat = np.frombuffer(blosc().decode(raw), dtype="<f4").astype(float)
    return _lat


def cap_profile(day, lat):
    """The polar-cap mean of every level, for 12Z of that day.

    -> (nlevels,) or None when the store has no data for the day.
    """
    noon = dt.datetime(day.year, day.month, day.day, 12)
    idx = int((noon - EPOCH).total_seconds() // 3600)
    raw = _get("%s/geopotential/%d.0.0.0" % (STORE, idx))
    if raw is None:
        return None
    a = np.frombuffer(blosc().decode(raw), dtype="<f4").reshape(1, 37, 721, 1440)
    out = np.full(len(LEVELS), np.nan)
    for i, lev in enumerate(LEVELS):
        out[i] = zonal_mean(np.asarray(a[0, LEV37.index(lev)], float), lat)
    return out


def load_cache():
    if os.path.exists(CACHE):
        try:
            import json
            return json.load(open(CACHE))
        except Exception:
            return {}
    return {}


def save_cache(cache):
    import json
    json.dump(cache, open(CACHE, "w"))


def build():
    """The sample -> the daily mean and sigma over the 30 years."""
    cache = load_cache()
    lat = latitude()

    todo = []
    for y in YEARS:
        for m in range(1, 13):
            for dd in SAMPLE_DAYS:
                key = "%04d-%02d-%02d" % (y, m, dd)
                if key not in cache:
                    todo.append(key)
    print("   %d sample days to fetch (%d already cached)"
          % (len(todo), len(cache)), flush=True)

    def one(key):
        y, m, d = (int(x) for x in key.split("-"))
        p = cap_profile(dt.date(y, m, d), lat)
        return key, (None if p is None else [float(x) for x in p])

    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for key, p in ex.map(one, todo):
            if p is None:
                print("   %s is not in the store" % key, flush=True)
                continue
            cache[key] = p
            done += 1
            if done % 40 == 0:
                save_cache(cache)
                el = time.time() - t0
                print("   %d/%d  %.1f min  eta %.0f min"
                      % (done, len(todo), el / 60,
                         (len(todo) - done) / max(done / max(el, 1e-9), 1e-9) / 60),
                      flush=True)
    save_cache(cache)

    # the samples for each calendar month, over the 30 years
    import calendar
    per_month = {}
    for m in range(1, 13):
        rows = []
        for y in YEARS:
            for dd in SAMPLE_DAYS:
                k = "%04d-%02d-%02d" % (y, m, dd)
                if k in cache:
                    rows.append(cache[k])
        if len(rows) < 10:
            print("   month %02d has only %d samples - skipped" % (m, len(rows)))
            continue
        a = np.asarray(rows, float)
        a = a[np.isfinite(a).all(axis=1)]
        # the 8th and the 22nd separately, so the climate can be drawn
        # through the month instead of stepping at the 15th
        first = np.asarray([cache["%04d-%02d-%02d" % (y, m, SAMPLE_DAYS[0])]
                            for y in YEARS
                            if "%04d-%02d-%02d" % (y, m, SAMPLE_DAYS[0]) in cache],
                           float)
        second = np.asarray([cache["%04d-%02d-%02d" % (y, m, SAMPLE_DAYS[1])]
                             for y in YEARS
                             if "%04d-%02d-%02d" % (y, m, SAMPLE_DAYS[1]) in cache],
                            float)
        first = first[np.isfinite(first).all(axis=1)]
        second = second[np.isfinite(second).all(axis=1)]
        per_month[m] = {"a": first.mean(axis=0), "b": second.mean(axis=0),
                        "s": a.std(axis=0, ddof=1), "n": int(a.shape[0])}
        print("   month %02d: %3d samples   the 10 hPa mean %10.1f  sigma %8.1f"
              % (m, a.shape[0], per_month[m]["a"][0], per_month[m]["s"][0]),
              flush=True)

    # the climate on the calendar: a straight line between the sample days
    import calendar
    # the anchor points: the 8th and the 22nd of every month
    anchors = []
    for m in range(1, 13):
        if m not in per_month:
            continue
        anchors.append((dt.date(2001, m, SAMPLE_DAYS[0]), per_month[m]["a"]))
        anchors.append((dt.date(2001, m, SAMPLE_DAYS[1]), per_month[m]["b"]))
    anchors.sort(key=lambda t: t[0])
    if len(anchors) < 4:
        raise SystemExit("not enough months of samples")
    # wrap the list so the end of the year joins the beginning
    first = anchors[0]
    last = anchors[-1]
    span = (first[0] - last[0]).days + (365 - last[0].timetuple().tm_yday)
    wrapped = anchors + [(first[0] + dt.timedelta(days=365), first[1])]
    # the day of the year, counted from 1 January, so the wrap works
    def yday(x):
        return (x - dt.date(2001, 1, 1)).days

    days, mean, sigma, counts = [], [], [], []
    for m in range(1, 13):
        if m not in per_month:
            continue
        nd = calendar.monthrange(2001, m)[1]
        for d in range(1, nd + 1):
            day = dt.date(2001, m, d)
            k = yday(day)
            # the two anchors that surround it
            lo = wrapped[0]
            hi = wrapped[-1]
            for a, b in zip(wrapped, wrapped[1:]):
                if yday(a[0]) <= k <= yday(b[0]):
                    lo, hi = a, b
                    break
            span = float(yday(hi[0]) - yday(lo[0]))
            g = 0.0 if span <= 0 else (k - yday(lo[0])) / span
            days.append("%02d-%02d" % (m, d))
            mean.append(lo[1] + (hi[1] - lo[1]) * g)
            sigma.append(per_month[m]["s"])
            counts.append(per_month[m]["n"])
    res = {"levels": np.array(LEVELS),
           "days": np.array(days),
           "mean": np.array(mean, float),
           "sigma": np.array(sigma, float),
           "count": np.array(counts, int)}
    np.savez_compressed(OUT, **res)
    print("   -> %s  (%d days)" % (OUT, len(days)))
    return OUT


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    build()
