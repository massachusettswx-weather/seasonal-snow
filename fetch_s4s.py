"""ECMWF Subseasonal (S4S) sea surface temperature for the ENSO plumes.

The S4S is not in the C3S seasonal catalogue - it lives in ECMWF's own
climate store (ECDS, dataset "s2s-forecasts", origin "ecmwf", level_type
"oceanic").  It runs 46 days a week, so the plume it produces is a weekly
one: week 1 is the week after the init.

    python3 fetch_s4s.py
"""
import json
import os
import sys
import time
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
sys.path.insert(0, HERE)
from enso_common import (BASIN_NAMES, basin_mean, land_mask_on,  # noqa: E402
                         tropical_mean)

ECDS = "https://ecds.ecmwf.int/api"
TAG = "ecmwf-s4s"
AREA = [20.0, 140.0, -20.0, 290.0]


def key():
    with open(os.path.join(HERE, ".cdsapirc")) as f:
        return [l.split(":", 1)[1].strip() for l in f
                if l.strip().startswith("key:")][0]


def latest_monday(y, m):
    """The S4S runs on Mondays; take the Monday of the init week."""
    d = date(y, m, 1)
    while d.weekday() != 0:
        d += timedelta(days=1)
    return d


def fetch(init):
    import requests
    s = requests.Session()
    s.headers.update({"PRIVATE-TOKEN": key()})
    d = os.path.join(MDIR, TAG)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "sst_weekly.grib")
    if os.path.exists(out) and os.path.getsize(out) > 10000:
        print("  have %s" % os.path.basename(out), flush=True)
        return out
    # the weekly means, week 1 .. week 6
    leads = []
    for w in range(6):
        a = 24 + 48 * w
        leads.append("%d_%d" % (a, a + 24))
    req = {"origin": "ecmwf", "year": "%04d" % init.year,
           "month": "%02d" % init.month, "day": "%02d" % init.day,
           "time": "00:00", "level_type": "oceanic",
           "variable": ["sea_surface_temperature"],
           "forecast_type": ["control_forecast", "perturbed_forecast"],
           "leadtime_hour": leads, "area": AREA, "data_format": "grib"}
    print("  requesting the S4S SST, init %s, weeks 1-6" % init, flush=True)
    r = s.post("%s/retrieve/v1/processes/s2s-forecasts/execute" % ECDS,
               json={"inputs": req}, timeout=180)
    if r.status_code >= 400:
        print("  submit failed HTTP %d: %s" % (r.status_code, r.text[:300]),
              flush=True)
        return None
    jid = r.json().get("jobID") or r.json().get("processID")
    print("  job %s" % jid, flush=True)
    for _ in range(240):
        time.sleep(15)
        jr = s.get("%s/retrieve/v1/jobs/%s" % (ECDS, jid), timeout=60)
        if jr.status_code != 200:
            continue
        st = jr.json().get("status")
        if st == "successful":
            break
        if st in ("failed", "error", "rejected", "dismissed"):
            print("  job %s" % st, flush=True)
            return None
    else:
        print("  timed out" , flush=True)
        return None
    rr = s.get("%s/retrieve/v1/jobs/%s/results" % (ECDS, jid), timeout=120)
    link = rr.json()["asset"]["value"]["href"]
    with s.get(link, stream=True, timeout=300) as dr:
        with open(out + ".part", "wb") as f:
            for chunk in dr.iter_content(4 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    os.replace(out + ".part", out)
    print("  saved %s (%.1f MB)" % (os.path.basename(out),
                                    os.path.getsize(out) / 1e6), flush=True)
    return out


def read_weekly(path, init):
    """-> (week labels, {basin: [per-member values per week]}, tropical).

    The GRIB holds one field per member per week; the members stay separate
    so the plume keeps its spread.
    """
    import eccodes
    recs = []
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                step = int(eccodes.codes_get(gid, "step"))
                num = int(eccodes.codes_get(gid, "number"))
                dd = int(eccodes.codes_get(gid, "dataDate"))
                d0 = date(dd // 10000, (dd // 100) % 100, dd % 100)
                lat = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                lon = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                vals = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                recs.append((step, num, d0, lat, lon, vals))
            except Exception:
                pass
            eccodes.codes_release(gid)
    if not recs:
        return None
    lat = np.unique(recs[0][3])[::-1]
    lon = np.unique(recs[0][4])
    order = np.argsort(lon)
    land = land_mask_on(lat, lon)
    per_week = {}
    for step, num, d0, la, lo, vals in recs:
        valid = d0 + timedelta(hours=step)
        w = valid - timedelta(days=1)           # the week starts a day earlier
        per_week.setdefault(w, {})[num] = vals.reshape(len(lat), len(lon))[:, order]
    weeks, basin, trop = [], {n: [] for n in BASIN_NAMES}, []
    for w in sorted(per_week):
        members = per_week[w]
        nums = sorted(members)
        bm = {n: [] for n in BASIN_NAMES}
        tm = []
        for num in nums:
            v = np.where(members[num] > 1000.0, np.nan, members[num])
            b = basin_mean(lat, lon, v, land)
            for n in BASIN_NAMES:
                bm[n].append(b[n])
            tm.append(tropical_mean(lat, lon, v, land))
        for n in BASIN_NAMES:
            basin[n].append(bm[n])
        trop.append(tm)
        weeks.append(w.isoformat())
    return weeks, basin, trop


def main():
    init = latest_monday(2026, 11)
    print("== %s (init %s)" % (TAG, init), flush=True)
    p = fetch(init)
    if not p:
        return
    got = read_weekly(p, init)
    if not got:
        print("  could not read the GRIB", flush=True)
        return
    weeks, basin, trop = got
    out = {"kind": "s4s", "note": "ECMWF Subseasonal (S4S), ECDS s2s-forecasts",
           "init": init.isoformat(), "weeks": weeks, "basins": BASIN_NAMES,
           "series": {n: basin[n] for n in BASIN_NAMES},
           "tropical": trop}
    json.dump(out, open(os.path.join(MDIR, TAG, "enso.json"), "w"), indent=1)
    print("  weeks:", weeks, flush=True)
    for n in BASIN_NAMES:
        m = np.array(basin[n]).mean(axis=1)
        print("   %-9s %s" % (n, " ".join("%.2f" % (v - 273.15) for v in m)),
              flush=True)
    print("   members: %d" % len(basin[BASIN_NAMES[0]][0]), flush=True)


if __name__ == "__main__":
    main()
