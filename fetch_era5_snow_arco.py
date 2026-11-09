"""ERA5 1991-2020 monthly SNOW climatology for the eastern U.S., built from the
ARCO-ERA5 store on Google Cloud (no CDS queue involved).

ERA5 does not publish "snowfall" in the ARCO single-level stores, so the snow
amount is derived from ERA5 itself the standard way:

    snow(day) = precip_24h(day) x fraction of the day's 6-hourly steps with
                 2 m temperature below 0 degC

precip_24h is ERA5's 24-hour total precipitation at 00Z (covering the calendar
day 00Z->00Z); the temperature fraction uses the four 6-hourly 2 m
temperatures of that day.

Saves clim[6, nlat, nlon] in mm w.e. per month for calendar months
11, 12, 1, 2, 3, 4 on the ARCO 0.75 deg grid over the eastern-US box.
"""
import os, sys, json, argparse, datetime, calendar
import numpy as np
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CACHE = os.path.join(DATA, "arco_chunks")
BUCKET = "https://storage.googleapis.com/gcp-public-data-arco-era5/"
STORE = "ar/1959-2022-6h-240x121_equiangular_with_poles_conservative.zarr"
EPOCH = datetime.date(1959, 1, 1)
MONTHS = [11, 12, 1, 2, 3, 4]
VARS = ("total_precipitation_24hr", "2m_temperature")
T0 = 273.15
NCHUNK_STEPS = 8


def _decode(buf):
    import numcodecs
    try:
        out = numcodecs.Blosc().decode(buf)
    except Exception:
        out = buf
    if isinstance(out, (bytes, bytearray)):
        out = np.frombuffer(out, dtype="<f4")
    return np.asarray(out, dtype=np.float32)


def fetch_chunk(var, k, use_cache=True):
    os.makedirs(os.path.join(CACHE, var), exist_ok=True)
    cp = os.path.join(CACHE, var, "%d.npy" % k)
    if use_cache and os.path.exists(cp):
        return k, np.load(cp)
    url = "%s%s/%s/%d.0.0" % (BUCKET, STORE, var, k)
    for attempt in range(4):
        try:
            buf = urllib.request.urlopen(url, timeout=90).read()
            arr = _decode(buf).reshape(NCHUNK_STEPS, -1, 121)
            if use_cache:
                np.save(cp, arr)
            return k, arr
        except Exception:
            if attempt == 3:
                raise
    return k, None


def step_index(day):
    """6-hourly ARCO index of 00Z on `day`."""
    return (day - EPOCH).days * 4


def coord(name):
    buf = urllib.request.urlopen("%s%s/%s/0" % (BUCKET, STORE, name), timeout=60).read()
    import numcodecs
    try:
        out = numcodecs.Blosc().decode(buf)
    except Exception:
        out = buf
    if isinstance(out, (bytes, bytearray)):
        out = np.frombuffer(out, dtype="<f8")
    return np.asarray(out, dtype=float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1991)
    ap.add_argument("--end", type=int, default=2020)
    ap.add_argument("--box", default="49,-100,24,-65", help="N,W,S,E")
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--months", default=",".join(str(m) for m in MONTHS))
    ap.add_argument("--out", default="era5_snow_clim_arco.npz")
    args = ap.parse_args()
    months = [int(x) for x in args.months.split(",")]
    out_npz = os.path.join(DATA, args.out)
    if os.path.exists(out_npz):
        print("already have", out_npz)
        return

    N, W, S, E = [float(x) for x in args.box.split(",")]
    lat = coord("latitude")
    lon = coord("longitude")
    li = np.where((lat >= S) & (lat <= N))[0]
    oi = np.where((lon >= (W % 360)) & (lon <= (E % 360)))[0]
    print("ARCO grid lon=%d lat=%d -> box %d lat x %d lon (lat %.1f..%.1f, lon %.1f..%.1f)"
          % (len(lon), len(lat), len(li), len(oi), lat[li].max(), lat[li].min(),
             lon[oi].min(), lon[oi].max()), flush=True)

    # month-by-month accumulation (both variables together, chunks are cached)
    accum = {mo: [] for mo in months}
    cache_p = {}
    cache_t = {}
    for y in range(args.start, args.end + 1):
        for mo in months:
            nd = calendar.monthrange(y, mo)[1]
            ks = sorted({step_index(datetime.date(y, mo, d)) // NCHUNK_STEPS
                         for d in range(1, nd + 1)})
            for k in ks:
                if k not in cache_p:
                    cache_p[k] = fetch_chunk("total_precipitation_24hr", k,
                                             not args.no_cache)[1]
                if k not in cache_t:
                    cache_t[k] = fetch_chunk("2m_temperature", k, not args.no_cache)[1]
            total = np.zeros((len(oi), len(li)))
            for d in range(1, nd + 1):
                day = datetime.date(y, mo, d)
                k = step_index(day) // NCHUNK_STEPS
                off = step_index(day) - k * NCHUNK_STEPS
                p = cache_p[k][off]                    # (nlon, nlat) 24h precip at 00Z
                temps = cache_t[k][off:off + 4]        # 00/06/12/18Z 2 m temperature
                frac = (temps < T0).sum(axis=0) / 4.0
                total += (p * frac)[np.ix_(oi, li)]
            accum[mo].append(total * 1000.0)          # m -> mm w.e.
            for k in ks:
                cache_p.pop(k, None); cache_t.pop(k, None)
        print("  %d done" % y, flush=True)

    clim = np.stack([np.mean(np.array(accum[mo]), axis=0) for mo in months])
    clim = np.transpose(clim, (0, 2, 1))                                       # (6, nlat, nlon)
    np.savez_compressed(out_npz, clim=clim.astype(np.float32),
                        lat=lat[li], lon=lon[oi],
                        months=np.array(months), years=np.array([args.start, args.end]))
    print("saved", out_npz, clim.shape)
    for i, mo in enumerate(months):
        print("  month %02d: box mean %.1f mm w.e./month" % (mo, clim[i].mean()))


if __name__ == "__main__":
    main()
