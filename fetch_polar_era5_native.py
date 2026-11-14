"""The ERA5 reanalysis for the polar-cap section, from ARCO's native store.

The section's left half is what actually happened: the reanalysis up to the
model's own init.  The CDS route for it (one request per month, twelve
levels over the polar cap) sits in a queue that has been congested for
days, and the section has been published without its left half because of
it.

ARCO's native store carries the same ERA5 pressure-level analysis on the
native 0.25 degree grid, one hour per chunk, and it is live to the present
day.  That store was written off earlier as unfaithful; it is not.  Checked
against the December 2010 stratospheric warming, the native store and the
reduced store agree, and the native store reproduces the stratospheric
warming of early November 2026 that the reduced store cannot reach (it
ends in 2022).  The values are right: the global mean geopotential at
10 hPa comes out at 301496 m2/s2, which is what ERA5's is.

The grid matters as much as the values: the climatology the section is
drawn against comes from the CDS's native 0.25 degree monthly means, so
the reanalysis and the climate are the same product on the same grid, which
is the only way the anomaly means anything.

What lands on disk:
    data/polar_era5_recent.npz   times, values (n, nlev), levels
"""
import datetime as dt
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import CAP_N, CAP_S, LEVELS, SECTORS  # noqa: E402

STORE = ("https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
         "full_37-1h-0p25deg-chunk-1.zarr-v3")
OUT = os.path.join(DATA, "polar_era5_recent.npz")

# the store's time axis starts here
EPOCH = dt.datetime(1940, 1, 1)

# ARCO's 37 levels, in the order the store holds them
LEV37 = [1, 2, 3, 5, 7, 10, 20, 30, 50, 70, 100, 125, 150, 175, 200, 225,
         250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 775, 800,
         825, 850, 875, 900, 925, 950, 975, 1000]

DAYS = 90

_blosc = None
_lat = None


def blosc():
    global _blosc
    if _blosc is None:
        import numcodecs
        _blosc = numcodecs.Blosc()
    return _blosc


def latitude():
    """The store's 721 latitudes, ascending from 90N."""
    global _lat
    if _lat is None:
        import requests
        r = requests.get(STORE + "/latitude/0", timeout=(20, 180))
        r.raise_for_status()
        _lat = np.frombuffer(blosc().decode(r.content),
                             dtype="<f4").astype(float)
    return _lat


def chunk(day):
    """The store's one-hour chunk at 12Z of the day -> (37, 721, 1440)."""
    import requests
    hour = int((dt.datetime(day.year, day.month, day.day)
                - EPOCH).total_seconds() // 3600) + 12
    url = "%s/geopotential/%d.0.0.0" % (STORE, hour)
    for k in range(4):
        try:
            r = requests.get(url, timeout=(30, 300))
            if r.status_code != 200:
                return None
            raw = blosc().decode(r.content)
            return np.frombuffer(raw, dtype="<f4").reshape(37, 721, 1440)
        except Exception:                              # noqa: BLE001
            time.sleep(2.0 * (k + 1))
    return None


def cap_and_sectors(field, lat):
    """-> (the polar-cap mean, {sector: the mean}) for one level.

    The cap is the NORTHERN cap only.  The native store's latitude
    coordinate runs from 90N down to 90S, so the northern cap is the rows
    at 60N and above - a test on the absolute value would take in the
    southern cap as well.

    The mean is weighted by cos(latitude) over the cap rows and over every
    longitude of the globe, so the denominator carries the longitude count
    too.
    """
    nlon = field.shape[1]
    lons = np.arange(nlon, dtype=float) * (360.0 / nlon)
    w = np.where(lat >= CAP_S - 1e-6, np.cos(np.deg2rad(lat)), 0.0)
    cap = float((field * w[:, None]).sum() / (w.sum() * nlon))
    out = {}
    for name, (a, b) in SECTORS.items():
        if b <= a:
            m = (lons >= a) | (lons <= b)
        else:
            m = (lons >= a) & (lons <= b)
        if not m.any():
            out[name] = np.nan
            continue
        out[name] = float((field[:, m] * w[:, None]).sum() / (w.sum() * m.sum()))
    return cap, out


def main(days=DAYS, out=OUT):
    today = dt.date.today()
    lat = latitude()
    jrows = {lv: LEV37.index(lv) for lv in LEVELS}

    times, rows, cap_rows_out, sec = [], [], [], {k: [] for k in SECTORS}
    for back in range(days, -1, -1):
        day = today - dt.timedelta(days=back)
        a = chunk(day)
        if a is None:
            print("   %s: the chunk is missing" % day)
            continue
        caps, secs = [], {k: [] for k in SECTORS}
        for lv in LEVELS:
            c, s = cap_and_sectors(a[jrows[lv]].astype(float), lat)
            caps.append(c)
            for k in SECTORS:
                secs[k].append(s[k])
        times.append("%s 12" % day.isoformat())
        rows.append(caps)
        for k in SECTORS:
            sec[k].append(secs[k])
        print("   %s: the 10 hPa cap mean %12.1f m2/s2" % (day, caps[0]))

    if len(times) < 20:
        print("   only %d days came back - nothing written" % len(times))
        return 1
    np.savez_compressed(out, times=np.array(times),
                        values=np.array(rows, float),
                        levels=np.array(LEVELS),
                        sectors=np.array([np.array(sec[k], float)
                                          for k in SECTORS], dtype=object),
                        sector_names=np.array(list(SECTORS)))
    print("   wrote %s: %d days, %d levels" % (out, len(times), len(LEVELS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
