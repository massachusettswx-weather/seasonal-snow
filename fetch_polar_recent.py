"""The ERA5 analysis just before a seasonal model's init, for the polar cap.

The polar-cap section has two halves: the ERA5 ANALYSIS on the left of the
"forecast starts" line, and the model's FORECAST on the right.  The analysis
half is the recent past, so it has to come from a live source - ARCO stops
at the end of 2022.

The source is the CDS ERA5 hourly pressure-level product, restricted to the
polar cap with the `area` widget, at 12 UTC only (the same convention the
rest of the site uses for its ERA5 layers).  The archive's cost limit
refuses three years at twelve levels, so the window is pulled in chunks of a
few months.

Every request is reduced on arrival to the polar-cap zonal mean per level
and only that is kept, so the cache is a few hundred kB rather than tens of
GB.
"""
import json
import os
import sys
import time
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import LEVELS, read_grib_levels  # noqa: E402

OUT = os.path.join(DATA, "polar_cap_recent.npz")
STATE = os.path.join(DATA, "polar_recent_jobs.json")

LV = [str(x) for x in LEVELS]
AREA = [90, -180, 60, 180]      # north, west, south, east
TIME = "12:00"                   # the site's ERA5 convention

# the analysis window: the two months before the November init.  Thirty
# days of analysis is what the section shows, so October and November
# cover it - the CDS queue on this account is the bottleneck and every
# extra request is one more that has to wait.
WINDOW = (date(2026, 10, 1), date(2026, 11, 2))


def chunks(start, end, months=2):
    """The request windows, about `months` long each."""
    out = []
    d = start
    while d <= end:
        stop = date(d.year + (d.month - 1 + months) // 12,
                    (d.month - 1 + months) % 12 + 1, 1) - timedelta(days=1)
        if stop > end:
            stop = end
        out.append((d, stop))
        d = stop + timedelta(days=1)
    return out


def build_request(d0, d1):
    """The request for one window.

    The CDS wants the days as a LIST OF DAYS, and every month in the window
    has to be listed with the days that actually exist in it - listing
    "01".."31" for a two-month window repeats the day numbers and the
    archive refuses the request outright.
    """
    months = {}
    d = d0
    while d <= d1:
        months.setdefault((d.year, d.month), []).append("%02d" % d.day)
        d += timedelta(days=1)
    req = {
        "product_type": "reanalysis",
        "variable": "geopotential",
        "pressure_level": LV,
        "year": sorted(set(y for y, m in months)),
        "month": sorted(set("%02d" % m for y, m in months)),
        "day": sorted(set(dd for v in months.values() for dd in v)),
        "time": [TIME],
        "area": AREA,
        "data_format": "grib",
    }
    # the archive needs one request per month: the day list is shared by all
    # the months in a request, so a window that spans a month boundary with
    # different day sets has to be split
    return [({"year": [str(y)], "month": ["%02d" % m], "day": v}, (y, m))
            for (y, m), v in sorted(months.items())]


def save(times, values):
    np.savez_compressed(OUT, times=np.array(times), levels=np.array(LEVELS),
                        values=np.array(values, float))


def load():
    if not os.path.exists(OUT):
        return [], []
    d = np.load(OUT, allow_pickle=True)
    return [str(t) for t in d["times"]], np.asarray(d["values"], float)


def main():
    import cds_direct
    cds = cds_direct.CDSDirect()
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"jobs": []}
    times, values = load()
    have = set(t[:10] for t in times)
    # one request per month: the CDS shares the day list across the months
    # in a request, so a month with 31 days cannot be asked for together
    # with one that has 30
    plan = []
    for d0, d1 in chunks(*WINDOW):
        for req, (y, m) in build_request(d0, d1):
            plan.append(("%04d-%02d" % (y, m), req))

    def harvest(job):
        """Download and decode one finished job."""
        path = os.path.join(DATA, "_recent.grib")
        cds.download_job(job["job"], path)
        ts, vals = read_grib_levels(path)
        os.remove(path)
        for t in ts:
            row = [vals[t].get(l) for l in LEVELS]
            if any(x is None for x in row):
                continue
            if t[:10] in have:
                continue
            have.add(t[:10])
            times.append(t)
            values.append(row)
        save(times, values)
        job["status"] = "decoded"
        json.dump(st, open(STATE, "w"), indent=1)
        print("   the %s window decoded: %d days in the cache"
              % (job["key"], len(times)), flush=True)

    # 1. harvest whatever is already in flight: the queue on this account
    #    holds two jobs at a time, so a job that has been waiting for hours
    #    must be collected before a new one is even considered
    for job in list(st["jobs"]):
        if job.get("status") not in ("accepted", "running", "queued"):
            continue
        status = cds.job_status(job["job"])
        job["status"] = status
        if status in ("completed", "successful"):
            harvest(job)
        elif status in ("failed", "rejected", "dismissed"):
            print("   the %s window is %s" % (job["key"], status), flush=True)
        else:
            print("   the %s window is %s" % (job["key"], status), flush=True)
    json.dump(st, open(STATE, "w"), indent=1)

    # 2. submit the months that are not already covered
    for key, req in plan:
        done = [j for j in st["jobs"] if j["key"] == key and j.get("status") == "decoded"]
        if done:
            continue
        live = [j for j in st["jobs"] if j["key"] == key
                and j.get("status") in ("accepted", "running", "queued")]
        if live:
            continue          # already in flight - do not duplicate it
        # the account holds two jobs; do not push a third
        n = 0
        try:
            n = sum(1 for j in cds.live_jobs()
                    if j.get("status") in ("accepted", "running", "queued"))
        except Exception:
            pass
        if n >= 2:
            print("   the account's queue is full (%d) - waiting" % n, flush=True)
            time.sleep(60)
            continue
        try:
            jid = cds.submit("reanalysis-era5-pressure-levels", req)
        except Exception as e:
            msg = str(e)
            if "Maximum number queued" in msg:
                print("   the queue is full - waiting", flush=True)
                time.sleep(120)
                continue
            print("   the %s submission failed: %s" % (key, msg[:160]), flush=True)
            time.sleep(60)
            continue
        st["jobs"].append({"key": key, "job": jid, "status": "accepted"})
        json.dump(st, open(STATE, "w"), indent=1)
        print("   the %s month submitted: %s" % (key, jid), flush=True)

    print("   the recent analysis: %d days -> %s" % (len(times), OUT), flush=True)


def run():
    """Loop until every month in the window is decoded.

    The CDS queue on this account holds two jobs at a time and jobs can sit
    "accepted" for hours, so the puller stays up and polls rather than
    exiting after one pass.
    """
    import cds_direct
    while True:
        st = json.load(open(STATE)) if os.path.exists(STATE) else {"jobs": []}
        need = []
        for d0, d1 in chunks(*WINDOW):
            for req, (y, m) in build_request(d0, d1):
                key = "%04d-%02d" % (y, m)
                dec = [j for j in st["jobs"]
                       if j["key"] == key and j.get("status") == "decoded"]
                if not dec:
                    need.append(key)
        if not need:
            print("   the window is complete", flush=True)
            return
        try:
            main()
        except Exception as e:
            print("   the pass failed: %s" % str(e)[:140], flush=True)
        time.sleep(60)


if __name__ == "__main__":
    run()
