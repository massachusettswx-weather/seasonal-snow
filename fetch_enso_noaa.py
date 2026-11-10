"""ENSO basin indices for the NOAA systems (read straight from NOAA).

NOAA SFSv1 - the NODD zarr: the model's 2 m air temperature over the tropical
Pacific (the atmosphere store has no SST), 31 members, 12 lead months.
NOAA CFSv2 - NCEP CPC: the published 40-member ensemble-mean 2 m air
temperature anomaly, which is already an anomaly against a 1991-2020
climatology.

    python3 fetch_enso_noaa.py
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
sys.path.insert(0, HERE)
from enso_common import BASIN_NAMES, basin_mean, land_mask_on  # noqa: E402

BUCKET = "noaa-oar-sfsdev-pds"


def write(tag, months, series, kind, note):
    d = os.path.join(MDIR, tag)
    os.makedirs(d, exist_ok=True)
    # series: {basin: [per month: [member values]]}
    out = {"kind": kind, "note": note,
           "months": months, "basins": BASIN_NAMES, "series": series}
    json.dump(out, open(os.path.join(d, "enso.json"), "w"), indent=1)
    for i, n in enumerate(BASIN_NAMES):
        s = out["series"][n]
        print("  %-9s %s" % (n, " ".join("%.2f" % (sum(v) / len(v)) for v in s)),
              flush=True)
    print("%s: wrote enso.json (%d months)" % (tag, len(months)), flush=True)


def sfs():
    import s3fs
    import zarr
    fs = s3fs.S3FileSystem(anon=True)
    z = zarr.open_group(fs.get_mapper(
        "%s/experiments/beta3/forecast/202611/atm_monthly.zarr" % BUCKET), mode="r")
    v = z["tmp2m"]
    la = np.asarray(z["lat"][:], float)
    lo = np.asarray(z["lon"][:], float)
    # the basin boxes are defined on 0..360, so the longitudes stay there
    land = land_mask_on(la, lo)
    months, series = [], {n: [] for n in BASIN_NAMES}
    nm = z["tmp2m"].shape[1]
    names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
             "Oct", "Nov", "Dec"]
    for lead in range(nm):
        mm = lead + 11                      # lead 1 = November 2026
        if mm <= 12:
            ym, mm = 2026, mm
        else:
            ym, mm = 2027, mm - 12
        months.append("%04d-%02d" % (ym, mm))
        block = np.asarray(v[:, lead, :, :], float)      # (member, lat, lon)
        stack = block.reshape(block.shape[0], block.shape[1], block.shape[2])
        for i in range(stack.shape[0]):
            bm = basin_mean(la, lo, stack[i], land)
            for n in BASIN_NAMES:
                series[n].append(bm[n])
    # transpose to per-month lists of members
    out = {n: [[series[n][i * stack.shape[0] + j] for j in range(stack.shape[0])]
               for i in range(len(months))] for n in BASIN_NAMES}
    write("sfsv1", months, out, "noaa-t2m",
          "NOAA SFSv1 2 m air temperature from the NODD zarr, 31 members")


def cfsv2():
    import h5netcdf
    p = os.path.join(MDIR, "cfsv2", "glbT2mMon.nc")
    if not os.path.exists(p):
        print("cfsv2: no CPC file yet - skipping", flush=True)
        return
    with h5netcdf.File(p, "r") as f:
        anom = np.asarray(f["anom"][0, :, 0], float)      # (time, lat, lon)
        lat = np.asarray(f["lat"][:], float)
        lon = np.asarray(f["lon"][:], float)
        t = np.asarray(f["time"][:], float)
    land = land_mask_on(lat, lon)
    months, series = [], []
    import datetime
    for i in range(anom.shape[0]):
        dt = datetime.date(2021, 1, 1) + datetime.timedelta(days=int(t[i]))
        months.append("%04d-%02d" % (dt.year, dt.month))
        bm = basin_mean(lat, lon, anom[i], land)
        series.append([bm[n] for n in BASIN_NAMES])
    orig = series
    series = {}
    for j, n in enumerate(BASIN_NAMES):
        series[n] = [[row[j]] for row in orig]
    write("cfsv2", months, series, "noaa-anom",
          "NOAA CFSv2 published 2 m air temperature anomaly (40-member mean)")


if __name__ == "__main__":
    sfs()
    cfsv2()
