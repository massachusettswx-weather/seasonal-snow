"""ERA5 polar-cap (60-90N) geopotential height, 1991-2020 + the current year.

The polar-cap time-height section needs the ERA5 analysis on the left of the
"forecast starts" line, and the 1991-2020 climatology (mean and sigma per
calendar day) to normalise the anomaly by sigma.

The source is the CDS ERA5 hourly pressure-level product, restricted to the
polar cap with the `area` widget, at 12 UTC only (the same convention the
rest of the site uses for its ERA5 layers), one year per request.  The
archive's cost limit refuses three years at a time, so the pull is chunked
by year.

Every request is reduced on arrival to the polar-cap zonal mean per level
and only that is kept, so the cache is a few MB rather than tens of GB.
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import LEVELS, zonal_mean  # noqa: E402

OUT = os.path.join(DATA, "era5_polarcap_z.json")
STATE = os.path.join(DATA, "polar_era5_jobs.json")

LV = [str(x) for x in LEVELS]
AREA = [90, -180, 60, 180]      # north, west, south, east
TIME = "12:00"                   # the site's ERA5 convention
YEARS = list(range(1991, 2021)) + [2026]


def load_cache():
    if os.path.exists(OUT):
        return json.load(open(OUT))
    return {}


def save_cache(c):
    tmp = OUT + ".tmp"
    json.dump(c, open(tmp, "w"))
    os.replace(tmp, OUT)


def read_grib_polar(path):
    """-> (times, {level: [values by time]}) of the polar-cap mean geopotential.

    The ERA5 request comes back as GRIB, which eccodes reads directly.
    """
    from polar_cap import read_grib_levels
    return read_grib_levels(path)


def fetch_year(cds, year):
    req = {
        "product_type": "reanalysis",
        "variable": "geopotential",
        "pressure_level": LV,
        "year": [str(year)],
        "month": ["%02d" % m for m in range(1, 13)],
        "day": ["%02d" % d for d in range(1, 32)],
        "time": [TIME],
        "area": AREA,
        "data_format": "grib",
    }
    return cds.submit("reanalysis-era5-pressure-levels", req)


def account_inflight(cds):
    """How many jobs the ACCOUNT holds right now, on any dataset.

    The CDS admission gate is ACCOUNT-WIDE: with two of our requests sitting
    queued, a third is refused whatever dataset it targets (ERA5 included).
    So the count has to come from the account's own job list, not from our
    own state file.
    """
    n = 0
    try:
        for j in cds.live_jobs():
            if j.get("status") in ("accepted", "running", "queued"):
                n += 1
    except Exception:
        return None
    return n


def build_npz(cache, out_path=None):
    """Merge the per-year cache into the npz the climatology builder wants.

    times  : (n,)   ISO "YYYY-MM-DD HH"
    levels : (nlev,)
    values : (n, nlev)  the polar cap mean geopotential height
    """
    times = []
    rows = []
    for y in sorted(cache, key=lambda s: int(s)):
        rec = cache[y]
        for t in rec["times"]:
            row = rec["values"].get(t, {})
            vals = [row.get(l) for l in LEVELS]
            if any(v is None for v in vals):
                continue
            times.append(t)
            rows.append(vals)
    if not times:
        return None
    order = np.argsort(times)
    times = [times[i] for i in order]
    rows = [rows[i] for i in order]
    p = out_path or os.path.join(DATA, "era5_polarcap_z.npz")
    np.savez_compressed(p, times=np.array(times), levels=np.array(LEVELS),
                        values=np.array(rows, float))
    return p


def main():
    import cds_direct
    cds = cds_direct.CDSDirect()
    cache = load_cache()
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"jobs": {}}
    todo = [y for y in YEARS if str(y) not in cache]
    if not todo:
        print("the ERA5 polar-cap cache is complete: %d years" % len(cache))
        return
    print("the years still needed: %s" % todo)
    # keep at most two requests in flight: the admission gate is account-wide
    MAX_INFLIGHT = 2
    while todo:
        # 1. harvest whatever has landed
        for y, j in list(st["jobs"].items()):
            if j.get("status") in ("accepted", "running", "queued"):
                status = cds.job_status(j["job"])
                j["status"] = status
                if status in ("completed", "successful"):
                    path = os.path.join(DATA, "_era5_z_%d.grib" % y)
                    cds.download_job(j["job"], path)
                    times, vals = read_grib_polar(path)
                    os.remove(path)
                    cache[str(y)] = {"times": times, "values": vals}
                    save_cache(cache)
                    build_npz(cache)
                    j["status"] = "decoded"
                    print("   the %d polar-cap year is decoded" % y, flush=True)
                elif status in ("failed", "rejected", "dismissed"):
                    print("   the %s job is %s - it will be retried" % (y, status),
                          flush=True)
                    j["status"] = "retry"
        # 2. count what the ACCOUNT holds (any dataset)
        n = account_inflight(cds)
        mine = sum(1 for j in st["jobs"].values()
                   if j.get("status") in ("accepted", "running", "queued"))
        if n is None:
            n = mine
        # 3. submit only while there is room in the account's queue
        room = MAX_INFLIGHT - n
        while room > 0 and todo:
            y = todo.pop(0)
            try:
                jid = fetch_year(cds, y)
            except Exception as e:
                print("   the %d submission failed: %s" % (y, str(e)[:140]), flush=True)
                time.sleep(60)
                todo.insert(0, y)
                break
            st["jobs"][str(y)] = {"job": jid, "status": "accepted"}
            room -= 1
            print("   the %d year submitted: %s" % (y, jid), flush=True)
        json.dump(st, open(STATE, "w"), indent=1)
        # a job that was refused comes back as "rejected": put it back in the
        # queue rather than losing the year
        for y, j in list(st["jobs"].items()):
            if j.get("status") == "retry" and y not in todo:
                todo.append(int(y))
        json.dump(st, open(STATE, "w"), indent=1)
        time.sleep(45)


if __name__ == "__main__":
    main()
