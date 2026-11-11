"""Fetch the snowfall for the lead months the monthly dataset does not carry.

The C3S "monthly statistics" dataset stops at lead month 6, but the systems
themselves run further - the ECMWF to 215 days (eight lead months), the UKMO
and the ECCC to 214/215 days (seven).  The extra months only exist in the
*original* (sub-daily) product, where every step carries its own
accumulation, so a request over the tail of the run returns the accumulation
day by day and the decoder adds it up into calendar months.

    python3 fetch_snow_ext.py [--only tag,tag]
"""
import os
import sys
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cds_direct                                       # noqa: E402
from fetch_snow_daily import read_snow, save_npz          # noqa: E402

DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
STATE = os.path.join(DATA, "models_fetched.json")

# the tail of the run: lead month 7 starts at day 181 (1 May 2027 for a
# 1 November init) and the longest published range ends on day 215
DAY0 = 181
DAY1 = 215
STEP = 12                       # the sub-daily product is 12-hourly

# (tag, centre, system) - the C3S systems that publish more than six months
CENTRES = [
    ("ecmwf-seas5",     "ecmwf", "51"),
    ("ukmo-gloseas6",   "ukmo",  "610"),
    ("eccc-canesm5",    "eccc",  "4"),
    ("eccc-gem5",       "eccc",  "5"),
    ("meteo-france-s9", "meteo_france", "9"),
    ("cmcc-sps4",       "cmcc",  "4"),
    ("dwd-gcfs2",       "dwd",   "22"),
    ("jma-jra3",        "jma",   "4"),
    ("bom-access-s2",   "bom",   "2"),
]


def main():
    only = ""
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    want = [x for x in only.split(",") if x]
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    c = cds_direct.CDSDirect()
    for tag, centre, system in CENTRES:
        if want and tag not in want:
            continue
        d = os.path.join(MDIR, tag)
        if not os.path.isdir(d):
            continue
        npz = os.path.join(d, "snowfall_ext.npz")
        if os.path.exists(npz):
            print("  %s: have the extended months" % tag, flush=True)
            continue
        init = state.get(tag, {}).get("init")
        if not init:
            print("  %s: no init known - skipping" % tag, flush=True)
            continue
        y, m = int(init[:4]), int(init[-2:])
        hours = [str(h) for h in range(DAY0 * 24, DAY1 * 24 + 1, STEP)]
        req = {"originating_centre": centre, "system": system,
               "variable": "snowfall", "year": str(y), "month": "%02d" % m,
               "day": "01", "leadtime_hour": hours, "data_format": "grib"}
        grib = os.path.join(d, "snowfall_ext.grib")
        print("  %s: requesting the snowfall for days %d-%d (%s:%s)"
              % (tag, DAY0, DAY1, centre, system), flush=True)
        jid = None
        for attempt in range(120):
            try:
                jid = c.submit("seasonal-original-single-levels", req)
                break
            except Exception as e:
                print("     queue full - waiting for a slot", flush=True)
                time.sleep(45)
        if not jid:
            print("  %s: no queue slot - skipping" % tag, flush=True)
            continue
        print("     submitted %s" % jid[:12], flush=True)
        ok = False
        for _ in range(400):
            s = c.job_status(jid)
            if s == "successful":
                c.download_job(jid, grib)
                ok = True
                break
            if s in ("failed", "rejected", "gone", "dismissed"):
                detail = c._job_detail(jid)
                if "Maximum number queued" in detail:
                    print("     queue full - re-submitting", flush=True)
                    break
                print("     job %s - %s" % (s, detail[:160].replace("\n", " ")),
                      flush=True)
                break
            time.sleep(30)
        if not ok:
            continue
        months, members, acc, glat, glon, ndays = read_snow(grib)
        if not months or acc is None:
            print("  %s: no data past the monthly product's 6 months" % tag,
                  flush=True)
            os.remove(grib)
            continue
        save_npz(npz, months, members, acc, glat, glon,
                 meta=dict(tag=tag, init=init, kind="extended"), ndays=ndays)
        print("  %s: %d extended month(s) %s (%s days each) -> %s"
              % (tag, len(months), [ "%04d-%02d" % m for m in months ],
                 ndays, os.path.basename(npz)), flush=True)


if __name__ == "__main__":
    main()
