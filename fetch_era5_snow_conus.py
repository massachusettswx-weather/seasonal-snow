"""Official ERA5 1991-2020 monthly snowfall climatology over the FULL CONUS box.

Dataset: reanalysis-era5-single-levels-monthly-means
         product_type = monthly_averaged_reanalysis, variable = snowfall

Why this matters: the climatology that was in data/era5_snow_clim.npz covers
only 99W-66W on a 1.5 deg grid, so the Sierra, the Cascades and the Rockies
- where the seasonal models put their snowfall - were never compared against
an observed reference at all.

Saves data/era5_snow_clim_conus.npz:
    clim (6, nlat, nlon)  mm w.e. per calendar month for 11,12,1,2,3,4
    lat, lon, months, years
"""
import os, sys, time, json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cds_direct import CDSDirect, QueueFull

DATA = os.path.join(HERE, "data")
DATASET = "reanalysis-era5-single-levels-monthly-means"
MONTHS = ["11", "12", "01", "02", "03", "04"]
AREA = [51, -127.5, 22, -64]        # N, W, S, E  (CONUS + a little margin)
OUT = os.path.join(DATA, "era5_snow_clim_conus.npz")


def decode(path):
    """-> list of dicts with year, month, lat(axis), lon(axis), values, units."""
    import eccodes
    out = []
    with open(path, "rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            try:
                la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                lo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                lats = np.unique(la)[::-1]
                lons = np.unique(lo)
                v = v.reshape(len(lats), len(lons))
                out.append(dict(year=int(eccodes.codes_get(gid, "year")),
                                 month=int(eccodes.codes_get(gid, "month")),
                                 lat=lats, lon=lons, values=v,
                                 units=eccodes.codes_get(gid, "units")))
            except Exception:
                pass
            eccodes.codes_release(gid)
    return out


def main():
    if os.path.exists(OUT):
        print("already have", OUT)
        return
    c = CDSDirect()
    req = {"product_type": "monthly_averaged_reanalysis", "variable": ["snowfall"],
           "year": [str(y) for y in range(1991, 2021)], "month": MONTHS,
           "time": "00:00", "area": AREA, "data_format": "grib"}
    grib = os.path.join(DATA, "era5_snow_clim_conus.grib")
    jid = None
    for attempt in range(60):
        try:
            jid = c.submit(DATASET, req)
            print("submitted %s (attempt %d)" % (jid[:8], attempt + 1), flush=True)
            break
        except QueueFull:
            print("queue full - retry in 60 s", flush=True)
            time.sleep(60)
        except Exception as e:
            print("submit failed:", str(e)[:200], flush=True)
            time.sleep(60)
    if not jid:
        print("GAVE UP")
        return
    t0 = time.time()
    while time.time() - t0 < 5400:
        s = c.job_status(jid)
        if s != "accepted":
            print("status:", s, flush=True)
            if s == "successful":
                break
            if s in ("failed", "rejected", "dismissed", "gone"):
                print("detail:", c._job_detail(jid)[:400], flush=True)
                return
        else:
            print("  waiting %.0f min" % ((time.time() - t0) / 60), flush=True)
        time.sleep(30)
    else:
        print("timed out")
        return
    c.download_job(jid, grib)
    print("downloaded %.1f MB" % (os.path.getsize(grib) / 1e6), flush=True)

    recs = decode(grib)
    print("records:", len(recs), "units:", recs[0]["units"], flush=True)
    if not recs:
        return
    r0 = recs[0]
    lat, lon = r0["lat"], r0["lon"]
    units = (r0["units"] or "").lower()
    print("grid: %d lat x %d lon  lat %.2f..%.2f  lon %.2f..%.2f"
          % (len(lat), len(lon), lat.max(), lat.min(), lon.min(), lon.max()), flush=True)

    acc = {m: [] for m in (11, 12, 1, 2, 3, 4)}
    for r in recs:
        v = r["values"]
        # ERA5 monthly-mean snowfall is a RATE.  'm s-1' -> mm over the month;
        # 'kg m-2 s-1' is numerically the same as mm s-1, so no x1000.
        if "m s" in units and "kg" not in units:
            mult = 1000.0
        elif "kg m" in units:
            mult = 1.0
        else:
            raise SystemExit("unknown snowfall units: %r" % units)
        days = [31, 31, 29, 31, 30, 31][r["month"] - 1]
        if r["month"] in (11, 12):
            days = 30 if r["month"] == 11 else 31
        else:
            days = [0, 31, 28, 31, 30, 31][r["month"] - 1]
        acc[r["month"]].append(v * days * 86400.0 * mult)
    clim = np.stack([np.mean(np.array(acc[m]), axis=0) for m in (11, 12, 1, 2, 3, 4)])
    np.savez_compressed(OUT, clim=clim, lat=lat, lon=lon,
                        months=np.array([11, 12, 1, 2, 3, 4]),
                        years=np.array([1991, 2020]))
    os.remove(grib)
    print("saved", OUT, clim.shape, flush=True)
    print("CONUS-ish max per month (mm):",
          np.round(clim.reshape(6, -1).max(axis=1), 1), flush=True)


if __name__ == "__main__":
    main()
