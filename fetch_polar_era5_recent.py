"""The recent ERA5 reanalysis for the polar-cap section.

The section shows the last 90 days of ERA5 in front of the model's own
forecast: what actually happened, and what might happen.  This pulls the
ERA5 half.

The request is the CDS "reanalysis-era5-pressure-levels" product, over the
polar cap only, at the twelve levels the section is drawn on, at 12Z.  The
CDS shares the day list across the months in a request, so a window is
split into requests whose months all have the same number of days.

The reanalysis lags real time by a few days, so the window is measured
back from the last day the archive actually has.
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

from polar_cap import read_grib_levels, zonal_mean   # noqa: E402

LEVELS = [10, 30, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]
AREA = [90, -180, 60, 180]
OUT = os.path.join(DATA, "polar_era5_recent.npz")
STATE = os.path.join(DATA, "polar_era5_recent_jobs.json")


def requests_for(d0, d1, partial_days=7):
    """The requests that cover d0..d1 - one per month.

    The CDS shares the day list across the months of a request, so months
    with different lengths cannot be asked for together, and a month that is
    only partly covered must not ask for days that are not there yet (the
    archive answers the whole request with "no data" if it is).  The last
    month of the window is therefore asked for day by day up to
    ``partial_days``, which is what the reanalysis latency allows for.
    """
    import calendar
    out = []
    d = d0
    while d <= d1:
        nd = calendar.monthrange(d.year, d.month)[1]
        last_in_month = min(nd, (d1 - d).days + 1)
        full = last_in_month == nd
        ndays = nd if full else min(last_in_month, partial_days)
        last_day = (date(d.year, d.month, nd) if full
                    else d + timedelta(days=ndays - 1))
        out.append({
            "year": ["%04d" % d.year],
            "month": ["%02d" % d.month],
            "day": ["%02d" % i for i in range(1, ndays + 1)],
            "first": d.isoformat(),
            "last": last_day.isoformat(),
            "full": full,
        })
        d = date(d.year, d.month, 1) + timedelta(days=nd)
    return out


def load():
    if not os.path.exists(OUT):
        return [], []
    d = np.load(OUT, allow_pickle=True)
    return [str(t) for t in d["times"]], np.asarray(d["values"], float)


def save(times, values):
    np.savez_compressed(OUT, times=np.array(times), levels=np.array(LEVELS),
                        values=np.asarray(values, float))


def decode(path):
    """-> (times, {level: the polar cap mean})"""
    times, vals = read_grib_levels(path)
    return times, vals


def account_room(cds, mine=0):
    """How many jobs the ACCOUNT holds, and so how much room is left.

    The CDS admission gate is account-wide at two, so the count comes from
    the account's own job list, not from the local state file.
    """
    try:
        n = sum(1 for j in cds.live_jobs()
                if j.get("status") in ("accepted", "running", "queued"))
    except Exception:
        return None
    return max(0, 2 - n)


def main():
    import cds_direct
    cds = cds_direct.CDSDirect()
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    end = date.today() - timedelta(days=5)
    start = end - timedelta(days=days - 1)
    print("   the ERA5 reanalysis window: %s -> %s (%d days)"
          % (start, end, days), flush=True)

    times, values = load()
    have = set(t[:10] for t in times)
    dirty = False
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"jobs": []}
    plan = requests_for(start, end)

    for _ in range(400):
        # 1. harvest whatever has finished
        for j in list(st["jobs"]):
            if j.get("status") not in ("accepted", "running", "queued"):
                continue
            status = cds.job_status(j["job"])
            j["status"] = status
            if status not in ("successful", "completed"):
                if status in ("failed", "rejected", "dismissed"):
                    print("   the %s job is %s" % (j["key"], status), flush=True)
                continue
            path = os.path.join(DATA, "_era5_recent.grib")
            cds.download_job(j["job"], path)
            ts, vals = decode(path)
            os.remove(path)
            n = 0
            for t in ts:
                row = [vals[t].get(l) for l in LEVELS]
                if any(x is None for x in row):
                    continue
                if t[:10] in have:
                    continue
                have.add(t[:10])
                times.append(t)
                values.append(row)
                n += 1
            print("   the %s job decoded: %d days" % (j["key"], n), flush=True)
            j["status"] = "decoded"
            if n:
                dirty = True
            json.dump(st, open(STATE, "w"), indent=1)

        # 2. submit what is still missing, if the account has room
        room = account_room(cds)
        if room is None:
            room = 0
        pending = {j["key"] for j in st["jobs"]
                   if j.get("status") in ("accepted", "running", "queued")}
        done = {j["key"] for j in st["jobs"] if j.get("status") == "decoded"}
        for r in plan:
            key = "%s-%s" % (r["first"], r["last"])
            if key in pending or key in done:
                continue
            if room <= 0:
                print("   the account's queue is full - waiting", flush=True)
                break
            req = {"variable": ["geopotential"],
                   "pressure_level": ["%d" % l for l in LEVELS],
                   "year": r["year"], "month": r["month"], "day": r["day"],
                   "time": "12:00", "area": AREA, "data_format": "grib"}
            try:
                jid = cds.submit("reanalysis-era5-pressure-levels", req)
            except Exception as e:
                print("   the %s submission failed: %s"
                      % (key, str(e)[:140]), flush=True)
                time.sleep(60)
                break
            st["jobs"].append({"key": key, "job": jid, "status": "accepted",
                               "first": r["first"], "last": r["last"]})
            json.dump(st, open(STATE, "w"), indent=1)
            print("   the %s request submitted: %s" % (key, jid), flush=True)
            room -= 1
            time.sleep(10)

        order = np.argsort(times) if times else []
        if len(times) and dirty:
            # the file is only rewritten when the CONTENT changed.  Writing
            # it every minute would change its timestamp, and the publisher
            # watches that file - it would rebuild and publish the whole site
            # once a minute for nothing.
            times = [times[i] for i in order]
            values = np.asarray(values, float)[order]
            save(times, values)
            dirty = False

        want = set()
        d = start
        while d <= end:
            want.add(d.isoformat())
            d += timedelta(days=1)
        missing = len(want - have)
        if missing == 0:
            print("   the recent ERA5 is complete: %d days -> %s"
                  % (len(times), OUT), flush=True)
            return
        print("   the recent ERA5: %d days, %d missing"
              % (len(times), missing), flush=True)
        time.sleep(60)


if __name__ == "__main__":
    main()
