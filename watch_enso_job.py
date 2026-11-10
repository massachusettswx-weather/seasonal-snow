"""Finish the Meteo-France SST fetch.

Its request was refused while an earlier one was still queued, so this
watches that older job, downloads it when it lands and turns it into
data/models/meteo-france-s9/enso.json.  If the old job dies, a fresh request
is submitted (waiting for a free queue slot).

    python3 watch_enso_job.py <tag> <job-id> [centre] [system] [leads]
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cds_direct                                       # noqa: E402
from fetch_enso import indices_from_grib, save          # noqa: E402

DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")


def request(centre, system, leads, init):
    y, m = int(init[:4]), int(init[-2:])
    return {"originating_centre": centre, "system": system,
            "variable": "sea_surface_temperature",
            "year": y, "month": m,
            "leadtime_month": [str(k) for k in range(1, leads + 1)],
            "data_format": "grib"}


def main():
    tag = sys.argv[1]
    jid = sys.argv[2]
    centre = sys.argv[3] if len(sys.argv) > 3 else "meteo_france"
    system = sys.argv[4] if len(sys.argv) > 4 else "9"
    leads = int(sys.argv[5]) if len(sys.argv) > 5 else 6
    c = cds_direct.CDSDirect()
    d = os.path.join(MDIR, tag)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "sst_monthly.grib")
    if os.path.exists(os.path.join(d, "enso.json")):
        print("%s already has an enso.json" % tag, flush=True)
        return

    st = {}
    p = os.path.join(DATA, "models_fetched.json")
    if os.path.exists(p):
        import json
        st = json.load(open(p))
    init = st.get(tag, {}).get("init") or "2026-10"

    # 1. the job that is already queued
    for i in range(480):                     # 4 h
        try:
            s = c.job_status(jid)
        except Exception as e:
            print("poll error: %s" % str(e)[:80], flush=True)
            s = "?"
        if s == "successful":
            print("job %s succeeded - downloading" % jid[:12], flush=True)
            c.download_job(jid, out)
            got = indices_from_grib(out)
            if got:
                idx, trop = got
                save(tag, idx, trop, "c3s-sst")
                print("wrote %s/enso.json" % tag, flush=True)
                return
            print("could not read the GRIB", flush=True)
            return
        if s in ("failed", "rejected", "gone", "dismissed"):
            print("job %s -> %s" % (jid[:12], s), flush=True)
            break
        time.sleep(30)
    else:
        print("gave up on the old job", flush=True)
        return

    # 2. a fresh request, waiting for a free slot
    for i in range(60):
        try:
            c.retrieve("seasonal-monthly-single-levels",
                       request(centre, system, leads, init), out,
                       max_wait_s=7200)
            print("fresh request done", flush=True)
            got = indices_from_grib(out)
            if got:
                idx, trop = got
                save(tag, idx, trop, "c3s-sst")
                print("wrote %s/enso.json" % tag, flush=True)
            return
        except cds_direct.QueueFull:
            print("queue full - waiting", flush=True)
            time.sleep(180)
        except Exception as e:
            print("request failed: %s" % str(e)[:200], flush=True)
            time.sleep(120)


if __name__ == "__main__":
    main()
