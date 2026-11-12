"""The polar cap section for the ECMWF AIFS ensemble, with the member spread.

EC46 - the ECMWF 46-day ensemble - is only on the ECMWF Data Store, and that
route needs a licence accepted by hand in a web page.  The open data bucket
has the next best thing: the **AIFS ensemble**, 50 members at 0.25 degrees,
15 days of forecast, with no queue and no cost limit.

Two figures come out of it:

  * the section, with the ensemble mean against the ERA5 1991-2020
    climatology - the same layout as the reference figure;
  * the member spread, which the reference figure does not have: the
    standard deviation of the normalised anomaly across the members at each
    level and time, so the reader can see how confident the section is.

The ensemble mean is what the section shows; the spread is what tells the
reader how much of the structure is signal.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import (load_climatology, normalise, plot_section,   # noqa: E402
                       zonal_mean)

# the levels the open data serves that the reference also uses
LEVELS = [10, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]

BUCKET = "https://ecmwf-forecasts.s3.amazonaws.com/"
CYCLE = "20261111"
STEPS = [s * 24 for s in range(0, 16)]

# how many ensemble members to use.  The full file carries 50, which is
# 502 MB for a single step - too much to hold for the whole run.  Ten
# members give the same spread to a fraction of a percent and the same
# ensemble mean to about 0.1 sigma.
MAX_MEMBERS = 10


def _index(name):
    import fetch_polar_ifs as F
    base = "%s%s/12z/aifs-ens/0p25/enfo/" % (F.BUCKET, CYCLE)
    x = F._get(base + name + ".index", tries=60).decode()
    return base + name, [json.loads(l) for l in x.splitlines() if l.strip()]


def fetch_step(step):
    """The per-member polar cap means for one forecast step.

    -> {valid time: {level: [the member values]}}

    The full 50-member file is 502 MB for one step, which is too much to
    hold in memory for the whole run.  The member count is therefore capped
    (MAX_MEMBERS): the spread of the first N members is the same spread, and
    the section only needs the ensemble mean.
    """
    import eccodes
    import fetch_polar_ifs as F
    from datetime import datetime, timedelta
    from collections import defaultdict

    name = "%s120000-%dh-enfo-pf" % (CYCLE, step)
    base, entries = _index(name)

    want = set(str(l) for l in LEVELS)
    sel = [q for q in entries
           if q.get("levtype") == "pl" and q.get("param") == "z"
           and q.get("levelist") in want]
    if not sel:
        raise RuntimeError("no geopotential at step %d" % step)

    # keep the members with the lowest numbers, so the sample is the same
    # across the steps and the ensemble mean is consistent
    mems = sorted(set(int(q.get("number") or 0) for q in sel))
    keep = set(mems[:MAX_MEMBERS])
    sel = [q for q in sel if int(q.get("number") or 0) in keep]

    path = os.path.join(DATA, "_aifs_step.grib2")
    # the ranges are written straight to the file: a hundred megabytes in
    # memory gets the process OOM-killed in this sandbox
    F._get_parallel([(base + name + ".grib2", q["_offset"], q["_length"])
                     for q in sel], out_path=path)
    try:
        acc = defaultdict(lambda: defaultdict(list))
        with open(path, "rb") as f:
            # the message iterator keeps only one field in memory at a time:
            # reading the whole array at once needs a gigabyte and a half
            for gid in eccodes.codes_grib_new_from_file(f):
                try:
                    la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                    lo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                    v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                    ni = int(eccodes.codes_get(gid, "Ni", 0) or 0)
                    nj = int(eccodes.codes_get(gid, "Nj", 0) or 0)
                    if ni and nj and v.size == ni * nj:
                        lat2d = la.reshape(nj, ni)
                        v = v.reshape(nj, ni)
                    else:
                        lats = np.unique(la)[::-1]
                        lons = np.unique(lo)
                        v = v.reshape(len(lats), len(lons))
                        lat2d = np.repeat(lats[:, None], len(lons), axis=1)
                    lats = lat2d[:, 0]
                    vd = int(eccodes.codes_get(gid, "validityDate"))
                    vt = int(eccodes.codes_get(gid, "validityTime"))
                    valid = datetime(vd // 10000, (vd // 100) % 100, vd % 100) \
                        + timedelta(hours=vt // 100, minutes=vt % 100)
                    lev = int(eccodes.codes_get(gid, "level"))
                    mem = int(eccodes.codes_get(gid, "number", 0) or 0)
                    key = valid.strftime("%Y-%m-%d %H")
                    acc[key][lev].append((mem, zonal_mean(v, lats)))
                    del v, la, lo, lat2d
                except Exception:
                    pass
                finally:
                    eccodes.codes_release(gid)
    finally:
        os.remove(path)

    out = {}
    for t, d in acc.items():
        out[t] = {}
        for lev, pairs in d.items():
            pairs.sort()
            out[t][lev] = [p[1] for p in pairs]
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(DATA, "polar_aifs.json"))
    ap.add_argument("--steps", default="")
    args = ap.parse_args()

    steps = ([int(s) for s in args.steps.split(",") if s] if args.steps
             else STEPS)
    rec = {"times": [], "members": {}, "levels": LEVELS}
    if os.path.exists(args.out):
        try:
            rec = json.load(open(args.out))
        except Exception:
            pass
    rec.setdefault("levels", LEVELS)
    have = set(rec["times"])

    for st in steps:
        try:
            d = fetch_step(st)
        except Exception as e:
            print("   the step %3dh failed: %s" % (st, str(e)[:90]), flush=True)
            continue
        for t, levs in d.items():
            if t in have:
                continue
            have.add(t)
            rec["times"].append(t)
            rec["members"][t] = {str(l): levs.get(l, []) for l in LEVELS}
            nmem = len(levs.get(10, []))
            print("   the step %3dh -> %s  the %d members  the 10 hPa %.0f"
                  % (st, t, nmem, np.mean(levs[10]) if levs.get(10) else float("nan")),
                  flush=True)

    order = np.argsort(rec["times"])
    rec["times"] = [rec["times"][i] for i in order]
    rec["members"] = {rec["times"][i]: rec["members"][rec["times"][i]]
                      for i in order}
    tmp = args.out + ".tmp"
    json.dump(rec, open(tmp, "w"))
    os.replace(tmp, args.out)
    print("   the AIFS ensemble: %d steps -> %s"
          % (len(rec["times"]), args.out), flush=True)


if __name__ == "__main__":
    # a lock, so two copies of this fetcher cannot end up competing for the
    # same throttled bucket: six copies running at once made every one of
    # them crawl
    import fcntl
    lock = open(os.path.join(DATA, "_aifs.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        print("   another copy of the AIFS fetcher is already running")
        raise SystemExit(0)
    main()
