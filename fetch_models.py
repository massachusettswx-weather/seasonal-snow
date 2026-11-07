"""Patient fetch of the C3S seasonal systems, using the direct CDS client.

The CDS queue limit ("Maximum number queued requests for this dataset") is
global - it is shared with every other user of the dataset, and our own
jobs are all terminal (none of ours holds a slot).  So the only workable
strategy is: one request at a time, retry patiently with a long backoff, and
move on to the next system rather than blocking on one.

For each candidate system we pull:
  * monthly snowfall + 2m_temperature  (seasonal-monthly-single-levels)
  * u_component_of_wind at 10 hPa       (seasonal-original-pressure-levels)

and write everything to data/models/<tag>/*.grib plus data/systems_probe.json.
"""
import os, sys, json, time, glob
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cds_direct import CDSDirect, QueueFull, NoData   # noqa: E402

DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
os.makedirs(MDIR, exist_ok=True)

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
]

INIT_TRY = [("2026", "11"), ("2026", "10"), ("2026", "09"), ("2025", "11")]


def grib_info(path):
    try:
        import eccodes
        n = 0; steps = set(); lats = set(); lons = set(); dates = set()
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
                    dates.add(int(eccodes.codes_get(gid, "dataDate")))
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


def get(client, dataset, req, out, tries=8):
    """One request with patient backoff on queue-full."""
    delay = 45
    for i in range(tries):
        try:
            client.retrieve(dataset, req, out)
            return True
        except QueueFull:
            print("      queue full -> sleep %ds (try %d/%d)" % (delay, i + 1, tries),
                  flush=True)
            time.sleep(delay)
            delay = min(delay * 1.4, 240)
        except NoData as e:
            print("      nodata: %s" % str(e)[:160], flush=True)
            return False
        except Exception as e:
            print("      error: %s %s" % (type(e).__name__, str(e)[:160]), flush=True)
            time.sleep(20)
    return False


def main():
    c = CDSDirect()
    path = os.path.join(DATA, "systems_probe.json")
    res = json.load(open(path)) if os.path.exists(path) else {}
    order = [x[0] for x in CANDIDATES]
    # keep the ones we have not confirmed yet first, but revisit them later
    todo = [x for x in CANDIDATES if not (res.get(x[0], {}).get("snow"))]
    for sid, name, centre, system, leads in todo:
        d = os.path.join(MDIR, sid)
        os.makedirs(d, exist_ok=True)
        print("== %-16s %s:%s" % (sid, centre, system), flush=True)
        rec = res.get(sid, {})
        rec.update({"name": name, "centre": centre, "system": system,
                    "expected_leads": leads})
        snow = rec.get("snow")
        # --- snowfall, all lead months ---
        got_snow = False
        for (y, m) in INIT_TRY:
            if os.path.exists(os.path.join(d, "snowfall_monthly_%s-%s.grib" % (y, m))):
                snow = {"init": "%s-%s" % (y, m), "dataset": "seasonal-monthly-single-levels"}
                got_snow = True
                break
            req = {"originating_centre": centre, "system": system,
                   "variable": "snowfall", "product_type": "monthly_mean",
                   "year": y, "month": m,
                   "leadtime_month": [str(k) for k in range(1, leads + 1)],
                   "data_format": "grib"}
            out = os.path.join(d, "snowfall_monthly_%s-%s.grib" % (y, m))
            if get(c, "seasonal-monthly-single-levels", req, out):
                info = grib_info(out)
                info.update({"init": "%s-%s" % (y, m),
                             "dataset": "seasonal-monthly-single-levels"})
                snow = info
                got_snow = True
                print("   snowfall OK:", info, flush=True)
                break
        rec["snow"] = snow
        rec["done"] = bool(snow)
        res[sid] = rec
        json.dump(res, open(path, "w"), indent=1)
        if not got_snow:
            continue
        # --- u10 ---
        y, m = snow["init"].split("-")
        uout = os.path.join(d, "u10_daily.grib")
        if not os.path.exists(uout):
            req = {"originating_centre": centre, "system": system,
                   "variable": "u_component_of_wind", "pressure_level": "10",
                   "year": y, "month": m,
                   "leadtime_hour": [str(h) for h in range(12, 24 * 210, 24)],
                   "data_format": "grib"}
            if get(c, "seasonal-original-pressure-levels", req, uout, tries=5):
                u = grib_info(uout); u["init"] = snow["init"]
                rec["u10"] = u
                print("   u10 OK:", u, flush=True)
        json.dump(res, open(path, "w"), indent=1)
    ok = [k for k, v in res.items() if v.get("snow")]
    print("confirmed with snowfall: %s" % ", ".join(ok), flush=True)


if __name__ == "__main__":
    main()
