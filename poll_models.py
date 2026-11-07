"""Very patient background poller for the C3S seasonal systems.

The CDS "Maximum number queued requests" limit turned out to be ACCOUNT-WIDE,
not per-dataset: a dataset this session had never touched also failed, and
none of our own ~5,000 jobs were in a non-terminal state.  So the limit is
either a global-per-account concurrency cap or a rolling request-rate cap.

Either way the strategy is the same: make ONE request, then wait a long time
before the next one.  This poller therefore:

  * walks the candidate systems one at a time;
  * makes a single attempt per system per cycle;
  * sleeps LONG (default 8 min) between attempts;
  * never runs two requests concurrently;
  * records everything it manages to pull.

Run:  nohup python3 poll_models.py &
"""
import os, sys, json, time
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
SLEEP = float(os.environ.get("POLL_SLEEP_S", 480))


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


def one_shot(client, sid, centre, system, leads, rec):
    """Try to get this system's snowfall + u10.  Returns True on success."""
    d = os.path.join(MDIR, sid)
    os.makedirs(d, exist_ok=True)
    snow = rec.get("snow")
    if not snow:
        for (y, m) in INIT_TRY:
            out = os.path.join(d, "snowfall_monthly_%s-%s.grib" % (y, m))
            if os.path.exists(out):
                snow = {"init": "%s-%s" % (y, m),
                        "dataset": "seasonal-monthly-single-levels"}
                break
            req = {"originating_centre": centre, "system": system,
                   "variable": "snowfall", "product_type": "monthly_mean",
                   "year": y, "month": m,
                   "leadtime_month": [str(k) for k in range(1, leads + 1)],
                   "data_format": "grib"}
            try:
                client.retrieve("seasonal-monthly-single-levels", req, out)
            except QueueFull:
                return False
            except NoData as e:
                print("   %s snowfall %s-%s nodata: %s" % (sid, y, m, str(e)[:90]), flush=True)
                continue
            except Exception as e:
                print("   %s error: %s %s" % (sid, type(e).__name__, str(e)[:90]), flush=True)
                continue
            info = grib_info(out)
            info.update({"init": "%s-%s" % (y, m),
                         "dataset": "seasonal-monthly-single-levels"})
            snow = info
            print("   %s snowfall OK %s" % (sid, info), flush=True)
            break
        rec["snow"] = snow
    if not snow:
        return False
    # u10
    uout = os.path.join(d, "u10_daily.grib")
    if not os.path.exists(uout):
        y, m = snow["init"].split("-")
        req = {"originating_centre": centre, "system": system,
               "variable": "u_component_of_wind", "pressure_level": "10",
               "year": y, "month": m,
               "leadtime_hour": [str(h) for h in range(12, 24 * 210, 24)],
               "data_format": "grib"}
        try:
            client.retrieve("seasonal-original-pressure-levels", req, uout)
            u = grib_info(uout); u["init"] = snow["init"]
            rec["u10"] = u
            print("   %s u10 OK %s" % (sid, u), flush=True)
        except QueueFull:
            return False
        except NoData as e:
            print("   %s u10 nodata: %s" % (sid, str(e)[:90]), flush=True)
        except Exception as e:
            print("   %s u10 error: %s %s" % (sid, type(e).__name__, str(e)[:90]), flush=True)
    rec["done"] = True
    return True


def main():
    c = CDSDirect()
    path = os.path.join(DATA, "systems_probe.json")
    res = json.load(open(path)) if os.path.exists(path) else {}
    cycle = 0
    while True:
        cycle += 1
        remaining = []
        for sid, name, centre, system, leads in CANDIDATES:
            rec = res.get(sid, {})
            rec.update({"name": name, "centre": centre, "system": system,
                        "expected_leads": leads})
            res[sid] = rec
            if rec.get("done") and rec.get("snow") and rec.get("u10"):
                continue
            remaining.append((sid, name, centre, system, leads))
        if not remaining:
            print("ALL SYSTEMS FETCHED", flush=True)
            json.dump(res, open(path, "w"), indent=1)
            return
        print("=== cycle %d: %d system(s) still to do: %s"
              % (cycle, len(remaining), ", ".join(r[0] for r in remaining)), flush=True)
        for (sid, name, centre, system, leads) in remaining:
            if one_shot(c, sid, centre, system, leads, res.get(sid, {})):
                res[sid] = res.get(sid, {})
                res[sid].update({"name": name, "centre": centre, "system": system,
                                 "expected_leads": leads})
                json.dump(res, open(path, "w"), indent=1)
            time.sleep(SLEEP)
        json.dump(res, open(path, "w"), indent=1)


if __name__ == "__main__":
    main()
