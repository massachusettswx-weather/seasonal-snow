"""Fetch the OFFICIAL ERA5 monthly snowfall climatology (1991-2020) from CDS.

Dataset: reanalysis-era5-single-levels-monthly-means
         product_type = monthly_averaged_reanalysis, variable = snowfall

The CDS ERA5 queues are often saturated, so this retries patiently in the
background. Output (npz, same layout as data/era5_snow_clim_arco.npz):
    clim (6, nlat, nlon) mm per month for months 11,12,1,2,3,4
    lat, lon, months, years
"""
import os, sys, time, json, argparse
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DATASET = "reanalysis-era5-single-levels-monthly-means"
MONTHS = ["11", "12", "01", "02", "03", "04"]
AREA = [50, -127, 22, -64]          # N, W, S, E


def client():
    key = os.environ.get("CDS_KEY", "").strip()
    if not key:
        for line in open(os.path.join(HERE, ".cdsapirc")):
            if line.strip().startswith("key:"):
                key = line.split(":", 1)[1].strip()
    import cdsapi
    return cdsapi.Client(url="https://cds.climate.copernicus.eu/api", key=key, progress=False)


def decode(path):
    """-> list of (year, month, lat_desc, lon, values[lat,lon], units)"""
    import eccodes
    out = []
    with open(path, "rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            try:
                def g(k, d=None):
                    try:
                        return eccodes.codes_get(gid, k)
                    except Exception:
                        return d
                ni, nj = int(g("Ni")), int(g("Nj"))
                vals = np.asarray(eccodes.codes_get_array(gid, "values"), dtype=np.float64)
                out.append(dict(year=int(g("year")), month=int(g("month")),
                                 ni=ni, nj=nj,
                                 lat_first=float(g("latitudeOfFirstGridPointInDegrees")),
                                 lat_last=float(g("latitudeOfLastGridPointInDegrees")),
                                 lon_first=float(g("longitudeOfFirstGridPointInDegrees")),
                                 lon_last=float(g("longitudeOfLastGridPointInDegrees")),
                                 units=g("units", ""), vals=vals[:ni * nj].reshape(nj, ni)))
            finally:
                eccodes.codes_release(gid)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=DATASET)
    ap.add_argument("--out", default="era5_snow_clim_cds.npz")
    ap.add_argument("--tries", type=int, default=40)
    ap.add_argument("--sleep", type=int, default=120)
    args = ap.parse_args()
    out_npz = os.path.join(DATA, args.out)
    if os.path.exists(out_npz):
        print("already have", out_npz)
        return
    grib = os.path.join(DATA, args.out.replace(".npz", ".grib"))
    c = client()
    req = {"product_type": "monthly_averaged_reanalysis", "variable": ["snowfall"],
           "year": [str(y) for y in range(1991, 2021)], "month": MONTHS,
           "time": "00:00", "area": AREA, "data_format": "grib"}
    ok = False
    for attempt in range(args.tries):
        try:
            print("[%s] attempt %d -> request" % (time.strftime("%H:%M:%S"), attempt + 1),
                  flush=True)
            c.retrieve(args.dataset, req, grib)
            ok = True
            break
        except Exception as e:
            msg = str(e).replace("\n", " ")[:200]
            print("   failed:", msg, flush=True)
            time.sleep(args.sleep)
    if not ok:
        print("GAVE UP after %d attempts" % args.tries, flush=True)
        return

    recs = decode(grib)
    print("records:", len(recs), "units:", recs[0]["units"] if recs else "?", flush=True)
    if not recs:
        return
    r0 = recs[0]
    lat = np.linspace(r0["lat_first"], r0["lat_last"], r0["nj"])
    lon = np.linspace(r0["lon_first"], r0["lon_last"], r0["ni"])
    units = (r0["units"] or "").lower()
    # 'snowfall' in ERA5 monthly means is a rate (kg m-2 s-1) -> monthly total in mm
    rate_like = ("s-1" in units or "s**-1" in units)

    def month_len(y, m):
        return [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]

    clim = np.zeros((6,) + lat.shape)
    for mi, mm in enumerate([11, 12, 1, 2, 3, 4]):
        stack = []
        for rec in recs:
            if rec["month"] != mm:
                continue
            v = rec["vals"]
            if rec["lat_first"] < rec["lat_last"]:
                v = v[::-1, :]
            if rate_like:
                v = v * month_len(rec["year"], mm) * 86400.0 * 1000.0     # kg m-2 -> mm
            else:
                v = v * 1000.0                                            # kg m-2 -> mm
            stack.append(v)
        clim[mi] = np.mean(stack, axis=0)
        print("  month %2d: %d years, mean %.2f mm" % (mm, len(stack), clim[mi].mean()),
              flush=True)

    np.savez_compressed(out_npz, clim=clim.astype(np.float32), lat=lat, lon=lon,
                        months=np.array([11, 12, 1, 2, 3, 4]),
                        years=np.array([1991, 2020]))
    print("wrote", out_npz, flush=True)
    os.remove(grib)


if __name__ == "__main__":
    main()
