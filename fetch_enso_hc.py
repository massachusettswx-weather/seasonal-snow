"""Each model's OWN hindcast climate for SST - the drift correction.

The plume charts show the observed analysis (the observed SST against the
observed 1991-2020 climatology) in front of the model's forecast.  If the
model's forecast is measured against the observed climatology, the model's
mean SST bias shows up as a step at the join: the plume starts a whole
degree above where the analysis ended, which is not a forecast signal.

The standard fix is to measure the forecast against the model's own hindcast
climate (the C3S "hindcast_climate_mean" product), so the model says how much
warmer than *its own* climate the Pacific will be.

This script fetches that climate for every centre and stores the basin and
tropical-mean climatologies per lead month in data/models/<tag>/sst_hindcast.npz.

    python3 fetch_enso_hc.py                 # every centre, one request at a time
    python3 fetch_enso_hc.py --only ecmwf-seas5
"""
import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
sys.path.insert(0, HERE)
from enso_common import (BASIN_NAMES, basin_mean, land_mask_on,  # noqa: E402
                         tropical_mean)

# tag, centre, system, lead months
CENTRES = [
    ("ecmwf-seas5", "ecmwf", 51, 6),
    ("cmcc-sps4", "cmcc", 4, 6),
    ("dwd-gcfs2", "dwd", 22, 6),
    ("eccc-canesm5", "eccc", 4, 6),
    ("eccc-gem5", "eccc", 5, 6),
    ("ukmo-gloseas6", "ukmo", 610, 6),
    ("meteo-france-s9", "meteo_france", 9, 6),
]


def fetch(tag, centre, system, leads):
    """-> path to the SST hindcast-climate GRIB (downloaded if needed)."""
    import cds_direct
    d = os.path.join(MDIR, tag)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "sst_hindcast.grib")
    if os.path.exists(out) and os.path.getsize(out) > 10000:
        print("  %s: have %s" % (tag, os.path.basename(out)), flush=True)
        return out
    st = os.path.join(DATA, "models_fetched.json")
    state = json.load(open(st)) if os.path.exists(st) else {}
    init = state.get(tag, {}).get("init")
    if not init:
        print("  %s: no init known - skipping" % tag, flush=True)
        return None
    y, m = int(init[:4]), int(init[-2:])
    req = {"originating_centre": centre, "system": system,
           "variable": "sea_surface_temperature",
           "product_type": "hindcast_climate_mean", "year": y, "month": m,
           "leadtime_month": [str(k) for k in range(1, leads + 1)],
           "data_format": "grib"}
    print("  %s: requesting the SST hindcast climate (%s, leads 1-%d)" %
          (tag, init, leads), flush=True)
    c = cds_direct.CDSDirect()
    try:
        jid = c.submit("seasonal-monthly-single-levels", req)
        for _ in range(240):
            stt = c.job_status(jid)
            if stt == "successful":
                c.download_job(jid, out)
                break
            if stt in ("failed", "error", "gone"):
                print("  %s: job %s" % (tag, stt), flush=True)
                return None
            time.sleep(15)
        else:
            print("  %s: timed out" % tag, flush=True)
            return None
    except Exception as e:
        print("  %s: FAILED %s" % (tag, str(e)[:200]), flush=True)
        return None
    print("  %s: saved %s (%.1f MB)" % (tag, os.path.basename(out),
                                         os.path.getsize(out) / 1e6), flush=True)
    return out


def read_clim(path):
    """-> (months, {basin: value}, {tropical: value}) from the GRIB."""
    import eccodes
    from datetime import datetime as _dt, timedelta as _td
    recs = []
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                step = int(eccodes.codes_get(gid, "step"))
                dd = int(eccodes.codes_get(gid, "dataDate"))
                d0 = _dt(dd // 10000, (dd // 100) % 100, dd % 100)
                valid = d0 + _td(hours=step)
                month = valid - _td(days=1)
                lat = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                lon = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                vals = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                recs.append(((month.year, month.month), lat, lon, vals))
            except Exception:
                pass
            eccodes.codes_release(gid)
    if not recs:
        return None
    lat = np.unique(recs[0][1])[::-1]
    lon = np.unique(recs[0][2])
    order = np.argsort(lon)
    land = land_mask_on(lat, lon)
    per_month = {}
    for (ym, la, lo, vals) in recs:
        v = vals.reshape(len(lat), len(lon))[:, order]
        v = np.where(v > 1000.0, np.nan, v)        # the land fill is 9999
        per_month.setdefault(ym, []).append(v)
    out, trop = {}, {}
    for ym, lst in sorted(per_month.items()):
        f = lst[0]
        bm = basin_mean(lat, lon, f, land)
        out[ym] = bm
        trop[ym] = tropical_mean(lat, lon, f, land)
    return sorted(out), out, trop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    only = [x for x in args.only.split(",") if x] or None
    for tag, centre, system, leads in CENTRES:
        if only and tag not in only:
            continue
        print("== %s" % tag, flush=True)
        p = fetch(tag, centre, system, leads)
        if not p:
            continue
        got = read_clim(p)
        if not got:
            print("  %s: could not read the GRIB" % tag, flush=True)
            continue
        months, clim, trop = got
        np.savez_compressed(
            os.path.join(MDIR, tag, "sst_hindcast.npz"),
            months=np.array(["%04d-%02d" % ym for ym in months]),
            basin=np.array([[clim[ym][n] for n in BASIN_NAMES] for ym in months]),
            tropical=np.array([trop[ym] for ym in months]))
        for i, ym in enumerate(months):
            print("    %04d-%02d  %s | tropical %.2f" %
                  (ym[0], ym[1], " ".join("%s %.2f" % (n.split()[-1], clim[ym][n] - 273.15)
                                          for n in BASIN_NAMES), trop[ym] - 273.15),
                  flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
