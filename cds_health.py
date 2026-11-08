"""Quick health check: is the CDS seasonal MARS archive serving again?

Two probes:
  1. a tiny ERA5 single-levels request (the service that kept working);
  2. a tiny seasonal-monthly-pressure-levels request (the one that stalled).

Prints the elapsed time for each.  Run with:  python3 cds_health.py
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cds_direct import CDSDirect, QueueFull

c = CDSDirect()

PROBES = [
    ("era5", "reanalysis-era5-single-levels",
     {"product_type": "reanalysis", "variable": "2m_temperature",
      "year": "2026", "month": "01", "day": "01", "time": "00:00",
      "data_format": "grib"}),
    ("seasonal-monthly", "seasonal-monthly-pressure-levels",
     {"originating_centre": "ecmwf", "system": "51",
      "variable": "u_component_of_wind", "pressure_level": "10",
      "product_type": "monthly_mean", "year": "2026", "month": "10",
      "leadtime_month": "1", "data_format": "grib"}),
]

for name, ds, req in PROBES:
    t0 = time.time()
    try:
        jid = c.submit(ds, req)
    except QueueFull as e:
        print("%-18s QUEUE FULL after %.0fs" % (name, time.time() - t0), flush=True)
        continue
    except Exception as e:
        print("%-18s SUBMIT FAILED after %.0fs: %s" % (name, time.time() - t0, e), flush=True)
        continue
    print("%-18s submitted %s" % (name, jid), flush=True)
    status = "?"
    while time.time() - t0 < 900:
        try:
            status = c.job_status(jid)
        except Exception as e:
            status = "err:%s" % e
        if status in ("successful", "failed", "dismissed", "gone", "partial"):
            break
        time.sleep(20)
    dt = time.time() - t0
    if status == "successful":
        print("%-18s OK in %.0fs" % (name, dt), flush=True)
    else:
        print("%-18s STATUS=%s after %.0fs" % (name, status, dt), flush=True)
