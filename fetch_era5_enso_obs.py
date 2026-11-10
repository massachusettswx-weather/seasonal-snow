"""ERA5 monthly sea surface temperature over the tropics, 1991-2026.

This is the analysis (observation) segment of the ENSO plumes:

  * the basin SST anomaly for each of the four ENSO regions, against the
    ERA5 1991-2020 climatology of the same basin and calendar month - the
    same baseline the models are measured against, so the observed line and
    the forecast plume join without a step;
  * the tropical-mean SST anomaly (20S-20N, all longitudes, land masked),
    which is what the relative index (RONI) subtracts from the basin index.

    python3 fetch_era5_enso_obs.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)
from enso_common import BASIN_NAMES, basin_mean, land_mask_on  # noqa: E402

SRC = os.path.join(DATA, "era5_enso_band.nc")
OUT = os.path.join(DATA, "era5_enso_obs.npz")
CLIM = os.path.join(DATA, "era5_enso_clim.npz")


def download():
    if os.path.exists(SRC) and os.path.getsize(SRC) > 100000:
        print("have %s (%.0f MB)" % (os.path.basename(SRC),
                                     os.path.getsize(SRC) / 1e6), flush=True)
        return
    import cds_direct
    print("requesting ERA5 monthly SST, 1991-2026, 20S-20N global ...", flush=True)
    c = cds_direct.CDSDirect()
    req = {"variable": ["sea_surface_temperature"],
           "product_type": ["monthly_averaged_reanalysis"],
           "year": [str(y) for y in range(1991, 2027)],
           "month": ["%02d" % m for m in range(1, 13)],
           "time": "00:00", "format": "netcdf",
           "area": [20, -180, -20, 180], "data_format": "netcdf"}
    c.retrieve("reanalysis-era5-single-levels-monthly-means", req, SRC)
    print("downloaded %.0f MB" % (os.path.getsize(SRC) / 1e6), flush=True)


def main():
    os.makedirs(DATA, exist_ok=True)
    download()

    import xarray as xr
    ds = xr.open_dataset(SRC)
    names = {str(v).lower(): str(v) for v in ds.data_vars}
    v = ds[names.get("sst", list(ds.data_vars)[0])]
    if "expver" in v.dims:
        v = v.isel(expver=0)
    lat = np.asarray(v.latitude.values, float)
    lon = np.asarray(v.longitudes.values if "longitudes" in v.coords
                     else v.longitude.values, float)
    # the CDS returns -180..180; the ENSO boxes are defined on 0..360
    if lon.min() < 0:
        lon = (lon + 360.0) % 360.0
        v = v.assign_coords(longitude=lon)
    tv = v["valid_time"] if "valid_time" in v.coords else v["time"]
    times = np.asarray(tv.dt.strftime("%Y-%m").values)
    land = land_mask_on(lat, lon)

    # the tropical mean: 20S-20N over every longitude
    tw = np.cos(np.deg2rad(lat))[:, None] * np.ones((1, len(lon)))
    tw = np.where(land > 0.5, 0.0, tw)

    months, basin, tm = [], [], []
    for i in range(v.shape[0]):
        f = np.asarray(v.isel({v.dims[0]: i}).values, float)
        f = np.where(land > 0.5, np.nan, f)
        bm = basin_mean(lat, lon, f, land)
        ok = np.isfinite(f)
        w = np.where(ok, tw, 0.0)
        t = float(np.sum(f * w) / np.sum(w))
        months.append(str(times[i]))
        basin.append([bm[n] for n in BASIN_NAMES])
        tm.append(t)
    months = np.array(months)
    basin = np.array(basin)
    tm = np.array(tm)

    # the 1991-2020 climatology of the same calendar month
    base = np.array([m.startswith("19") or m.startswith("20") for m in months])
    base &= np.array([m[:4] >= "1991" and m[:4] <= "2020" for m in months])
    clim_b = np.zeros((12, len(BASIN_NAMES)))
    clim_t = np.zeros(12)
    for mm in range(1, 13):
        sel = [i for i in range(len(months))
               if int(months[i][5:7]) == mm and base[i]]
        clim_b[mm - 1] = np.mean(basin[sel], axis=0)
        clim_t[mm - 1] = np.mean(tm[sel])
    cal = np.array([int(m[5:7]) - 1 for m in months])
    anom_b = basin - clim_b[cal]
    anom_t = tm - clim_t[cal]

    np.savez_compressed(OUT, months=months, basin=basin, tm=tm,
                        basin_anom=anom_b, tm_anom=anom_t,
                        basin_clim=clim_b, tm_clim=clim_t,
                        basins=np.array(BASIN_NAMES))
    print("saved %s: %d months %s .. %s" %
          (os.path.basename(OUT), len(months), months[0], months[-1]), flush=True)
    print("basin means (K) last 8 months:", flush=True)
    for i in range(max(0, len(months) - 8), len(months)):
        print("  %s  %s | tropical %.3f  anom %.3f" %
              (months[i], " ".join("%.2f" % x for x in basin[i]), tm[i], anom_t[i]),
              flush=True)
    print("climatology (K):", flush=True)
    for i, n in enumerate(BASIN_NAMES):
        print("  %-9s %s" % (n, " ".join("%.2f" % x for x in clim_b[:, i])), flush=True)
    print("  tropical  %s" % " ".join("%.3f" % x for x in clim_t), flush=True)

    # keep the basin climatology in the file the renderer already reads
    if os.path.exists(CLIM):
        z = np.load(CLIM, allow_pickle=True)
        np.savez_compressed(CLIM, basins=np.array(BASIN_NAMES),
                            sst=clim_b, t2m=z["t2m"],
                            sst_min=z["sst_min"], sst_max=z["sst_max"],
                            sst_std=z["sst_std"])
        print("refreshed %s with the band climatology" % os.path.basename(CLIM),
              flush=True)


if __name__ == "__main__":
    main()
