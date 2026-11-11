"""ENSO basin indices for every seasonal model.

For each model we need the forecast SST (or 2 m air temperature over the
tropical Pacific) for every ensemble member and every lead month, then the
area-weighted basin means for the four standard ENSO regions.

    Nino 3.4   5N-5S  170W-120W     Nino 3   5N-5S  150W-90W
    Nino 4     5N-20S 160E-150W     Nino 1+2 0-10S  90W-80W

The anomalies are measured against the ERA5 1991-2020 climatology of the same
basin and month (data/era5_enso_clim.npz), so every model's plume is on the
same footing.

    python3 fetch_enso.py                 # every model that has data
    python3 fetch_enso.py --only ecmwf-seas5
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
GC = "grib"

# tag, C3S originating centre, system, lead months
C3S = [
    ("ecmwf-seas5", "ecmwf", 51, 6),
    ("cmcc-sps4", "cmcc", 4, 6),
    ("dwd-gcfs2", "dwd", 22, 6),
    ("eccc-canesm5", "eccc", 4, 6),
    ("eccc-gem5", "eccc", 5, 6),
    ("ukmo-gloseas6", "ukmo", 610, 6),
    ("meteo-france-s9", "meteo_france", 9, 6),
    ("jma-jra3", "jma", 4, 6),
    ("bom-access-s2", "bom", 2, 6),
]

# basin: name, lat0, lat1, lon0, lon1 (degrees, lon negative = west)
BASINS = [
    ("Nino 3.4", 5.0, -5.0, 190.0, 240.0),
    ("Nino 3", 5.0, -5.0, 210.0, 270.0),
    ("Nino 4", 5.0, -20.0, 160.0, 210.0),
    ("Nino 1+2", 0.0, -10.0, 270.0, 280.0),
]


def basin_means(lat, lon, field, land=None):
    """-> {basin: area-weighted mean} for a 2-D field (lat, lon)."""
    out = {}
    ok = np.isfinite(field)
    for name, la0, la1, lo0, lo1 in BASINS:
        m = (lat[:, None] >= min(la0, la1)) & (lat[:, None] <= max(la0, la1)) & \
            (lon[None, :] >= min(lo0, lo1)) & (lon[None, :] <= max(lo0, lo1))
        if land is not None:
            m = m & (land < 0.5)
        if not m.any():
            out[name] = np.nan
            continue
        w = np.cos(np.deg2rad(lat[:, None]))
        ww = np.broadcast_to(w, field.shape) * m * ok
        tot = ww.sum()
        out[name] = float(np.sum(np.where(ok, field, 0.0) * ww) / tot) if tot > 0 else np.nan
    return out


def fetch_c3s_sst(tag, centre, system, leads, init=None):
    """-> path to the SST GRIB (already downloaded if present)."""
    import cds_direct
    d = os.path.join(MDIR, tag)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "sst_monthly.grib")
    if os.path.exists(out) and os.path.getsize(out) > 10000:
        print("  %s: have %s" % (tag, os.path.basename(out)), flush=True)
        return out
    st = os.path.join(DATA, "models_fetched.json")
    state = json.load(open(st)) if os.path.exists(st) else {}
    if init is None:
        init = state.get(tag, {}).get("init")
    if not init:
        print("  %s: no init known - skipping" % tag, flush=True)
        return None
    y, m = int(init[:4]), int(init[-2:])
    req = {"originating_centre": centre, "system": system,
           "variable": "sea_surface_temperature",
           "product_type": "monthly_mean", "year": y, "month": m,
           "leadtime_month": [str(k) for k in range(1, leads + 1)],
           "data_format": GC}
    print("  %s: requesting SST %s leads 1-%d" % (tag, init, leads), flush=True)
    c = cds_direct.CDSDirect()
    import time
    try:
        # the CDS queue is account-wide and only takes a few jobs at a time,
        # so a submission can be refused - wait for a slot and try again
        jid = None
        for attempt in range(40):
            try:
                jid = c.submit("seasonal-monthly-single-levels", req)
                break
            except cds_direct.QueueFull:
                if attempt == 0:
                    print("  %s: queue full, waiting for a slot" % tag, flush=True)
                time.sleep(120)
        if jid is None:
            print("  %s: no queue slot after 80 min - skipping" % tag, flush=True)
            return None
        for _ in range(240):
            st = c.job_status(jid)
            if st == "successful":
                c.download_job(jid, out)
                break
            if st in ("failed", "error"):
                print("  %s: job %s" % (tag, st), flush=True)
                return None
            time.sleep(15)
    except Exception as e:
        print("  %s: FAILED %s" % (tag, str(e)[:160]), flush=True)
        return None
    print("  %s: saved %s (%.1f MB)" % (tag, out, os.path.getsize(out) / 1e6), flush=True)
    return out


def indices_from_grib(path):
    """-> (months, {basin: [member values]}, {tropical: [member values]}).

    The C3S SST field fills land with 9999, so every mean has to exclude the
    land - the Nino 1+2 box straddles the South American coast and without the
    mask its mean is garbage.
    """
    import eccodes
    from datetime import datetime as _dt, timedelta as _td
    from enso_common import land_mask_on, tropical_mean
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
                month = (valid - _td(days=1))
                lat = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                lon = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                vals = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                recs.append(((month.year, month.month), lat, lon, vals))
            except Exception:
                pass
            eccodes.codes_release(gid)
    if not recs:
        return None
    lat = np.unique(recs[0][1])[::-1]        # descending, like the GRIB
    # keep the longitudes in 0..360: the ENSO boxes are defined that way and
    # Nino 4 straddles the date line
    lon = np.unique(recs[0][2])
    order = np.argsort(lon)
    land = land_mask_on(lat, lon)
    per_month = {}
    for (ym, la, lo, vals) in recs:
        v = vals.reshape(len(lat), len(lon))[:, order]
        # the C3S land fill is 9999
        v = np.where(v > 1000.0, np.nan, v)
        per_month.setdefault(ym, []).append(v)
    out = {}
    trop = {}
    for ym, lst in sorted(per_month.items()):
        stack = np.array(lst)
        mem = []
        for i in range(stack.shape[0]):
            mem.append(basin_means(lat, lon, stack[i], land))
            trop.setdefault(ym, []).append(
                tropical_mean(lat, lon, stack[i], land))
        out[ym] = mem
    return out, trop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    only = [x for x in args.only.split(",") if x] or None

    # the C3S centres first (one CDS request at a time)
    for tag, centre, system, leads in C3S:
        if only and tag not in only:
            continue
        print("== %s" % tag, flush=True)
        p = fetch_c3s_sst(tag, centre, system, leads)
        if p:
            got = indices_from_grib(p)
            if got:
                idx, trop = got
                save(tag, idx, trop, "c3s-sst")
    print("done", flush=True)


def save(tag, idx, trop, kind):
    d = os.path.join(MDIR, tag)
    os.makedirs(d, exist_ok=True)
    months = sorted(idx)
    names = [b[0] for b in BASINS]
    st = json.load(open(os.path.join(DATA, "models_fetched.json"))) \
        if os.path.exists(os.path.join(DATA, "models_fetched.json")) else {}
    out = {"kind": kind,
           "init": st.get(tag, {}).get("init"),
           "months": ["%04d-%02d" % ym for ym in months],
           "basins": names,
           "series": {n: [[mem[n] for mem in idx[ym]] for ym in months]
                      for n in names},
           # the tropical mean (20S-20N, all longitudes) for the relative index
           "tropical": [trop[ym] for ym in months]}
    json.dump(out, open(os.path.join(d, "enso.json"), "w"), indent=1)
    print("  %s: wrote enso.json (%d months, %d members)" %
          (tag, len(months), len(out["series"][names[0]][0])), flush=True)
    for i, n in enumerate(names):
        mm = np.array(out["series"][n])
        print("    %-9s %s" % (n, " ".join("%.2f" % (v.mean() - 273.15)
                                         for v in mm)), flush=True)


if __name__ == "__main__":
    main()
