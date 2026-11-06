"""Fetch the SEAS5 SUBDAILY (original) product and reduce it to a daily 12Z
zonal-mean u series at 10 hPa for 60N and the NH.

This is the product that reproduces the published chart: daily member values
(hence the realistic daily spread) over the full 7-month window, e.g. an
init on 1 Oct 2026 covers 01 Oct 2026 -> 02 May 2027 at 12Z.

Same traps as the monthly product:
  * system=51 (not 5)
  * NO "area" (the retrieval fails with MarsNoDataError if you pass one)
  * the grid is 1.00 deg centred on half-degrees -> interpolate 60N
  * init date = year/month/day of the run

usage: python3 fetch_seas5_daily.py --year 2026 --month 11 [--day 01]
"""
import os, sys, json, time, argparse
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

DATASET = "seasonal-original-pressure-levels"
URL = "https://cds.climate.copernicus.eu/api"
SYSTEM = 51
N_DAYS = 215          # 12Z daily from day 1 12Z -> day 215 12Z (~7 months)


def get_client():
    key = os.environ.get("CDS_KEY", "").strip()
    if not key:
        rc = os.path.join(HERE, ".cdsapirc")
        if os.path.exists(rc):
            for line in open(rc):
                if line.strip().startswith("key:"):
                    key = line.split(":", 1)[1].strip()
    if not key:
        sys.exit("No CDS key: set CDS_KEY or create %s" % os.path.join(HERE, ".cdsapirc"))
    import cdsapi
    return cdsapi.Client(url=URL, key=key, progress=True)


def daily_hours(n_days=N_DAYS):
    """leadtime_hour for a 12Z daily series (init 00Z -> +12 h is day 1 12Z)."""
    return [str(12 + 24 * k) for k in range(n_days)]


def decode_grib(path):
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
                member = int(g("perturbationNumber", 0))
                step = int(g("step", 0))
                valid = int(g("date"))
                ni = int(g("Ni")); nj = int(g("Nj"))
                first = float(g("latitudeOfFirstGridPointInDegrees"))
                last = float(g("latitudeOfLastGridPointInDegrees"))
                vals = np.asarray(eccodes.codes_get_array(gid, "values"), dtype=np.float64)
                if vals.size < ni * nj:
                    continue
                lats = np.linspace(first, last, nj) if nj > 1 else np.array([first])
                zonal = vals[: ni * nj].reshape(nj, ni).mean(axis=1)
                out.append(dict(member=member, step=step, valid=valid,
                                lat=lats, zonal=zonal))
            finally:
                eccodes.codes_release(gid)
    return out


def pick60(lats, zonal):
    lats = np.asarray(lats, dtype=float); zonal = np.asarray(zonal, dtype=float)
    o = np.argsort(lats); ls, zs = lats[o], zonal[o]
    if np.any(np.isclose(ls, 60.0, atol=1e-6)):
        return float(zs[int(np.argmin(np.abs(ls - 60.0)))])
    return float(np.interp(60.0, ls, zs))


def nh_mean(lats, zonal):
    lats = np.asarray(lats); zonal = np.asarray(zonal)
    m = lats >= -0.001
    w = np.cos(np.deg2rad(lats[m]))
    return float((zonal[m] * w).sum() / w.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--month", type=int, default=11)
    ap.add_argument("--day", default="01")
    ap.add_argument("--days", type=int, default=N_DAYS)
    ap.add_argument("--probe-only", action="store_true")
    args = ap.parse_args()
    y, m = args.year, args.month
    tag = "%04d%02d" % (y, m)
    hours = daily_hours(args.days)
    client = get_client()

    def request(hs, target):
        req = {"originating_centre": "ecmwf", "system": SYSTEM,
               "variable": "u_component_of_wind", "pressure_level": "10",
               "year": str(y), "month": "%02d" % m, "day": args.day,
               "leadtime_hour": hs, "data_format": "grib"}
        print("request ->", os.path.basename(target), "steps:", len(hs), flush=True)
        client.retrieve(DATASET, req, target)

    if args.probe_only:
        request(hours[:2], os.path.join(DATA, "seas5_%s_daily_probe.grib" % tag))
        return

    target = os.path.join(DATA, "seas5_%s_daily.grib" % tag)
    if not (os.path.exists(target) and os.path.getsize(target) > 1000):
        request(hours, target)
    print("grib bytes:", os.path.getsize(target), flush=True)

    recs = decode_grib(target)
    mem = sorted({r["member"] for r in recs})
    steps = sorted({r["step"] for r in recs})
    print("fields", len(recs), "members", len(mem), "steps", len(steps), flush=True)
    n60 = np.full((len(mem), len(steps)), np.nan)
    nnh = np.full((len(mem), len(steps)), np.nan)
    smap = {s: i for i, s in enumerate(steps)}
    for r in recs:
        mi = mem.index(r["member"]); li = smap[r["step"]]
        n60[mi, li] = pick60(r["lat"], r["zonal"])
        nnh[mi, li] = nh_mean(r["lat"], r["zonal"])
    np.savez_compressed(os.path.join(DATA, "seas5_%s_daily.npz" % tag),
                        members60=n60, members_nh=nnh,
                        member_numbers=np.array(mem), steps=np.array(steps))
    print("saved daily npz", n60.shape, flush=True)
    ens = np.nanmean(n60, axis=0)
    print("daily ensemble mean @60N (first 8):", np.round(ens[:8], 2), flush=True)
    print("daily ensemble mean @60N (last 5):", np.round(ens[-5:], 2), flush=True)


if __name__ == "__main__":
    main()
