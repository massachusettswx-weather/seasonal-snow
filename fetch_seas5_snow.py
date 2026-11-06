"""Pull SEAS5 monthly-mean snowfall for a seasonal init and reduce it to a
numpy array: [member, lead_month, lat, lon] in m w.e. s-1.

dataset: seasonal-monthly-single-levels (1.00 deg global, no `area` allowed)
variable: snowfall  (m of water equivalent s**-1)
"""
import os, sys, argparse, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DATASET = "seasonal-monthly-single-levels"
URL = "https://cds.climate.copernicus.eu/api"
SYSTEM = 51
LEADS = ["1", "2", "3", "4", "5", "6"]


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
    recs = []
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
                member = int(g("perturbationNumber", 0))
                step = int(g("step", 0))
                ni = int(g("Ni")); nj = int(g("Nj"))
                first = float(g("latitudeOfFirstGridPointInDegrees"))
                last = float(g("latitudeOfLastGridPointInDegrees"))
                vals = np.asarray(eccodes.codes_get_array(gid, "values"), dtype=np.float64)
                recs.append((member, step, first, last, vals[:ni * nj].reshape(nj, ni)))
            finally:
                eccodes.codes_release(gid)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--month", type=int, default=11)
    args = ap.parse_args()
    tag = "%04d%02d" % (args.year, args.month)
    out_npz = os.path.join(DATA, "seas5_%s_snow.npz" % tag)
    if os.path.exists(out_npz):
        print("already have", out_npz)
        return

    c = client()
    target = os.path.join(DATA, "seas5_%s_snow.grib" % tag)
    req = {"originating_centre": "ecmwf", "system": SYSTEM, "variable": "snowfall",
           "product_type": "monthly_mean", "year": str(args.year),
           "month": "%02d" % args.month, "leadtime_month": LEADS, "data_format": "grib"}
    for attempt in range(5):
        try:
            print("request ->", target, flush=True)
            c.retrieve(DATASET, req, target)
            break
        except Exception as e:
            msg = str(e)
            if attempt < 4 and ("Maximum number queued" in msg or "Bad Request" in msg
                                or "HTTPError" in msg):
                wait = 90 * (attempt + 1)
                print("  retry in %ds" % wait, flush=True)
                time.sleep(wait)
                continue
            raise

    recs = decode(target)
    members = sorted({r[0] for r in recs})
    steps = sorted({r[1] for r in recs})
    lat = np.linspace(recs[0][2], recs[0][3], recs[0][4].shape[0])   # north -> south
    arr = np.full((len(members), len(steps), lat.size, recs[0][4].shape[1]), np.nan)
    smap = {s: i for i, s in enumerate(steps)}
    for member, step, f0, l0, field in recs:
        arr[members.index(member), smap[step]] = field
    lon = (np.arange(recs[0][4].shape[1]) + 0.5)
    np.savez_compressed(out_npz, rates=arr.astype(np.float32), lat=lat, lon=lon,
                        members=np.array(members), steps=np.array(steps))
    os.remove(target)
    mm = arr.mean(axis=0) * 1000 * 30 * 86400
    print("saved", out_npz, arr.shape)
    print("global monthly mean snowfall (mm/month) per lead:", np.round(mm.mean(axis=(1, 2)), 3))


if __name__ == "__main__":
    main()
