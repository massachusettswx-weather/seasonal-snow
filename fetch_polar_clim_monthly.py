"""The polar-cap climatology in the SAME convention as the data it normalises.

**Why this had to be rebuilt.**  The ERA5 polar-cap climatology was first
built from ARCO's *reduced* 1.5 degree store, which is ARCO's own
conservative remapping of the ERA5 pressure-level product.  That remapping
moves the polar-cap mean by 0.2-0.8% - and it moves it by a different
amount on different days, because it depends on how the field is shaped.

That is small in the numbers and large in the picture.  At 10 hPa the
polar-cap mean is about 293,000 m2/s2, so 0.7% is 2,000 m2/s2, and the
day-to-day standard deviation in October is only about 800.  The
reanalysis drawn against that climatology came out a whole 2-3 sigma too
cold for every day, and the stratospheric warming of early November 2026
did not appear in it at all.

So the climatology has to be built from the **native** ERA5 pressure-level
product - the same product the recent reanalysis and the seasonal models
are on.  The CDS `reanalysis-era5-pressure-levels-monthly-means` gives
30 years of monthly means on that native grid in ONE request.

The mean and the standard deviation are taken over the 30 years for each
calendar month and each level: the monthly climate and the way a single
month departs from it, which is the scale a seasonal forecast is judged
against.

    python3 fetch_polar_clim_monthly.py
"""
import json
import os
import sys
import time
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import read_grib_levels_sectors   # noqa: E402

LEVELS = [10, 30, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]
AREA = [90, -180, 60, 180]
YEARS = list(range(1991, 2021))

STATE = os.path.join(DATA, "polar_clim_jobs.json")
OUT = os.path.join(DATA, "polar_cap_clim_monthly.npz")

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November",
               "December"]


def submit(cds):
    """The one request that carries the whole 30-year climatology."""
    req = {"variable": ["geopotential"],
           "pressure_level": ["%d" % l for l in LEVELS],
           "year": ["%d" % y for y in YEARS],
           "month": ["%02d" % m for m in range(1, 13)],
           "area": AREA,
           "data_format": "grib"}
    jid = cds.submit("reanalysis-era5-pressure-levels-monthly-means", req)
    st = {"jobs": [{"job": jid, "status": "accepted"}]}
    json.dump(st, open(STATE, "w"), indent=1)
    print("   the monthly means request: %s" % jid, flush=True)
    return jid


def build(path):
    """The GRIB -> the per-month mean and sigma over the 30 years.

    The same climate is built for the two sectors of the cap, so a sector
    section is judged against the sector's OWN climate - the Atlantic and
    the Pacific do not have the same mean height, and they do not have the
    same day to day spread.
    """
    times, vals, sec = read_grib_levels_sectors(path)
    by_month = defaultdict(dict)
    by_month_s = defaultdict(dict)
    # `vals` is the {time: {level: value}} dictionary; `times` is only the
    # list of time strings
    for t, levels in vals.items():
        by_month[t[:7]][t] = levels
    for t, sdict in sec.items():
        by_month_s[t[:7]][t] = sdict
    rows = []
    srows = []
    for ym in sorted(by_month):
        # one month can carry more than one field (the monthly mean product
        # writes the month on its first day); take the first that has every
        # level
        for t in sorted(by_month[ym]):
            lv = by_month[ym][t]
            if all(l in lv for l in LEVELS):
                rows.append((ym, [lv[l] for l in LEVELS]))
                sd = by_month_s.get(ym, {}).get(t, {})
                srows.append((ym, {name: [d[l] for l in LEVELS]
                                   for name, d in sd.items()
                                   if all(l in d for l in LEVELS)}))
                break
    if not rows:
        raise SystemExit("the GRIB has no complete month")
    print("   %d months read" % len(rows), flush=True)

    out = {}
    sout = {}
    for m in range(1, 13):
        a = np.array([r[1] for r in rows if int(r[0][5:7]) == m], float)
        good = np.isfinite(a).all(axis=1)
        a = a[good]
        if a.shape[0] < 2:
            print("   month %02d has only %d years - skipped" % (m, a.shape[0]))
            continue
        out[m] = {"n": int(a.shape[0]),
                  "mean": a.mean(axis=0).tolist(),
                  "sigma": a.std(axis=0, ddof=1).tolist()}
        print("   %-10s %2d years   the 10 hPa mean %10.1f  sigma %8.1f"
              % (MONTH_NAMES[m - 1], a.shape[0], out[m]["mean"][0],
                 out[m]["sigma"][0]), flush=True)
        # the sectors
        names = sorted({n for _, sd in srows for n in sd})
        for name in names:
            b = np.array([sd[name] for ym, sd in srows
                          if int(ym[5:7]) == m and name in sd], float)
            if b.ndim != 2 or b.shape[0] < 2:
                continue
            b = b[np.isfinite(b).all(axis=1)]
            if b.shape[0] < 2:
                continue
            sout.setdefault(name, {})[m] = {
                "n": int(b.shape[0]),
                "mean": b.mean(axis=0).tolist(),
                "sigma": b.std(axis=0, ddof=1).tolist()}

    np.savez_compressed(OUT,
                        levels=np.array(LEVELS),
                        months=np.array(sorted(out)),
                        mean=np.array([out[m]["mean"] for m in sorted(out)], float),
                        sigma=np.array([out[m]["sigma"] for m in sorted(out)], float),
                        count=np.array([out[m]["n"] for m in sorted(out)], int),
                        sector_names=np.array(sorted(sout)),
                        sector_data=np.array(
                            [{name: {int(m): {"mean": sout[name][m]["mean"],
                                             "sigma": sout[name][m]["sigma"],
                                             "n": sout[name][m]["n"]}
                                     for m in sout[name]}
                              for name in sorted(sout)}], dtype=object))
    print("   the sector climates: %s" % ", ".join(
        "%s (%d months)" % (n, len(sout[n])) for n in sorted(sout)), flush=True)
    print("   -> %s" % OUT)
    return OUT


def main():
    import cds_direct
    cds = cds_direct.CDSDirect()
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"jobs": []}
    job = None
    for j in st.get("jobs", []):
        if j.get("status") not in ("rejected", "failed", "dismissed"):
            job = j["job"]          # the live one, if there is one
    if job is None:
        # the account holds two requests at a time; wait for a slot rather
        # than be refused
        for _ in range(240):
            n = sum(1 for j in cds.live_jobs()
                    if j.get("status") in ("accepted", "running", "queued"))
            if n < 2:
                break
            print("   the account's queue is full - waiting", flush=True)
            time.sleep(30)
        job = submit(cds)
    else:
        print("   the request already in flight: %s" % job, flush=True)

    grib = os.path.join(DATA, "_polar_clim_monthly.grib")
    for _ in range(2000):
        status = cds.job_status(job)
        print("   the job is %s" % status, flush=True)
        if status in ("successful", "completed"):
            cds.download_job(job, grib)
            build(grib)
            os.remove(grib)
            return
        if status in ("failed", "rejected", "dismissed", "gone"):
            print("   the job is %s - giving up" % status)
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
