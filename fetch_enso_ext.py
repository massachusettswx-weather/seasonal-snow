"""The extended-lead SST for the C3S centres (lead month 7 and beyond).

The C3S monthly product stops at lead month 6 for every centre, but the
original (daily) product carries the same fields out to 5160 h = 215 days =
7 lead months.  This script pulls the SST for the extra lead months on the
tropical band only and aggregates it into monthly means, so the ENSO plumes
run to each system's own full range.

    python3 fetch_enso_ext.py --only ecmwf-seas5
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

# tag, centre, system, first extra lead (month), last extra lead (month)
CENTRES = [
    ("ecmwf-seas5", "ecmwf", 51, 7, 7),
    ("cmcc-sps4", "cmcc", 4, 7, 7),
    ("dwd-gcfs2", "dwd", 22, 7, 7),
    ("eccc-canesm5", "eccc", 4, 7, 7),
    ("eccc-gem5", "eccc", 5, 7, 7),
    ("ukmo-gloseas6", "ukmo", 610, 7, 7),
    ("meteo-france-s9", "meteo_france", 9, 7, 7),
]

# the tropical band, generous enough to hold every ENSO box
AREA = [20.0, 140.0, -20.0, 290.0]


def hours_for(lead_from, lead_to):
    """The lead hours that cover lead months lead_from..lead_to."""
    out = []
    for m in range(lead_from, lead_to + 1):
        # the end of lead month m (day 30/31/28 of the month) as hours
        out.append(int((m * 30.44) * 24))
    return out


def fetch(tag, centre, system, lead_from, lead_to):
    import cds_direct
    d = os.path.join(MDIR, tag)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "sst_extended.grib")
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
    # every 24 h from the start of lead month lead_from to the end of the run
    start = int((lead_from - 1) * 30.44 * 24)
    end = 5160
    leads = [str(h) for h in range(start, end + 1, 24)]
    req = {"originating_centre": centre, "system": system,
           "variable": "sea_surface_temperature",
           "year": y, "month": m, "leadtime_hour": leads,
           "data_format": "grib"}
    # the area cut keeps the download small; some systems refuse it
    req_area = dict(req, area=AREA)
    c = cds_direct.CDSDirect()
    for attempt, r_ in enumerate((req_area, req)):
        print("  %s: requesting the SST for lead months %d-%d (%s) %s" %
              (tag, lead_from, lead_to, "tropical band" if attempt == 0
               else "global", " ".join(leads[:2]) + " ..."), flush=True)
        try:
            jid = c.submit("seasonal-original-single-levels", r_)
        except Exception as e:
            print("  %s: submit failed %s" % (tag, str(e)[:160]), flush=True)
            continue
        ok = False
        for _ in range(240):
            stt = c.job_status(jid)
            if stt == "successful":
                c.download_job(jid, out)
                ok = True
                break
            if stt in ("failed", "error", "gone", "rejected"):
                print("  %s: job %s" % (tag, stt), flush=True)
                try:
                    c._request("DELETE", "/retrieve/v1/jobs/%s" % jid)
                except Exception:
                    pass
                break
            time.sleep(15)
        if ok:
            print("  %s: saved %s (%.1f MB)" % (tag, os.path.basename(out),
                                                 os.path.getsize(out) / 1e6),
                  flush=True)
            return out
    return None


def read_extended(path):
    """-> (months, {basin: [member values]}, {tropical: [member values]})."""
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
        v = np.where(v > 1000.0, np.nan, v)
        per_month.setdefault(ym, []).append(v)
    out, trop = {}, {}
    for ym, lst in sorted(per_month.items()):
        stack = np.array(lst)
        mem = []
        for i in range(stack.shape[0]):
            bm = basin_mean(lat, lon, stack[i], land)
            mem.append(bm)
            trop.setdefault(ym, []).append(tropical_mean(lat, lon, stack[i], land))
        out[ym] = mem
    return sorted(out), out, trop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    only = [x for x in args.only.split(",") if x] or None
    for tag, centre, system, lf, lt in CENTRES:
        if only and tag not in only:
            continue
        print("== %s" % tag, flush=True)
        p = fetch(tag, centre, system, lf, lt)
        if not p:
            continue
        got = read_extended(p)
        if not got:
            print("  %s: could not read the GRIB" % tag, flush=True)
            continue
        months, idx, trop = got
        np.savez_compressed(
            os.path.join(MDIR, tag, "sst_extended.npz"),
            months=np.array(["%04d-%02d" % ym for ym in months]),
            basin=np.array([[[mem[n] for mem in idx[ym]] for n in BASIN_NAMES]
                            for ym in months]),
            tropical=np.array([trop[ym] for ym in months]))
        for i, ym in enumerate(months):
            print("    %04d-%02d  Nino3.4 %.2f C (mean of %d members)" %
                  (ym[0], ym[1], np.mean([m["Nino 3.4"] for m in idx[ym]]) - 273.15,
                   len(idx[ym])), flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
