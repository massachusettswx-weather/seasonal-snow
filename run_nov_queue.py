"""Work the C3S November queue one request at a time.

The CDS will only admit a request when the account's MARS queue has room,
and it admits them for a window that can be as short as a minute before the
job is purged.  Several submitters competing for the same slots is what made
the queue unusable: every one of them burned a slot and lost it again.

So this runner keeps exactly ONE request in flight and walks a list in
priority order, re-submitting until the job actually completes:

  1. ECCC CanESM5 November snowfall   - moves a centre onto the November init
  2. JMA November snowfall            - a new centre for the site
  3. BOM November snowfall            - a new centre for the site
  4. ECCC GEM5.2 November snowfall    - the other ECCC centre
  5. JMA sea-surface temperature      - the ENSO plume for the new centre
  6. JMA hindcast climate + 10 hPa u  - the anomalies and the wind panel

    python3 run_nov_queue.py [--only step,step] [--dry-run]
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

# (step, tag, name, centre, system, kind, fields)
STEPS = [
    ("bom-snow", "bom-access-s2", "BOM ACCESS-S2", "bom", "2", "snow", ["snow"]),
    ("eccc-can", "eccc-canesm5", "ECCC CanESM5.1p1bc", "eccc", "4", "snow", ["snow"]),
    ("jma-snow", "jma-jra3", "JMA JRA3-25", "jma", "7", "snow", ["snow"]),
    ("eccc-gem", "eccc-gem5", "ECCC GEM5.2-NEMO", "eccc", "5", "snow", ["snow"]),
    ("jma-sst", "jma-jra3", "JMA JRA3-25", "jma", "7", "sst", ["sst"]),
    ("jma-rest", "jma-jra3", "JMA JRA3-25", "jma", "7", "clim+u10", ["clim", "u10"]),
    ("ecmwf-ext", "ecmwf-seas5", "ECMWF SEAS5", "ecmwf", "51", "ext", ["ext"]),
    ("ukmo-ext", "ukmo-gloseas6", "UKMO GloSeas6-GC5.1", "ukmo", "610", "ext", ["ext"]),
]

# what each kind needs from the CDS
REQ = {
    "snow": ("seasonal-monthly-single-levels",
             {"variable": "snowfall", "product_type": "monthly_mean",
              "leadtime_month": [str(k) for k in range(1, 7)]}),
    "sst": ("seasonal-monthly-single-levels",
            {"variable": "sea_surface_temperature", "product_type": "monthly_mean",
             "leadtime_month": [str(k) for k in range(1, 7)]}),
    "clim": ("seasonal-monthly-single-levels",
             {"variable": "snowfall", "product_type": "hindcast_climate_mean",
              "leadtime_month": [str(k) for k in range(1, 7)]}),
    "u10": ("seasonal-monthly-pressure-levels",
            {"variable": "u_component_of_wind", "pressure_level": "10",
             "product_type": "monthly_mean",
             "leadtime_month": [str(k) for k in range(1, 7)]}),
    # the lead months past the sixth only exist in the sub-daily product,
    # where every step carries its own accumulation
    "ext": ("seasonal-original-single-levels",
            {"variable": "snowfall", "day": "01",
             "leadtime_hour": [str(h) for h in range(181 * 24, 216 * 24, 12)]}),
}


def target_for(tag, kind):
    if kind == "snow":
        return os.path.join(MDIR, tag, "snowfall_monthly.grib")
    if kind == "sst":
        return os.path.join(MDIR, tag, "sst_monthly.grib")
    if kind == "clim":
        return os.path.join(MDIR, tag, "snowfall_hindcast.grib")
    if kind == "ext":
        return os.path.join(MDIR, tag, "snowfall_ext.grib")
    return os.path.join(MDIR, tag, "u10_monthly.grib")


def live_jobs(c):
    return {j.get("jobID") for j in
            c._request("GET", "/retrieve/v1/jobs?limit=200").json().get("jobs", [])
            if j.get("status") in ("accepted", "running", "queued")}


def record_init(tag, name, centre, system, init):
    p = os.path.join(DATA, "models_fetched.json")
    st = json.load(open(p)) if os.path.exists(p) else {}
    rec = st.get(tag, {})
    rec.update({"name": name, "centre": centre, "system": system,
                "init": init, "probe_date": time.strftime("%Y-%m-%d")})
    st[tag] = rec
    json.dump(st, open(p, "w"), indent=1)
    print("   %s is on the %s init" % (tag, init), flush=True)


def run_step(c, step, tag, name, centre, system, kind, fields, dry=False):
    """One request at a time: submit, wait for it to COMPLETE, download."""
    init = "2026-11"
    # a file that exists is not proof that it belongs to this run: the
    # centre's previous init's file is stale and has to be re-fetched
    sp = os.path.join(DATA, "models_fetched.json")
    have_init = ""
    if os.path.exists(sp):
        have_init = json.load(open(sp)).get(tag, {}).get("init", "")
    stale = bool(have_init) and have_init != init
    for f in fields:
        out = target_for(tag, f)
        if os.path.exists(out) and os.path.getsize(out) > 10000 and not stale:
            print("   %s/%s: already on disk" % (tag, f), flush=True)
            continue
        # remember what was there: only a FRESH file counts as fetched
        before = os.path.getmtime(out) if os.path.exists(out) else 0
        dataset, extra = REQ[f]
        req = {"originating_centre": centre, "system": system,
               "year": "2026", "month": "11", "data_format": "grib"}
        req.update(extra)
        for attempt in range(60):
            try:
                jid = c.submit(dataset, req)
            except Exception as e:
                print("   %s/%s: refused (%s) - waiting"
                      % (tag, f, str(e)[:60]), flush=True)
                time.sleep(60)
                continue
            print("   %s/%s: submitted %s (attempt %d)"
                  % (tag, f, jid[:12], attempt + 1), flush=True)
            # the job is admitted for a window that can be short; it has to
            # actually complete, so keep it and wait
            for _ in range(400):
                s = c.job_status(jid)
                if s == "successful":
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    c.download_job(jid, out)
                    print("   %s/%s: saved %s (%.1f MB)"
                          % (tag, f, os.path.basename(out),
                             os.path.getsize(out) / 1e6), flush=True)
                    if f == "ext":
                        # the renderer reads the decoded months, not the GRIB
                        from fetch_snow_daily import read_snow, save_npz
                        months, members, acc, glat, glon = read_snow(out)
                        if months and acc is not None:
                            save_npz(out.replace(".grib", ".npz"), months,
                                     members, acc, glat, glon,
                                     meta=dict(tag=tag, init=init, kind="extended"))
                            print("   %s/ext: %d extended month(s) %s"
                                  % (tag, len(months),
                                     [ "%04d-%02d" % m for m in months ]),
                                  flush=True)
                        else:
                            print("   %s/ext: nothing past the sixth month" % tag,
                                  flush=True)
                    break
                if s in ("failed", "rejected", "dismissed"):
                    print("   %s/%s: %s - resubmitting"
                          % (tag, f, s), flush=True)
                    break
                if s == "gone":
                    if jid in live_jobs(c):
                        time.sleep(30)
                        continue
                    print("   %s/%s: purged before it ran - resubmitting"
                          % (tag, f), flush=True)
                    break
                time.sleep(30)
            else:
                print("   %s/%s: gave up waiting" % (tag, f), flush=True)
                return False
            # only a FRESH file counts: the centre's previous init's file
            # is still on disk and would otherwise look like a success
            if (os.path.exists(out) and os.path.getsize(out) > 10000
                    and os.path.getmtime(out) > before):
                break
            time.sleep(20)
        else:
            print("   %s/%s: no luck" % (tag, f), flush=True)
            return False
    # the centre only counts as on the November init once ITS forecast has
    # been fetched for this init
    if kind != "ext" and os.path.exists(target_for(tag, "snow")) and not stale:
        record_init(tag, name, centre, system, init)
    return True


def main():
    dry = "--dry-run" in sys.argv
    only = []
    if "--only" in sys.argv:
        only = [x for x in sys.argv[sys.argv.index("--only") + 1].split(",") if x]
    c = cds_direct.CDSDirect()
    for step, tag, name, centre, system, kind, fields in STEPS:
        if only and step not in only:
            continue
        print("== %s (%s:%s) %s" % (tag, centre, system, kind), flush=True)
        if dry:
            print("   would fetch:", fields, flush=True)
            continue
        run_step(c, step, tag, name, centre, system, kind, fields, dry)


if __name__ == "__main__":
    main()
