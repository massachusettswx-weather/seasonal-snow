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
from enso_common import (BASIN_NAMES, basin_mean, land_mask_on,  # noqa: E402
                         tropical_mean)

BUCKET = "noaa-oar-sfsdev-pds"


def write(tag, months, series, kind, note, tropical=None, init=None):
    d = os.path.join(MDIR, tag)
    os.makedirs(d, exist_ok=True)
    # series: {basin: [per month: [member values]]}
    out = {"kind": kind, "note": note, "init": init,
           "months": months, "basins": BASIN_NAMES, "series": series}
    if tropical is not None:
        # the tropical mean (20S-20N, all longitudes): the term the relative
        # index (RONI) subtracts from the basin anomaly
        out["tropical"] = tropical
    json.dump(out, open(os.path.join(d, "enso.json"), "w"), indent=1)
    for i, n in enumerate(BASIN_NAMES):
        s = out["series"][n]
        print("  %-9s %s" % (n, " ".join("%.2f" % (sum(v) / len(v)) for v in s)),
              flush=True)
    print("%s: wrote enso.json (%d months)" % (tag, len(months)), flush=True)


def sfs():
    """The SFSv1 sea surface temperature from NOAA's ocean store.

    The atmosphere store has no SST - it is in the coupled ocean store
    (ocn_monthly.zarr), 31 members, 12 lead months, 1 degree.
    """
    import s3fs
    import zarr
    from fetch_sfs import newest_init
    fs = s3fs.S3FileSystem(anon=True)
    init = newest_init(fs)
    if not init:
        raise SystemExit("no SFS init found in the store")
    print("   the SFS init: %s" % init, flush=True)
    z = zarr.open_group(fs.get_mapper(
        "%s/experiments/beta3/forecast/%s/ocn_monthly.zarr" % (BUCKET, init)),
        mode="r")
    v = z["SST"]
    la = np.asarray(z["latitude"][:], float)
    lo = np.asarray(z["longitude"][:], float)
    # the basin boxes are defined on 0..360, so the longitudes stay there
    land = land_mask_on(la, lo)
    months, series = [], {n: [] for n in BASIN_NAMES}
    trop = []
    nm = z["SST"].shape[1]
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
        # the ocean store keeps the SST in Celsius and fills the land and the
        # cells the ocean model does not cover with a huge negative number
        if np.nanmax(block) < 200.0:
            block = block + 273.15
        block = np.where((block > 250.0) & (block < 330.0), block, np.nan)
        stack = block.reshape(block.shape[0], block.shape[1], block.shape[2])
        for i in range(stack.shape[0]):
            bm = basin_mean(la, lo, stack[i], land)
            for n in BASIN_NAMES:
                series[n].append(bm[n])
            trop.append(tropical_mean(la, lo, stack[i], land))
    # transpose to per-month lists of members
    nmem = stack.shape[0]
    out = {n: [[series[n][i * nmem + j] for j in range(nmem)]
               for i in range(len(months))] for n in BASIN_NAMES}
    out_t = [[trop[i * nmem + j] for j in range(nmem)] for i in range(len(months))]
    write("sfsv1", months, out, "noaa-sst",
          "NOAA SFSv1 sea surface temperature from the NODD ocean store, 31 members",
          tropical=out_t, init="%s-%s" % (init[:4], init[4:6]))


CPC_IDX = "https://www.cpc.ncep.noaa.gov/products/CFSv2/dataInd1"

# the Nino index CPC publishes for each basin
CPC_INDEX_FILE = {
    "Nino 3.4": "nino34Mon.nc",
    "Nino 3": "nino3Mon.nc",
    "Nino 4": "nino4Mon.nc",
    "Nino 1+2": "nino12Mon.nc",
}

# the renormalisation that turns the basin anomaly into the relative one.
# It is the same constant the rest of the site uses (it comes out at 1.242
# with ERSST v6), and it reproduces CPC's published RONI to 0.006 degC.
K_RONI = 1.242


def _cpc_index(name, cache):
    """-> (months, values) for one of CPC's Nino index files.

    The file holds the 40 forecast members and one observed series for 21
    months: the hindcast months are filled with -9999, so the forecast
    months are the ones where the members are present.
    """
    import datetime
    import h5netcdf
    import urllib.request
    os.makedirs(cache, exist_ok=True)
    p = os.path.join(cache, name)
    if not (os.path.exists(p) and os.path.getsize(p) > 1000):
        url = "%s/%s" % (CPC_IDX, name)
        print("  downloading", url, flush=True)
        urllib.request.urlretrieve(url, p)
    with h5netcdf.File(p, "r") as f:
        t = np.asarray(f["time"][:], float)
        a = np.asarray(f["anom"][:], float)
    a = a.reshape(a.shape[0], a.shape[1])
    a = np.where(a < -9000, np.nan, a)        # the fill marks the hindcast
    months = []
    for x in t:
        d = datetime.date(2021, 1, 1) + datetime.timedelta(days=int(x))
        months.append("%04d-%02d" % (d.year, d.month))
    return months, a


def cfsv2():
    """The CFSv2 plume, built from CPC's own published Nino indices.

    CPC publishes, for the current init, the 40-member ensemble of the
    monthly Nino 3.4, 3, 4 and 1+2 indices and the RONI of Nino 3.4, for
    the nine forecast months.  That is more than the gridded file carries
    (which is the 40-member mean of the SST anomaly for six months), and it
    is NOAA's own index rather than one derived here.

    The relative index is built the same way as every other model's: the
    basin anomaly minus the tropical-mean anomaly, rescaled.  The tropical
    term is CPC's own, recovered per member from the two published series
    (RONI = (Nino 3.4 - tropical) x k), so the RONI of Nino 3.4 here is
    CPC's published RONI exactly, and the other basins use the same
    tropical term member by member.
    """
    cache = os.path.join(DATA, "cpc_index")
    m34, a34 = _cpc_index("nino34Mon.nc", cache)
    _, ar34 = _cpc_index("rnino34Mon.nc", cache)
    months_all = m34

    # the forecast months are the ones where the members are present
    fmask = np.array([np.isfinite(a34[:, k]).sum() >= 40
                      for k in range(a34.shape[1])])
    fidx = [k for k in range(len(months_all)) if fmask[k]]
    months = [months_all[k] for k in fidx]
    print("  CFSv2 forecast months: %s .. %s (%d)"
          % (months[0], months[-1], len(months)), flush=True)

    series = {}
    for basin, fname in CPC_INDEX_FILE.items():
        if fname == "nino34Mon.nc":
            a = a34
        else:
            mm, aa = _cpc_index(fname, cache)
            assert mm == months_all
            a = aa
        rows = []
        for k in fidx:
            col = a[:, k]
            rows.append([float(v) for v in col[np.isfinite(col)]])
        series[basin] = rows

    # CPC's tropical term, per member, recovered from Nino 3.4 and its RONI
    trop = []
    for k in fidx:
        c34 = a34[:, k]
        cr = ar34[:, k]
        ok = np.isfinite(c34) & np.isfinite(cr)
        tv = c34[ok] - cr[ok] / K_RONI
        trop.append([float(v) for v in tv])
        if k == fidx[0]:
            print("  members per month: %d | tropical term %.3f .. %.3f"
                  % (len(tv), min(tv), max(tv)), flush=True)

    # the first forecast month identifies the init: CPC replaces the file
    # when a new run starts, so the label comes from the data
    init = months[0][:7] if months else "2026-11"
    print("  the CFSv2 init: %s" % init, flush=True)
    write("cfsv2", months, series, "noaa-anom",
          "NOAA CFSv2 published Nino indices (40-member ensemble, CPC)",
          tropical=trop, init=init)


if __name__ == "__main__":
    sfs()
    cfsv2()
