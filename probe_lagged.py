"""Probe the C3S sub-daily seasonal product for a LAGGED ensemble.

The monthly product for the UKMO, the JMA and the BoM turned out to be a
*lagged* ensemble: the members are not all started on the same day.  The UKMO
serves 62 members started two per day on 31 consecutive days, the JMA 155
started five per day, the BoM 99 started eleven per day on nine days - and
every member's lead time is shifted so that all of them are valid at the
same time.

If the sub-daily product keeps that layout, then the request's `day` input
selects the members STARTED ON THAT DAY, which is why `day=['01']` returns
only two members for the UKMO and five for the JMA.

This asks the archive for a handful of start days and prints, for every
member, its own start date, its step and its validity - so the structure can
be read off the raw GRIB rather than assumed.

    python3 probe_lagged.py ukmo 610 11 01,02,03 12,36,60
    python3 probe_lagged.py bom   2 11 01,02,03 12
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cds_direct import CDSDirect, QueueFull, NoData   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATASET = "seasonal-original-pressure-levels"
POLAR = [90, -180, 60, 180]          # north, west, south, east


def account_live(c):
    """How many jobs the account holds right now (the gate is account-wide)."""
    n = 0
    try:
        for j in c.live_jobs(limit=60):
            if j.get("status") in ("accepted", "running", "queued"):
                n += 1
    except Exception:
        return None
    return n


def wait_for_slot(c, want=2, verbose=True):
    """Block until the account holds fewer than `want` live jobs."""
    while True:
        n = account_live(c)
        if n is None:
            return
        if n < want:
            if verbose:
                print("  %d live job(s) on the account - submitting" % n,
                      flush=True)
            return
        if verbose:
            print("  %d live job(s) on the account - waiting" % n, flush=True)
        time.sleep(30)


def read_members(path):
    """-> [(member, start date, step, validity, level)] for every message."""
    import eccodes
    out = []
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                def g(k, d=None):
                    try:
                        v = eccodes.codes_get(gid, k)
                    except Exception:
                        return d
                    if isinstance(v, (bytes, bytearray)):
                        v = v.decode()
                    return v
                out.append((g("number"), g("perturbationNumber"), g("dataDate"),
                            g("dataTime"), g("step"), g("validityDate"),
                            g("validityTime"), g("level"), g("typeOfLevel"),
                            g("centre")))
            finally:
                eccodes.codes_release(gid)
    return out


def dump(rows, tag):
    from collections import defaultdict
    print("\n=== %s: %d messages" % (tag, len(rows)))
    if not rows:
        return
    by = defaultdict(list)
    for r in rows:
        by[r[0]].append(r)
    print("  distinct member numbers: %d  -> %s"
          % (len(by), sorted(int(k) for k in by)[:20]))
    print("  %-5s %-5s %-9s %-6s %-5s %-9s %-6s %-6s %-9s %s"
          % ("num", "pn", "dataDate", "dataTm", "step", "validDate",
             "validTm", "level", "type", "centre"))
    for m in sorted(by, key=lambda x: int(x)):
        for r in by[m][:6]:
            print("  %-5s %-5s %-9s %-6s %-5s %-9s %-6s %-6s %-9s %s" % r)
        if len(by[m]) > 6:
            print("    ... %d more records for this member" % (len(by[m]) - 6))


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "ukmo-gloseas6"
    system = sys.argv[2] if len(sys.argv) > 2 else "610"
    month = sys.argv[3] if len(sys.argv) > 3 else "11"
    days = (sys.argv[4] if len(sys.argv) > 4 else "01,02,03").split(",")
    leads = (sys.argv[5] if len(sys.argv) > 5 else "12,36,60").split(",")
    year = sys.argv[6] if len(sys.argv) > 6 else "2026"
    centre = tag if tag in ("bom", "dwd", "jma", "cmcc", "eccc", "ncep",
                            "ukmo", "ecmwf", "meteo_france") else \
        {"ukmo-gloseas6": "ukmo", "jma-jra3": "jma",
         "bom-access-s2": "bom"}.get(tag, tag)

    req = {"originating_centre": centre, "system": str(system),
           "variable": ["u_component_of_wind"], "pressure_level": ["10"],
           "year": [year], "month": [month], "day": days,
           "leadtime_hour": leads, "area": POLAR, "data_format": "grib"}
    print("the request:", req, flush=True)

    c = CDSDirect()
    wait_for_slot(c)
    try:
        jid = c.submit(DATASET, req)
    except QueueFull as e:
        print("!! the queue refused it:", str(e)[:200], flush=True)
        return
    except NoData as e:
        print("!! no data:", str(e)[:400], flush=True)
        return
    print("submitted %s" % jid, flush=True)

    s = None
    for _ in range(240):
        time.sleep(15)
        s = c.job_status(jid)
        if s in ("successful", "completed", "failed", "rejected", "dismissed",
                 "gone"):
            break
    print("the job is %s" % s, flush=True)
    if s not in ("successful", "completed"):
        print("the traceback:", c._job_detail(jid)[:600], flush=True)
        return
    out = os.path.join(HERE, "data", "probe_lagged_%s.grib" % tag)
    c.download_job(jid, out)
    print("downloaded %.1f MB -> %s" % (os.path.getsize(out) / 1e6, out),
          flush=True)
    dump(read_members(out), tag)


if __name__ == "__main__":
    main()
