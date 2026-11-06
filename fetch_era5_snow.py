"""ERA5 1991-2020 monthly snowfall climatology for the eastern U.S. box.

dataset: reanalysis-era5-single-levels, product_type monthly_averaged_reanalysis,
variable snowfall (kg m-2 s-1 -> the CDS monthly mean is an average rate, so
multiplying by the number of seconds in the month gives the monthly total in
mm water equivalent).

Saves clim[6, nlat, nlon] in mm/month for calendar months 11, 12, 1, 2, 3, 4.
"""
import os, sys, argparse, time, calendar
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DATASET = "reanalysis-era5-single-levels-monthly-means"
URL = "https://cds.climate.copernicus.eu/api"
MONTHS = [11, 12, 1, 2, 3, 4]


def client():
    key = os.environ.get("CDS_KEY", "").strip()
    if not key:
        rc = os.path.join(HERE, ".cdsapirc")
        for line in open(rc):
            if line.strip().startswith("key:"):
                key = line.split(":", 1)[1].strip()
    import cdsapi
    return cdsapi.Client(url=URL, key=key, progress=True)


def decode(path):
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
                ni = int(g("Ni")); nj = int(g("Nj"))
                first = float(g("latitudeOfFirstGridPointInDegrees"))
                last = float(g("latitudeOfLastGridPointInDegrees"))
                vals = np.asarray(eccodes.codes_get_array(gid, "values"), dtype=np.float64)
                out.append((int(g("year", 0)), int(g("month", 0)), first, last,
                            vals[:ni * nj].reshape(nj, ni)))
            finally:
                eccodes.codes_release(gid)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1991)
    ap.add_argument("--end", type=int, default=2020)
    ap.add_argument("--area", default="49,-100,24,-65", help="N,W,S,E")
    args = ap.parse_args()
    out_npz = os.path.join(DATA, "era5_snow_clim.npz")
    if os.path.exists(out_npz):
        print("already have", out_npz)
        return
    area = [float(x) for x in args.area.split(",")]
    c = client()
    target = os.path.join(DATA, "era5_snow_%d_%d.grib" % (args.start, args.end))
    req = {"product_type": "monthly_averaged_reanalysis", "variable": "snowfall",
           "year": [str(y) for y in range(args.start, args.end + 1)],
           "month": ["%02d" % m for m in MONTHS], "time": "00:00",
           "area": area, "data_format": "grib"}
    for attempt in range(8):
        try:
            print("request ->", target, flush=True)
            c.retrieve(DATASET, req, target)
            break
        except Exception as e:
            msg = str(e)
            print("  attempt %d failed: %s" % (attempt, msg.replace("\n", " ")[-200:]), flush=True)
            if attempt < 7 and ("Maximum number queued" in msg or "Bad Request" in msg
                                or "HTTPError" in msg or "ConnectionError" in msg):
                wait = 60 * (attempt + 1)
                print("  retry in %ds" % wait, flush=True)
                time.sleep(wait)
                continue
            raise

    recs = decode(target)
    lat = np.linspace(recs[0][2], recs[0][3], recs[0][4].shape[0])
    lon = None
    acc = {m: [] for m in MONTHS}
    for year, month, f0, l0, field in recs:
        if lon is None:
            ni = field.shape[1]
            lon = (np.arange(ni) + 0.125) * 0.25 + area[1]   # 0.25 deg, from the west edge
        secs = calendar.monthrange(year, month)[1] * 86400.0
        acc[month].append(field * 1000.0 * secs)             # mm w.e. for that month
    clim = np.stack([np.mean(acc[m], axis=0) for m in MONTHS])   # [6, nlat, nlon]
    np.savez_compressed(out_npz, clim=clim.astype(np.float32), lat=lat, lon=lon,
                        months=np.array(MONTHS), years=np.array([args.start, args.end]))
    os.remove(target)
    print("saved", out_npz, clim.shape)
    for i, m in enumerate(MONTHS):
        print("  month %02d: domain mean %.1f mm/month" % (m, clim[i].mean()))


if __name__ == "__main__":
    main()
