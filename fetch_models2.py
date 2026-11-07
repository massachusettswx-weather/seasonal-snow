"""Fetch the seasonal systems that are actually available, with their own
init month and their own hindcast climate.

What the CDS told us (measured):
  * every non-ECMWF C3S contribution answers the 1 Nov 2026 init with
    "Restricted access to current C3S seasonal forecast non-ECMWF
    contribution" - those runs are not released yet;
  * six systems DO serve the 1 Oct 2026 init: UKMO 610, ECCC 4, ECCC 5,
    CMCC 4, DWD 22, METFR 9;
  * NCEP 2 and BOM 2 serve neither of those months;
  * ECMWF 51 serves the 1 Nov 2026 init.

For each system we pull, at its own init:
  * snowfall, monthly_mean            -> the forecast field
  * snowfall, hindcast_climate_mean   -> that model's own climate (baseline)
  * u_component_of_wind @ 10 hPa      -> the SPV members (daily)

One request at a time - the CDS queue limit is account-wide.
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

# tag, display name, centre, system, init year, init month, lead months
SYSTEMS = [
    ("ecmwf-seas5",    "ECMWF SEAS5",          "ecmwf", "51", "2026", "11", 7),
    ("ukmo-gloseas6",  "UKMO GloSeas6-GC5.1",  "ukmo",  "610", "2026", "10", 6),
    ("eccc-canesm5",   "ECCC CanESM5.1p1bc",   "eccc",  "4",  "2026", "10", 7),
    ("eccc-gem5",      "ECCC GEM5.2-NEMO",     "eccc",  "5",  "2026", "10", 7),
    ("cmcc-sps4",      "CMCC SPS4",            "cmcc",  "4",  "2026", "10", 7),
    ("dwd-gcfs2",      "DWD GCFS2.2",          "dwd",   "22", "2026", "10", 7),
    ("meteo-france-s9","METFR System 9",       "meteo_france", "9", "2026", "10", 6),
]

GC = "grib"
SLEEP = 4


def tb(jid):
    for _ in range(3):
        try:
            for j in S.get(API + "/retrieve/v1/jobs?limit=30", timeout=60).json().get("jobs", []):
                if j.get("jobID") == jid:
                    return ((j.get("metadata", {}).get("results", {}) or {})
                            .get("traceback", "") or "")
        except Exception:
            pass
        time.sleep(5)
    return ""


def retrieve(ds, req, out, tries=6):
    """-> True on success.  Returns False on any failure (logged)."""
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
                print("      queue full -> sleep 90s", flush=True)
                time.sleep(90)
                continue
            print("      rejected: %s" % txt[:200], flush=True)
            return False
        if r.status_code not in (200, 201):
            print("      HTTP %d %s" % (r.status_code, r.text[:150]), flush=True)
            time.sleep(20)
            continue
        jid = r.json().get("jobID")
        t0 = time.time()
        while time.time() - t0 < 2400:
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
                dr = S.get(link, timeout=600)
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
                    print("      queue full -> sleep 90s", flush=True)
                    time.sleep(90)
                    break
                print("      job %s: %s" % (st, (t[-220:] or "")), flush=True)
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
        return {"fields": n, "steps": sorted(steps)[:5], "grid": grid,
                "nlat": len(lats), "nlon": len(lons)}
    except Exception as e:
        return {"error": str(e)[:120]}


def main():
    p = os.path.join(DATA, "models_fetched.json")
    state = json.load(open(p)) if os.path.exists(p) else {}
    for tag, name, centre, system, y, m, leads in SYSTEMS:
        d = os.path.join(MDIR, tag)
        os.makedirs(d, exist_ok=True)
        rec = state.setdefault(tag, {})
        rec.update({"name": name, "centre": centre, "system": system,
                    "init": "%s-%s" % (y, m), "leads": leads})

        # 1. the forecast field
        fg = os.path.join(d, "snowfall_monthly.grib")
        if not os.path.exists(fg) or rec.get("snow") is None:
            req = {"originating_centre": centre, "system": system,
                   "variable": "snowfall", "product_type": "monthly_mean",
                   "year": y, "month": m,
                   "leadtime_month": [str(k) for k in range(1, leads + 1)],
                   "data_format": GC}
            print("[%s] snowfall monthly_mean %s-%s" % (tag, y, m), flush=True)
            if retrieve("seasonal-monthly-single-levels", req, fg):
                rec["snow"] = grib_info(fg)
                print("   OK %s" % rec["snow"], flush=True)
            else:
                print("   FAILED", flush=True)
                json.dump(state, open(p, "w"), indent=1)
                continue

        # 2. that model's own hindcast climate
        cg = os.path.join(d, "snowfall_hindcast.grib")
        if not os.path.exists(cg) or rec.get("clim") is None:
            req = {"originating_centre": centre, "system": system,
                   "variable": "snowfall", "product_type": "hindcast_climate_mean",
                   "year": y, "month": m,
                   "leadtime_month": [str(k) for k in range(1, leads + 1)],
                   "data_format": GC}
            print("[%s] snowfall hindcast_climate_mean" % tag, flush=True)
            if retrieve("seasonal-monthly-single-levels", req, cg):
                rec["clim"] = grib_info(cg)
                print("   OK %s" % rec["clim"], flush=True)
            else:
                print("   FAILED (will fall back to ERA5 baseline)", flush=True)

        # 3. the 10 hPa wind members.
        #    seasonal-original-pressure-levels gives daily values but only for
        #    the ECMWF contribution; the monthly pressure-levels dataset
        #    serves every centre, so we take monthly means from there and
        #    keep the daily ECMWF file when it works.
        ug = os.path.join(d, "u10_daily.grib")
        if not os.path.exists(ug) or rec.get("u10") is None:
            req = {"originating_centre": centre, "system": system,
                   "variable": "u_component_of_wind", "pressure_level": "10",
                   "year": y, "month": m,
                   "leadtime_hour": [str(h) for h in range(12, 24 * 210, 24)],
                   "data_format": GC}
            print("[%s] u10 daily" % tag, flush=True)
            if retrieve("seasonal-original-pressure-levels", req, ug):
                rec["u10"] = grib_info(ug)
                rec["u10_daily"] = True
                print("   OK (daily) %s" % rec["u10"], flush=True)
            else:
                print("   daily unavailable, falling back to monthly", flush=True)

        mg = os.path.join(d, "u10_monthly.grib")
        if not os.path.exists(mg) or rec.get("u10m") is None:
            req = {"originating_centre": centre, "system": system,
                   "variable": "u_component_of_wind", "pressure_level": "10",
                   "product_type": "monthly_mean",
                   "year": y, "month": m,
                   "leadtime_month": [str(k) for k in range(1, leads + 1)],
                   "data_format": GC}
            print("[%s] u10 monthly_mean" % tag, flush=True)
            if retrieve("seasonal-monthly-pressure-levels", req, mg):
                rec["u10m"] = grib_info(mg)
                print("   OK %s" % rec["u10m"], flush=True)
            else:
                print("   FAILED", flush=True)

        rec["done"] = True
        json.dump(state, open(p, "w"), indent=1)
        time.sleep(SLEEP)

    json.dump(state, open(p, "w"), indent=1)
    print("\n=== summary ===")
    for tag, r in state.items():
        print("  %-16s init=%s snow=%s clim=%s u10=%s" % (
            tag, r.get("init"), bool(r.get("snow")), bool(r.get("clim")), bool(r.get("u10"))))


if __name__ == "__main__":
    main()
