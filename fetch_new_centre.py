"""Fetch everything a newly added C3S centre needs, one request at a time.

A probe would waste a queue slot, and the CDS queue is the scarcest thing
here, so this goes straight for the data: the monthly snowfall, the model's
own hindcast climate, the monthly 10 hPa wind and the sea-surface
temperature for the plume.

    python3 fetch_new_centre.py <tag> <name> <centre> <system> [init]
"""
import os
import sys
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cds_direct                                       # noqa: E402

DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
STATE = os.path.join(DATA, "models_fetched.json")
LEADS = 6


def get(c, dataset, req, target):
    """Submit, wait and download, retrying while the queue is full."""
    for attempt in range(240):
        try:
            jid = c.submit(dataset, req)
        except Exception:
            print("     queue full - waiting for a slot", flush=True)
            time.sleep(45)
            continue
        print("     submitted %s" % jid[:12], flush=True)
        for _ in range(400):
            s = c.job_status(jid)
            if s == "successful":
                c.download_job(jid, target)
                print("     saved %s (%.1f MB)"
                      % (os.path.basename(target),
                         os.path.getsize(target) / 1e6), flush=True)
                return True
            if s in ("failed", "rejected", "gone", "dismissed"):
                detail = c._job_detail(jid)
                if "Maximum number queued" in detail:
                    print("     queue full - re-submitting", flush=True)
                    break
                print("     job %s - %s"
                      % (s, detail[:200].replace("\n", " ")), flush=True)
                return False
            time.sleep(30)
        time.sleep(45)
    print("     no queue slot in 3 h - giving up", flush=True)
    return False


def watch(c, tag, name, centre, system, jid, init):
    """Watch a job that is already queued; save it and flip the init.

    The CDS detail endpoint answers 404 intermittently while a job record is
    re-indexed, so a "gone" is confirmed against the job list before the run
    is called a failure.
    """
    d = os.path.join(MDIR, tag)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "snowfall_monthly.grib")
    for _ in range(480):
        s = c.job_status(jid)
        if s == "successful":
            c.download_job(jid, out)
            print("  %s: saved %s (%.1f MB)"
                  % (tag, os.path.basename(out), os.path.getsize(out) / 1e6),
                  flush=True)
            st = json.load(open(STATE)) if os.path.exists(STATE) else {}
            rec = st.get(tag, {})
            rec.update({"name": name, "centre": centre, "system": system,
                        "init": init, "probe_date": time.strftime("%Y-%m-%d")})
            st[tag] = rec
            json.dump(st, open(STATE, "w"), indent=1)
            print("  %s is on the %s init" % (tag, init), flush=True)
            return True
        if s == "gone":
            live = {j.get("jobID") for j in
                    c._request("GET", "/retrieve/v1/jobs?limit=200")
                    .json().get("jobs", [])}
            if jid in live:
                print("  %s: the job is still queued - continuing" % tag,
                      flush=True)
                time.sleep(30)
                continue
            print("  %s: the job is gone" % tag, flush=True)
            return False
        if s in ("failed", "rejected", "dismissed"):
            print("  %s: job %s - %s"
                  % (tag, s, c._job_detail(jid)[:180].replace("\n", " ")),
                  flush=True)
            return False
        time.sleep(30)
    print("  %s: gave up waiting" % tag, flush=True)
    return False


def main():
    if sys.argv[1] == "--watch":
        # fetch_new_centre.py --watch <job-id> <tag> <name> <centre> <system> [init]
        jid, tag, name, centre, system = sys.argv[2:7]
        init = sys.argv[7] if len(sys.argv) > 7 else "2026-11"
        c = cds_direct.CDSDirect()
        print("== %s: watching %s" % (tag, jid[:12]), flush=True)
        watch(c, tag, name, centre, system, jid, init)
        return
    tag, name, centre, system = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    init = sys.argv[5] if len(sys.argv) > 5 else "2026-11"
    # which fields to fetch: snow, sst, clim, u10 (all of them by default)
    want = (sys.argv[6] if len(sys.argv) > 6 else "snow,sst,clim,u10").split(",")
    want = [w.strip() for w in want if w.strip()]
    d = os.path.join(MDIR, tag)
    os.makedirs(d, exist_ok=True)
    y, m = int(init[:4]), int(init[-2:])
    c = cds_direct.CDSDirect()

    # 1. the monthly snowfall
    print("== %s (%s:%s) init %s" % (tag, centre, system, init), flush=True)
    fg = os.path.join(d, "snowfall_monthly.grib")
    # the file may still be the PREVIOUS init's data - a file that exists is
    # not proof that it belongs to the run being fetched
    have_init = ""
    sp = os.path.join(DATA, "models_fetched.json")
    if os.path.exists(sp):
        have_init = json.load(open(sp)).get(tag, {}).get("init", "")
    stale = bool(have_init) and have_init != init
    if "snow" in want and (not os.path.exists(fg) or stale):
        print("   snowfall monthly_mean", flush=True)
        get(c, "seasonal-monthly-single-levels",
            {"originating_centre": centre, "system": system,
             "variable": "snowfall", "product_type": "monthly_mean",
             "year": str(y), "month": "%02d" % m,
             "leadtime_month": [str(k) for k in range(1, LEADS + 1)],
             "data_format": "grib"}, fg)

    # 4. the sea-surface temperature for the ENSO plume
    sg = os.path.join(d, "sst_monthly.grib")
    if "sst" in want and not os.path.exists(sg):
        print("   sea_surface_temperature monthly_mean", flush=True)
        get(c, "seasonal-monthly-single-levels",
            {"originating_centre": centre, "system": system,
             "variable": "sea_surface_temperature", "product_type": "monthly_mean",
             "year": str(y), "month": "%02d" % m,
             "leadtime_month": [str(k) for k in range(1, LEADS + 1)],
             "data_format": "grib"}, sg)

    # 2. the model's own climate (the anomaly baseline; it does not change
    #    between inits)
    cg = os.path.join(d, "snowfall_hindcast.grib")
    if "clim" in want and not os.path.exists(cg):
        print("   snowfall hindcast_climate_mean", flush=True)
        get(c, "seasonal-monthly-single-levels",
            {"originating_centre": centre, "system": system,
             "variable": "snowfall", "product_type": "hindcast_climate_mean",
             "year": str(y), "month": "%02d" % m,
             "leadtime_month": [str(k) for k in range(1, LEADS + 1)],
             "data_format": "grib"}, cg)

    # 3. the monthly 10 hPa wind (the daily series comes from the chunked
    #    puller)
    ug = os.path.join(d, "u10_monthly.grib")
    if "u10" in want and not os.path.exists(ug):
        print("   u10 monthly_mean", flush=True)
        get(c, "seasonal-monthly-pressure-levels",
            {"originating_centre": centre, "system": system,
             "variable": "u_component_of_wind", "pressure_level": "10",
             "product_type": "monthly_mean", "year": str(y), "month": "%02d" % m,
             "leadtime_month": [str(k) for k in range(1, LEADS + 1)],
             "data_format": "grib"}, ug)

    # record the centre - but only once its forecast is really on disk,
    # otherwise the site would list a model whose panels cannot be drawn
    if not os.path.exists(fg):
        print("== %s: no forecast on disk yet - not recording the init"
              % tag, flush=True)
        return
    if have_init and have_init != init:
        # the file is still the old init's - do not claim the new init
        print("== %s: the forecast on disk is still the %s init - not "
              "recording %s" % (tag, have_init, init), flush=True)
        return
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    rec = st.get(tag, {})
    rec.update({"name": name, "centre": centre, "system": system,
                "init": init, "probe_date": time.strftime("%Y-%m-%d"),
                "done": True})
    st[tag] = rec
    json.dump(st, open(STATE, "w"), indent=1)
    print("== %s recorded (init %s)" % (tag, init), flush=True)


if __name__ == "__main__":
    main()
