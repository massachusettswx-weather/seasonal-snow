"""Fetch the seasonal systems that are actually released, with their own init
month and their own hindcast climate.

What the CDS told us (measured, 7 Nov 2026):
  * every non-ECMWF C3S contribution rejects the 1 Nov 2026 init with
    "Restricted access to current C3S seasonal forecast non-ECMWF
    contribution" - those runs are simply not released yet;
  * the 1 Oct 2026 init serves UKMO 610, ECCC 4, ECCC 5, CMCC 4, DWD 22 and
    METFR 9;
  * NCEP 2 and BOM 2 served neither of those months;
  * ECMWF 51 serves the 1 Nov 2026 init.

So this script does NOT hard-code an init: it probes each system backwards
month by month and takes the FRESHEST init that actually returns data.  When
the C3S release the November runs (expected 10 Nov 2026), re-running this
script picks them up with no code change.

For each system, at its own init:
  * snowfall, monthly_mean            -> the forecast field
  * snowfall, hindcast_climate_mean   -> that model's own climate (baseline)
  * u_component_of_wind at 10 hPa      -> the SPV members

One request at a time: the CDS queue limit is account-wide.

usage:  python3 fetch_models.py [--include-late]
"""
import os, sys, json, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
os.makedirs(MDIR, exist_ok=True)

KEY = [l.split(":", 1)[1].strip() for l in open(os.path.join(HERE, ".cdsapirc"))
       if l.strip().startswith("key:")][0]
API = "https://cds.climate.copernicus.eu/api"
S = requests.Session()
S.headers.update({"PRIVATE-TOKEN": KEY})

# tag, display name, centre, system, expected lead months
SYSTEMS = [
    ("ecmwf-seas5",    "ECMWF SEAS5",          "ecmwf", "51", 7),
    ("ukmo-gloseas6",  "UKMO GloSeas6-GC5.1",  "ukmo",  "610", 6),
    ("eccc-canesm5",   "ECCC CanESM5.1p1bc",   "eccc",  "4",  7),
    ("eccc-gem5",      "ECCC GEM5.2-NEMO",     "eccc",  "5",  7),
    ("cmcc-sps4",      "CMCC SPS4",            "cmcc",  "4",  7),
    ("dwd-gcfs2",      "DWD GCFS2.2",          "dwd",   "22", 7),
    ("meteo-france-s9","METFR System 9",       "meteo_france", "9", 6),
    # NCEP and BOM are in the C3S catalogue but are not site models - NOAA is
    # read from NOAA itself - so they are not fetched.
]

# probe newest first: Nov 2026, then Oct, Sep, ... back a year
MONTHS = []
for yr in (2026, 2025):
    for mo in range(12, 0, -1):
        MONTHS.append((str(yr), "%02d" % mo))
MONTHS = MONTHS[:14]

GC = "grib"


def tb(jid):
    for _ in range(3):
        try:
            r = S.get(API + "/retrieve/v1/jobs?limit=30", timeout=60).json()
            for j in r.get("jobs", []):
                if j.get("jobID") == jid:
                    return ((j.get("metadata", {}).get("results", {}) or {})
                            .get("traceback", "") or "")
        except Exception:
            pass
        time.sleep(4)
    return ""


def retrieve(ds, req, out, tries=4):
    """-> True on success.  Queue-limit rejections are retried with a pause."""
    for attempt in range(tries):
        try:
            r = S.post("%s/retrieve/v1/processes/%s/execute" % (API, ds),
                       json={"inputs": req}, timeout=180)
        except Exception as e:
            print("      http error: %s" % str(e)[:120], flush=True)
            time.sleep(20)
            continue
        if r.status_code in (400, 422):
            txt = r.text
            if "Maximum number queued" in txt:
                print("      queue full -> pause 120s", flush=True)
                time.sleep(120)
                continue
            print("      rejected: %s" % txt[:220], flush=True)
            return False
        if r.status_code not in (200, 201):
            print("      HTTP %d %s" % (r.status_code, r.text[:150]), flush=True)
            time.sleep(20)
            continue
        jid = r.json().get("jobID")
        t0 = time.time()
        while time.time() - t0 < 14400:
            time.sleep(12)
            try:
                st = S.get(API + "/retrieve/v1/jobs/" + jid, timeout=60).json().get("status")
            except Exception:
                continue
            if st == "successful":
                rr = S.get(API + "/retrieve/v1/jobs/%s/results" % jid, timeout=120)
                try:
                    link = rr.json()["asset"]["value"]["href"]
                except Exception:
                    print("      no result link", flush=True)
                    return False
                dr = S.get(link, timeout=900)
                if dr.status_code >= 400:
                    print("      download HTTP %d" % dr.status_code, flush=True)
                    time.sleep(15)
                    continue
                with open(out, "wb") as f:
                    f.write(dr.content)
                return True
            if st in ("rejected", "failed"):
                t = tb(jid)
                if "Maximum number queued" in t:
                    print("      queue full -> pause 120s", flush=True)
                    time.sleep(120)
                    break
                print("      job %s: %s" % (st, (t[-200:] or "")), flush=True)
                return False
        else:
            print("      timed out waiting", flush=True)
            time.sleep(20)
    return False


def grib_info(path):
    try:
        import eccodes
        n = 0; steps = set(); lats = set(); lons = set()
        with open(path, "rb") as f:
            while True:
                try:
                    gid = eccodes.codes_grib_new_from_file(f)
                except Exception:
                    break
                if gid is None:
                    break
                n += 1
                try:
                    steps.add(int(eccodes.codes_get(gid, "step")))
                    lats.add(float(eccodes.codes_get(gid, "latitudeOfLastGridPointInDegrees")))
                    lons.add(float(eccodes.codes_get(gid, "longitudeOfLastGridPointInDegrees")))
                except Exception:
                    pass
                eccodes.codes_release(gid)
        grid = None
        if len(lats) > 1 and len(lons) > 1:
            grid = [round(abs(lats[0] - lats[1]), 4), round(abs(lons[0] - lons[1]), 4)]
        return {"fields": n, "steps": sorted(steps)[:5], "grid": grid}
    except Exception as e:
        return {"error": str(e)[:120]}


def probe_init(centre, system, rec=None):
    """-> (year, month) of the freshest released init, or None.

    A centre probed earlier today is not probed again: the CDS queue is slow
    and the answer cannot change within the day.  Clearing probe_date in
    data/models_fetched.json forces a fresh probe.
    """
    today = time.strftime("%Y-%m-%d")
    if rec and rec.get("probe_date") == today and rec.get("init"):
        y, m = rec["init"].split("-")
        print("   probe cache: %s (probed today)" % rec["init"], flush=True)
        return int(y), int(m)
    for (y, m) in MONTHS:
        req = {"originating_centre": centre, "system": system,
               "variable": "snowfall", "product_type": "monthly_mean",
               "year": y, "month": m, "leadtime_month": ["1"],
               "data_format": GC}
        fn = "/tmp/probe_init.grib"
        if retrieve("seasonal-monthly-single-levels", req, fn, tries=2):
            print("   freshest init: %s-%s" % (y, m), flush=True)
            return y, m
        time.sleep(3)
    return None


def main():
    p = os.path.join(DATA, "models_fetched.json")
    state = json.load(open(p)) if os.path.exists(p) else {}

    for tag, name, centre, system, leads in SYSTEMS:
        d = os.path.join(MDIR, tag)
        os.makedirs(d, exist_ok=True)
        rec = state.get(tag, {})
        rec.update({"name": name, "centre": centre, "system": system,
                    "expected_leads": leads})

        # keep the init we already have, unless we can find a fresher one
        have = rec.get("init")
        print("== %-16s %s:%s  (current init %s)" % (tag, centre, system, have), flush=True)
        fresh = probe_init(centre, system, rec)
        if fresh is None:
            print("   no released init found - skipping", flush=True)
            rec["done"] = False
            state[tag] = rec
            json.dump(state, open(p, "w"), indent=1)
            continue
        y, m = fresh
        if have == "%s-%s" % (y, m) and rec.get("snow"):
            print("   already at the freshest init", flush=True)
            state[tag] = rec
            json.dump(state, open(p, "w"), indent=1)
            continue
        init = "%s-%s" % (y, m)
        rec["init"] = init
        rec["probe_date"] = time.strftime("%Y-%m-%d")
        rec.pop("snow", None); rec.pop("clim", None)
        rec.pop("u10", None); rec.pop("u10m", None)
        # the monthly forecast may already have been fetched for this init
        # (the November fetch runs ahead of this script) - keep it, the
        # hindcast climate is the model's own climate and does not change
        # from one init to the next, but the 10 hPa wind does.
        keep_forecast = os.path.exists(os.path.join(d, "snowfall_monthly.grib"))
        for f in ("u10_daily.grib", "u10_monthly.grib"):
            fp = os.path.join(d, f)
            if os.path.exists(fp):
                os.remove(fp)

        # 1. the forecast field
        fg = os.path.join(d, "snowfall_monthly.grib")
        req = {"originating_centre": centre, "system": system,
               "variable": "snowfall", "product_type": "monthly_mean",
               "year": y, "month": m,
               "leadtime_month": [str(k) for k in range(1, leads + 1)],
               "data_format": GC}
        print("   snowfall monthly_mean %s" % init, flush=True)
        if keep_forecast:
            rec["snow"] = grib_info(fg)
            print("   OK (the forecast for %s was already fetched) %s"
                  % (init, rec["snow"]), flush=True)
        elif retrieve("seasonal-monthly-single-levels", req, fg):
            rec["snow"] = grib_info(fg)
            print("   OK %s" % rec["snow"], flush=True)
        else:
            print("   FAILED", flush=True)
            state[tag] = rec
            json.dump(state, open(p, "w"), indent=1)
            continue

        # 2. that model's own hindcast climate
        cg = os.path.join(d, "snowfall_hindcast.grib")
        req = {"originating_centre": centre, "system": system,
               "variable": "snowfall", "product_type": "hindcast_climate_mean",
               "year": y, "month": m,
               "leadtime_month": [str(k) for k in range(1, leads + 1)],
               "data_format": GC}
        print("   snowfall hindcast_climate_mean", flush=True)
        if os.path.exists(cg) and os.path.getsize(cg) > 10000:
            rec["clim"] = grib_info(cg)
            print("   OK (the model's own climate, unchanged between inits) %s"
                  % rec["clim"], flush=True)
        elif retrieve("seasonal-monthly-single-levels", req, cg):
            rec["clim"] = grib_info(cg)
            print("   OK %s" % rec["clim"], flush=True)
        else:
            print("   FAILED (anomalies will be skipped for this model)", flush=True)

        # 3. the 10 hPa wind: daily where available, monthly otherwise
        ug = os.path.join(d, "u10_daily.grib")
        req = {"originating_centre": centre, "system": system,
               "variable": "u_component_of_wind", "pressure_level": "10",
               "year": y, "month": m,
               "leadtime_hour": [str(h) for h in range(12, 24 * 210, 24)],
               "data_format": GC}
        # the daily 10 hPa wind comes from the chunked puller
        # (fetch_models_daily.py): one job per 72 days, which the CDS queue
        # accepts reliably - a single 210-step request is refused as too big
        print("   u10 daily -> chunked puller", flush=True)
        mg = os.path.join(d, "u10_monthly.grib")
        req = {"originating_centre": centre, "system": system,
               "variable": "u_component_of_wind", "pressure_level": "10",
               "product_type": "monthly_mean", "year": y, "month": m,
               "leadtime_month": [str(k) for k in range(1, leads + 1)],
               "data_format": GC}
        print("   u10 monthly_mean", flush=True)
        if retrieve("seasonal-monthly-pressure-levels", req, mg, tries=3):
            rec["u10m"] = grib_info(mg)
            print("   OK %s" % rec["u10m"], flush=True)
        else:
            print("   FAILED", flush=True)

        rec["done"] = True
        state[tag] = rec
        json.dump(state, open(p, "w"), indent=1)
        time.sleep(4)

    json.dump(state, open(p, "w"), indent=1)
    print("\n=== summary ===")
    for tag, r in state.items():
        print("  %-16s init=%-8s snow=%-5s clim=%-5s u10m=%s"
              % (tag, r.get("init"), bool(r.get("snow")), bool(r.get("clim")),
                 bool(r.get("u10m"))))


if __name__ == "__main__":
    main()
