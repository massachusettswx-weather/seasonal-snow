"""ERA5 1991-2020 climatology for the four ENSO basins.

Monthly means of sea surface temperature and 2 m air temperature over the
tropical Pacific, plus the land-sea mask, reduced to the basin means.  The
result is data/era5_enso_clim.npz:

    sst[12, nbasin]   basin-mean SST (K) for each calendar month
    t2m[12, nbasin]   basin-mean 2 m air temperature (K)
    sst_std[12, nbasin]  the interannual spread of the basin mean
    sst_min / sst_max   the 1991-2020 monthly range
    basins            the basin names

    python3 fetch_era5_enso.py
"""
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ARCO = ("https://storage.googleapis.com/gcp-public-data-arco-era5/"
        "ar/1959-2022-6h-240x121_equiangular_with_poles_conservative.zarr")

sys.path.insert(0, HERE)
from enso_common import BASINS, BASIN_NAMES, basin_mean, land_mask_on  # noqa: E402


def land_mask():
    """ERA5 land-sea mask (1 = land) on the ARCO grid, saved for reuse."""
    import xarray as xr
    p = os.path.join(DATA, "era5_enso_landmask.npz")
    if os.path.exists(p):
        z = np.load(p)
        return z["land"], z["lat"], z["lon"]
    ds = xr.open_zarr(ARCO, chunks=None)
    lsm = ds["land_sea_mask"]
    if "time" in lsm.dims:
        lsm = lsm.isel(time=0)
    lat = np.asarray(lsm.latitude.values, float)
    lon = np.asarray(lsm.longitude.values, float)
    land = np.asarray(lsm.values, float)
    np.savez_compressed(p, land=land, lat=lat, lon=lon)
    print("land mask saved:", land.shape, "lat", lat.min(), lat.max(),
          "lon", lon.min(), lon.max(), flush=True)
    return land, lat, lon


def main():
    os.makedirs(DATA, exist_ok=True)
    land_ar, lat_ar, lon_ar = land_mask()

    src = os.path.join(DATA, "era5_enso_monthly.nc")
    if not os.path.exists(src):
        print("downloading the ERA5 monthly means...", flush=True)
        import cds_direct
        c = cds_direct.CDSDirect()
        req = {"variable": ["sea_surface_temperature", "2m_temperature"],
               "product_type": ["monthly_averaged_reanalysis"],
               "year": [str(y) for y in range(1991, 2021)],
               "month": [str(m) for m in range(1, 13)],
               "time": "00:00", "format": "netcdf",
               "area": [20, 100, -20, 300], "data_format": "netcdf"}
        jid = c.submit("reanalysis-era5-single-levels-monthly-means", req)
        c.download_job(jid, src)
    print("ERA5 monthly means:", os.path.getsize(src) / 1e6, "MB", flush=True)

    import xarray as xr
    ds = xr.open_dataset(src)
    print("vars:", list(ds.data_vars), flush=True)

    def series(varname):
        v = ds[varname]
        lat = np.asarray(v.latitude.values, float)
        lon = np.asarray(v.longitude.values, float)
        if "expver" in v.dims:               # ERA5 keeps an experiment version
            v = v.isel(expver=0)
        tv = v["valid_time"] if "valid_time" in v.coords else v["time"]
        months = np.asarray(tv.dt.month.values)
        out = {m: [] for m in range(1, 13)}
        for i in range(v.shape[0]):
            if months is None:
                continue
            f = np.asarray(v.isel({v.dims[0]: i}).values, float)
            bm = basin_mean(lat, lon, f, land_mask_on(lat, lon))
            out[int(months[i])].append([bm[n] for n in BASIN_NAMES])
        return out, lat, lon

    results = {}
    names = {str(v).lower(): str(v) for v in ds.data_vars}
    for var, key in (("sst", "sst"), ("t2m", "t2m")):
        if var not in names:
            print("  %s missing from the download (have %s)" % (var, list(ds.data_vars)),
                  flush=True)
            continue
        var = names[var]
        ser, lat, lon = series(var)
        mean = np.array([np.mean(ser[m], axis=0) for m in range(1, 13)])
        results[key] = mean
        if key == "sst":
            results["sst_std"] = np.array([np.std(ser[m], axis=0) for m in range(1, 13)])
            results["sst_min"] = np.array([np.min(ser[m], axis=0) for m in range(1, 13)])
            results["sst_max"] = np.array([np.max(ser[m], axis=0) for m in range(1, 13)])
        print("%s basin means (K):" % var, flush=True)
        for i, n in enumerate(BASIN_NAMES):
            print("   %-9s %s" % (n, " ".join("%.1f" % v for v in mean[:, i])), flush=True)

    np.savez_compressed(os.path.join(DATA, "era5_enso_clim.npz"),
                        basins=np.array(BASIN_NAMES),
                        **{k: v for k, v in results.items()})
    print("saved data/era5_enso_clim.npz", flush=True)


if __name__ == "__main__":
    main()
