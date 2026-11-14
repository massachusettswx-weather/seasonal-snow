"""Cross-check the ARCO-native ERA5 against the CDS ERA5, day by day.

The polar chart's ERA5 half comes from ARCO's native 0.25 degree store and
its climate from the same store.  The claim that the CDS's monthly means
were ~10 K cold in the stratosphere needs a direct test: take one month of
the CDS daily ERA5 (reanalysis-era5-pressure-levels, geopotential, 12Z) and
reduce it to the same polar cap mean the chart uses, then compare it with
the ARCO-native value for the same day.

    python3 check_era5_cross.py 2026 9
"""

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from polar_cap import LEVELS, zonal_mean            # noqa: E402

DATA = os.path.join(HERE, "data")
CDS = "https://cds.climate.copernicus.eu/api/retrieve/v1/processes/reanalysis-era5-pressure-levels/execute"
AREA = [90.0, -180.0, 60.0, 180.0]


def key():
    with open(os.path.join(HERE, ".cdsapirc")) as f:
        return [l.split(":", 1)[1].strip() for l in f
                if l.strip().startswith("key:")][0]


def submit(year, month):
    import requests
    import calendar
    days = ["%02d" % d for d in range(1, calendar.monthrange(year, month)[1] + 1)]
    body = {"inputs": {
        "product_type": "reanalysis",
        "variable": ["geopotential"],
        "year": "%04d" % year,
        "month": ["%02d" % month],
        "day": days,
        "time": "12:00",
        "pressure_level": ["%d_hpa" % l for l in LEVELS],
        "area": AREA,
        "format": "grib",
    }, "outputs": {"asset": {"value": {"type": "file"}}}}
    s = requests.Session()
    s.headers.update({"PRIVATE-TOKEN": key(), "Content-Type": "application/json"})
    r = s.post(CDS, json=body, timeout=300)
    if r.status_code >= 400:
        raise RuntimeError("submit failed HTTP %d: %s" % (r.status_code, r.text[:300]))
    return s, r.json()["jobID"]


def wait(s, jid, tries=240):
    import time
    for _ in range(tries):
        time.sleep(15)
        r = s.get("https://cds.climate.copernicus.eu/api/retrieve/v1/jobs/%s" % jid,
                  timeout=60)
        if r.status_code != 200:
            continue
        st = r.json().get("status")
        if st in ("successful", "completed"):
            return True
        if st in ("failed", "error", "rejected", "dismissed"):
            print("   the job is %s" % st, flush=True)
            return False
    return False


def download(s, jid, path):
    r = s.get("https://cds.climate.copernicus.eu/api/retrieve/v1/jobs/%s/results" % jid,
              timeout=120)
    link = r.json()["asset"]["value"]["href"]
    with s.get(link, stream=True, timeout=600) as dr:
        with open(path, "wb") as f:
            for chunk in dr.iter_content(4 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    return path


def read_cap(path):
    """-> {time: {level: the polar cap mean}} from the CDS GRIB."""
    import eccodes
    from datetime import date, timedelta
    out = {}
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:                          # noqa: BLE001
                break
            if gid is None:
                break
            try:
                la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                lo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                ni = int(eccodes.codes_get(gid, "Ni", 0) or 0)
                nj = int(eccodes.codes_get(gid, "Nj", 0) or 0)
                if ni and nj and v.size == ni * nj:
                    v = v.reshape(nj, ni)
                    lat2d = la.reshape(nj, ni)
                    lon2d = lo.reshape(nj, ni)
                else:
                    lats = np.unique(la)[::-1]
                    lons = np.unique(lo)
                    if v.size != lats.size * lons.size:
                        continue
                    v = v.reshape(len(lats), len(lons))
                    lat2d = np.repeat(lats[:, None], len(lons), axis=1)
                    lon2d = np.repeat(lons[None, :], len(lats), axis=0)
                vd = int(eccodes.codes_get(gid, "validityDate"))
                vt = int(eccodes.codes_get(gid, "validityTime"))
                valid = date(vd // 10000, (vd // 100) % 100, vd % 100) \
                    + timedelta(hours=vt // 100, minutes=vt % 100)
                lev = int(eccodes.codes_get(gid, "level"))
                key = valid.strftime("%Y-%m-%d %H")
                out.setdefault(key, {})[lev] = zonal_mean(v, lat2d[:, 0])
            except Exception:                          # noqa: BLE001
                continue
            finally:
                try:
                    eccodes.codes_release(gid)
                except Exception:                      # noqa: BLE001
                    pass
    return out


def main():
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    month = int(sys.argv[2]) if len(sys.argv) > 2 else 9
    grib = os.path.join(DATA, "_xcheck_cds_%04d%02d.grib" % (year, month))
    if not os.path.exists(grib):
        s, jid = submit(year, month)
        print("   the job %s submitted" % jid, flush=True)
        if not wait(s, jid):
            return
        download(s, jid, grib)
        print("   the GRIB is down", flush=True)
    cds = read_cap(grib)
    os.remove(grib)

    # the ARCO-native series the chart uses
    arco = np.load(os.path.join(DATA, "polar_era5_recent.npz"), allow_pickle=True)
    atimes = [str(t) for t in arco["times"]]
    avals = arco["values"]
    alev = [int(x) for x in arco["levels"]]
    amap = {t: {l: avals[i][j] for j, l in enumerate(alev)}
            for i, t in enumerate(atimes)}

    rows = []
    for t in sorted(cds):
        if t not in amap:
            continue
        for lev in (10, 100, 500, 1000):
            if lev not in cds[t] or lev not in amap[t]:
                continue
            rows.append((t, lev, cds[t][lev], amap[t][lev]))
    print("   %-18s %6s %12s %12s %10s" % ("time", "hPa", "CDS", "ARCO", "difference"))
    for t, lev, c, a in rows:
        if lev != 10:
            continue
        print("   %-18s %6d %12.0f %12.0f %10.0f" % (t, lev, c, a, c - a))
    for lev in (10, 100, 500, 1000):
        d = [c - a for t, l, c, a in rows if l == lev]
        if d:
            print("   the level %5d hPa: the mean difference %8.0f m2/s2 "
                  "(%6.0f m), %d days"
                  % (lev, float(np.mean(d)), float(np.mean(d)) /9.81, len(d)))


if __name__ == "__main__":
    main()
