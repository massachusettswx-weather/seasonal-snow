"""ERA5 polar-cap (60-90N) geopotential height, 1991-2020, from ARCO.

Why ARCO and not the CDS
------------------------
The seasonal polar-cap section needs the ERA5 climatology of the polar cap
mean geopotential height: the mean and the sigma of every calendar day, at
twelve pressure levels, over 1991-2020.  The CDS can serve that, but the CDS
queue on this account is saturated (an admission cap of two, and jobs that sit
"accepted" for hours), and the ERA5 hourly pressure-level request is refused
outright above one year at twelve levels.

ARCO-ERA5 is a public GCS bucket with no queue and no cost limit, and it can
be read with as many parallel workers as the network will take.  The store
used here is

    1959-2022-1h-240x121_equiangular_with_poles_conservative.zarr

which carries the `geopotential` on all 37 pressure levels on a 1.5 deg grid
that includes the poles.  The chunk is [8 hours, 37 levels, 240 lon, 121 lat]
- about 21 MB compressed - so one chunk carries the 12Z value of a whole day
together with its neighbours.  Only the 12Z member of each chunk is kept.

What is stored
--------------
The cache keeps the ZONAL MEAN AT EVERY CAP LATITUDE (21 of them), for each
of the twelve levels, not the finished cap mean.  The cap mean is then a
weighted average over those, and it can be recomputed for any weighting or
band edge without downloading the 235 GB again.

That is not gold-plating: it caught a real bug.  ARCO stores 60N as
59.999999999999986, so an exact `lat >= 60.0` test silently dropped the
bottom row of the cap and shifted the 500 hPa value by 104 m2/s2 (0.2%),
which is a tenth of the sigma the anomaly is normalised by.  With the
per-latitude cache the band edge is a tolerance in one place, and the
weights are recomputable.

The job is resumable: one row per finished day.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import CAP_N, CAP_S, LEVELS  # noqa: E402

STORE = ("https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
         "1959-2022-1h-240x121_equiangular_with_poles_conservative.zarr")

# ARCO's 37 levels, in the order the store holds them
LEV37 = [1, 2, 3, 5, 7, 10, 20, 30, 50, 70, 100, 125, 150, 175, 200, 225,
         250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 775, 800,
         825, 850, 875, 900, 925, 950, 975, 1000]

OUT = os.path.join(DATA, "era5_polarcap_profiles.npz")
LOG = os.path.join(DATA, "polar_era5_arco.log")

EPOCH = dt.datetime(1959, 1, 1)
_blosc = None
_lat = None


def blosc():
    global _blosc
    if _blosc is None:
        import numcodecs
        _blosc = numcodecs.Blosc()
    return _blosc


def latitude():
    """The store's latitudes (121, ascending from -90N)."""
    global _lat
    if _lat is None:
        r = requests.get(STORE + "/latitude/0", timeout=(20, 180))
        r.raise_for_status()
        _lat = np.frombuffer(blosc().decode(r.content), dtype="<f8").astype(float)
    return _lat


def cap_rows(lat):
    """The indices of the polar-cap rows.

    The band edges are compared with a tolerance: ARCO's 60N row is
    59.999999999999986, and an exact test drops it.
    """
    return np.where((lat >= CAP_S - 1e-6) & (lat <= CAP_N + 1e-6))[0]


def chunk_bytes(idx):
    """One ARCO chunk -> (8, 37, 240, 121) float32, or None."""
    url = f"{STORE}/geopotential/{idx}.0.0.0"
    for k in range(4):
        try:
            r = requests.get(url, timeout=(30, 300))
            if r.status_code != 200:
                return None
            raw = blosc().decode(r.content)
            return np.frombuffer(raw, dtype="<f4").reshape(8, 37, 240, 121)
        except Exception:
            time.sleep(2.0 * (k + 1))
    return None


def day_to_chunk(d):
    """The ARCO chunk that holds 12Z of the day `d`."""
    day = dt.datetime(d.year, d.month, d.day)
    hour = int((day - EPOCH).total_seconds() // 3600) + 12
    return hour // 8, hour % 8


def cap_profiles(chunk, slot, lat, rows):
    """The zonal mean at every cap latitude, for the twelve levels.

    -> (nlevels, nrows)
    """
    out = np.full((len(LEVELS), len(rows)), np.nan)
    sub = chunk[slot]                       # (37, 240 lon, 121 lat)
    for i, lev in enumerate(LEVELS):
        j = LEV37.index(lev)
        f = np.asarray(sub[j], float).T     # (nlat, nlon)
        out[i] = f[rows, :].mean(axis=1)    # the zonal mean at each cap latitude
    return out


def load_cache():
    """-> {date: (nlevels, nrows) array}"""
    if os.path.exists(OUT):
        try:
            d = np.load(OUT, allow_pickle=True)
            times = [str(t) for t in d["times"]]
            vals = d["values"]
            return {t: vals[i] for i, t in enumerate(times)}
        except Exception:
            return {}
    return {}


def save_cache(cache):
    if not cache:
        return
    times = sorted(cache)
    np.savez_compressed(OUT, times=np.array(times),
                        values=np.array([cache[t] for t in times], float),
                        lat=np.array(cap_rows(latitude()), int))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="1991-01-01")
    ap.add_argument("--end", default="2020-12-31")
    ap.add_argument("--workers", type=int, default=24)
    a = ap.parse_args()

    d0 = dt.date.fromisoformat(a.start)
    d1 = dt.date.fromisoformat(a.end)
    lat = latitude()
    rows = cap_rows(lat)

    cache = load_cache()
    days = []
    d = d0
    while d <= d1:
        if d.isoformat() not in cache:
            days.append(d)
        d += dt.timedelta(days=1)

    print("ARCO ERA5 polar cap: %d days to fetch (%d already cached), "
          "%d cap latitudes" % (len(days), len(cache), len(rows)), flush=True)
    if not days:
        save_cache(cache)
        print("the cache is complete", flush=True)
        return

    t0 = time.time()

    def work(d):
        ci, slot = day_to_chunk(d)
        c = chunk_bytes(ci)
        if c is None:
            return d, None
        p = cap_profiles(c, slot, lat, rows)
        del c
        return d, p

    done = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for d, p in ex.map(work, days):
            if p is None:
                print("   %s unavailable - skipped" % d, flush=True)
                continue
            cache[d.isoformat()] = p
            done += 1
            if done % 100 == 0:
                save_cache(cache)
                el = time.time() - t0
                rate = done / max(el, 1e-9)
                left = (len(days) - done) / max(rate, 1e-9)
                print("   %d/%d  %.1f min  %.0f days/h  eta %.0f min"
                      % (done, len(days), el / 60, rate * 3600, left / 60),
                      flush=True)
    save_cache(cache)
    print("done -> %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
