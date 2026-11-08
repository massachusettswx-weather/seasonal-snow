"""Probe: does seasonal-original-pressure-levels serve DAILY 10 hPa u for the
non-ECMWF centres?  One tiny request per centre, strictly sequential."""
import os, sys, json, time, traceback
from cds_direct import CDSDirect, QueueFull, NoData

DATASET = "seasonal-original-pressure-levels"
CENTRES = [("cmcc", "4"), ("dwd", "22"), ("eccc", "4"), ("eccc", "5"),
           ("ukmo", "610"), ("meteo_france", "9"), ("ncep", "2"), ("bom", "2")]

c = CDSDirect()
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "probe")
os.makedirs(out, exist_ok=True)
res = {}
for centre, sysid in CENTRES:
    tag = "%s%s" % (centre, sysid)
    tgt = os.path.join(out, "daily_%s.grib" % tag)
    req = {"originating_centre": centre, "system": sysid,
           "variable": "u_component_of_wind", "pressure_level": "10",
           "year": "2026", "month": "10", "day": "01",
           "leadtime_hour": ["12", "36"], "data_format": "grib"}
    print("=== probe", tag, flush=True)
    try:
        c.retrieve(DATASET, req, tgt, poll_s=10, max_wait_s=900)
        n = os.path.getsize(tgt)
        res[tag] = {"ok": True, "bytes": n}
        print("   OK  bytes=%d" % n, flush=True)
    except NoData as e:
        res[tag] = {"ok": False, "err": str(e)[:300]}
        print("   NODATA:", str(e)[:300], flush=True)
    except QueueFull as e:
        res[tag] = {"ok": False, "err": "QUEUEFULL"}
        print("   QUEUEFULL - stopping (account limit)", flush=True)
        break
    except Exception as e:
        res[tag] = {"ok": False, "err": str(e)[:300]}
        print("   FAIL:", str(e)[:300], flush=True)
    json.dump(res, open(os.path.join(out, "daily_probe.json"), "w"), indent=1)
print("DONE", json.dumps(res, indent=1))
