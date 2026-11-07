"""Patient, strictly-sequential prober for the C3S seasonal systems.

What the CDS actually does (measured, not guessed):
  * one request in flight at a time from this token;
  * the "Maximum number queued requests for this dataset" limit is shared with
    other users, so a request can be rejected even when we are idle;
  * a rejected request is cheap - retrying with backoff is the right move;
  * the limit is per *dataset*, so a saturated dataset must not block the
    others.

So: one request at a time, retry with exponential backoff, never give up on a
system until its budget is exhausted.

Results -> data/systems_probe.json  (merged, never overwritten)
"""
import os, json, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
KEY = [l.split(":", 1)[1].strip() for l in open(os.path.join(HERE, ".cdsapirc"))
       if l.strip().startswith("key:")][0]
import cdsapi

CLIENT = cdsapi.Client(url="https://cds.climate.copernicus.eu/api", key=KEY,
                        progress=False, quiet=True, wait_until_complete=False)

CANDIDATES = [
    ("ecmwf-seas5",    "ECMWF SEAS5",          "ecmwf", "51", 7),
    ("ncep-cfsv2",     "NCEP CFSv2",           "ncep",  "2",  7),
    ("ukmo-gloseas6",  "UKMO GloSeas6-GC5.1",  "ukmo",  "610", 6),
    ("eccc-canesm5",   "ECCC CanESM5.1p1bc",   "eccc",  "4",  7),
    ("eccc-gem5",      "ECCC GEM5.2-NEMO",     "eccc",  "5",  7),
    ("bom-access-s2",  "BOM ACCESS-S2",        "bom",   "2",  7),
    ("cmcc-sps4",      "CMCC SPS4",            "cmcc",  "4",  7),
    ("dwd-gcfs2",      "DWD GCFS2.2",          "dwd",   "22", 7),
    ("meteo-france-s9","METFR System 9",       "meteo_france", "9", 6),
    ("ukmo-gc6-604",   "UKMO GloSeas6-GC3.2",  "ukmo",  "604", 6),
    ("ukmo-gc6-601",   "UKMO GloSeas6-GC5.1",  "ukmo",  "601", 6),
]

INIT_TRY = [("2026", "11"), ("2026", "10"), ("2026", "09"), ("2025", "11")]

BACKOFF = [20, 40, 80, 150, 300, 300, 300, 300, 300, 300, 300, 300]


def try_req(dataset, req, fname):
    """-> (ok, why).  'queued' means retry later."""
    try:
        CLIENT.retrieve(dataset, req, fname)
        return True, "ok"
    except Exception as e:
        msg = str(e).replace("\n", " ")
        if "Maximum number queued" in msg:
            return False, "queued"
        if "NoData" in msg or "not available" in msg:
            return False, "nodata"
        return False, msg[-220:]


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
        return {"fields": n, "steps": sorted(steps)[:4], "grid": grid,
                "nlat": len(lats), "nlon": len(lons)}
    except Exception as e:
        return {"error": str(e)[:120]}


def with_retry(dataset, req, fname, label, tries=len(BACKOFF)):
    """Issue one request, retrying on queue-limit rejections."""
    for i in range(tries):
        ok, why = try_req(dataset, req, fname)
        if ok:
            print("      got %s (%s)" % (label, dataset), flush=True)
            return True
        if why != "queued":
            print("      %s -> %s" % (label, why), flush=True)
            return False
        w = BACKOFF[min(i, len(BACKOFF) - 1)]
        print("      %s queued -> sleep %ds (try %d/%d)" % (label, w, i + 1, tries), flush=True)
        time.sleep(w)
    return False


def probe_system(centre, system, sid):
    """-> (snow_info, control_info)"""
    snow = None; control = None
    for (y, m) in INIT_TRY:
        for var in ("snowfall", "2m_temperature"):
            if var == "snowfall" and snow:
                continue
            if var == "2m_temperature" and control:
                continue
            req = {"originating_centre": centre, "system": system,
                   "variable": var, "product_type": "monthly_mean",
                   "year": y, "month": m, "leadtime_month": ["1"],
                   "data_format": "grib"}
            fn = "/tmp/p_%s_%s.grib" % (system, var)
            ok = with_retry("seasonal-monthly-single-levels", req, fn,
                            "%s %s %s-%s" % (sid, var, y, m), tries=6)
            if ok:
                info = grib_info(fn)
                info.update({"init": "%s-%s" % (y, m),
                             "dataset": "seasonal-monthly-single-levels"})
                if var == "snowfall":
                    snow = info
                else:
                    control = info
            else:
                break
        if snow and control:
            break
        if snow:
            break
    return snow, control


def main():
    path = os.path.join(DATA, "systems_probe.json")
    res = json.load(open(path)) if os.path.exists(path) else {}
    for sid, name, centre, system, leads in CANDIDATES:
        if res.get(sid, {}).get("done"):
            print("skip %s (done)" % sid, flush=True); continue
        print("== %-16s %s:%s" % (sid, centre, system), flush=True)
        snow, control = probe_system(centre, system, sid)
        u = None
        if snow:
            y, m = snow["init"].split("-")
            req = {"originating_centre": centre, "system": system,
                   "variable": "u_component_of_wind", "pressure_level": "10",
                   "year": y, "month": m, "leadtime_hour": ["12", "36"],
                   "data_format": "grib"}
            fn = "/tmp/pu_%s.grib" % system
            if with_retry("seasonal-original-pressure-levels", req, fn,
                          "%s u10" % sid, tries=6):
                u = grib_info(fn); u.update({"init": snow["init"]})
        rec = res.get(sid, {})
        rec.update({"name": name, "centre": centre, "system": system,
                    "expected_leads": leads, "snow": snow, "control": control,
                    "u10": u, "done": True})
        res[sid] = rec
        print("   snow:", snow, "\n   ctrl:", control, "\n   u10 :", u, flush=True)
        json.dump(res, open(path, "w"), indent=1)
    json.dump(res, open(path, "w"), indent=1)
    ok = [k for k, v in res.items() if v.get("done") and v.get("snow")]
    print("done. systems with snowfall: %s" % ", ".join(ok), flush=True)


if __name__ == "__main__":
    main()
