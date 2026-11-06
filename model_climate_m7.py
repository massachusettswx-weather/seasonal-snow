"""Compute the ECMWF-style model climate for LEAD MONTH 7 of a given init month.

The CDS monthly-statistics product only carries lead months 1-6, so the 7th
month of the model-climate line has to be reconstructed the way ECMWF does it:
average the run's own ensemble mean over a set of past runs started in the
SAME calendar month.

For every past init we pull the subdaily (original) product for the daily 12Z
steps of month 7 only, compute the 60N / NH ensemble mean, and average those
means over the past runs -> the model climate for that calendar month.

usage: python3 model_climate_m7.py --month 10 --years 2016-2025
"""
import os, sys, json, argparse, datetime
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)
DATASET = "seasonal-original-pressure-levels"
URL = "https://cds.climate.copernicus.eu/api"
SYSTEM = 51


def client():
    key = os.environ.get("CDS_KEY", "").strip()
    if not key:
        rc = os.path.join(HERE, ".cdsapirc")
        if os.path.exists(rc):
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
                member = int(g("perturbationNumber", 0)); step = int(g("step", 0))
                ni = int(g("Ni")); nj = int(g("Nj"))
                first = float(g("latitudeOfFirstGridPointInDegrees"))
                last = float(g("latitudeOfLastGridPointInDegrees"))
                vals = np.asarray(eccodes.codes_get_array(gid, "values"), dtype=np.float64)
                if vals.size < ni * nj:
                    continue
                lats = np.linspace(first, last, nj) if nj > 1 else np.array([first])
                zonal = vals[: ni * nj].reshape(nj, ni).mean(axis=1)
                recs.append((member, step, lats, zonal))
            finally:
                eccodes.codes_release(gid)
    return recs


def reduce60(lats, zonal):
    lats = np.asarray(lats); zonal = np.asarray(zonal)
    o = np.argsort(lats); ls, zs = lats[o], zonal[o]
    if np.any(np.isclose(ls, 60.0, atol=1e-6)):
        return float(zs[int(np.argmin(np.abs(ls - 60.0)))])
    return float(np.interp(60.0, ls, zs))


def reduce_nh(lats, zonal):
    lats = np.asarray(lats); zonal = np.asarray(zonal)
    m = lats >= -0.001
    w = np.cos(np.deg2rad(lats[m]))
    return float((zonal[m] * w).sum() / w.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument("--years", default="2016-2025")
    ap.add_argument("--days", type=int, default=0, help="override month-7 length")
    ap.add_argument("--lead-month", type=int, default=7, help="lead month to reconstruct")
    args = ap.parse_args()
    y0, y1 = [int(x) for x in args.years.split("-")]
    c = client()
    series60, seriesnh = [], []
    for y in range(y0, y1 + 1):
        tag = "%04d%02d" % (y, args.month)
        out_npz = os.path.join(DATA, "m7_%s.npz" % tag)
        if os.path.exists(out_npz):
            d = np.load(out_npz); series60.append(d["m60"]); seriesnh.append(d["mnh"])
            print("cached", tag, flush=True); continue
        import calendar
        # lead month 7 starts (lead_month-1) months after the init month
        m_start = args.month + (args.lead_month - 1)
        y_start = y + (m_start - 1) // 12
        m_start = (m_start - 1) % 12 + 1
        offset_days = (datetime.date(y_start, m_start, 1) - datetime.date(y, args.month, 1)).days
        n_days = args.days or calendar.monthrange(y_start, m_start)[1]
        hours = [str(offset_days * 24 + 12 + 24 * k) for k in range(n_days)]
        print("  lead month %d starts %s, %d daily steps, first lead %s h"
              % (args.lead_month, "%04d-%02d" % (y_start, m_start), n_days, hours[0]), flush=True)
        target = os.path.join(DATA, "m7_%s.grib" % tag)
        req = {"originating_centre": "ecmwf", "system": SYSTEM,
               "variable": "u_component_of_wind", "pressure_level": "10",
               "year": str(y), "month": "%02d" % args.month, "day": "01",
               "leadtime_hour": hours, "data_format": "grib"}
        print("request m7", tag, flush=True)
        for attempt in range(6):
            try:
                c.retrieve(DATASET, req, target)
                break
            except Exception as e:
                msg = str(e)
                if ("Maximum number queued" in msg or "HTTPError: 400" in msg
                        or "Bad Request" in msg) and attempt < 5:
                    wait = 90 * (attempt + 1)
                    print("  queued-limit, retry in %ds: %s" % (wait, msg.splitlines()[-1][:90]),
                          flush=True)
                    import time as _t; _t.sleep(wait)
                    continue
                raise
        recs = decode(target)
        mem = sorted({r[0] for r in recs}); steps = sorted({r[1] for r in recs})
        want = sorted(int(h) for h in hours)
        if steps != want:
            raise RuntimeError("CDS returned steps %s ... != requested %s ..."
                               % (steps[:3], want[:3]))
        m60 = np.full((len(mem), len(steps)), np.nan); mnh = np.full_like(m60, np.nan)
        smap = {s: i for i, s in enumerate(steps)}
        for member, step, lats, zonal in recs:
            mi = mem.index(member); li = smap[step]
            m60[mi, li] = reduce60(lats, zonal); mnh[mi, li] = reduce_nh(lats, zonal)
        e60 = np.nanmean(m60, axis=0); enh = np.nanmean(mnh, axis=0)
        np.savez_compressed(out_npz, m60=e60, mnh=enh, steps=np.array(steps))
        series60.append(e60); seriesnh.append(enh)
        os.remove(target)
        print("  ens mean (first 5):", np.round(e60[:5], 2), flush=True)
    cl60 = np.nanmean(np.array(series60), axis=0)
    clnh = np.nanmean(np.array(seriesnh), axis=0)
    mp = os.path.join(DATA, "model_clim_m7_month%02d.npz" % args.month)
    np.savez_compressed(mp, clim60=cl60, clim_nh=clnh, nyears=len(series60))
    print("model climate month-7 for init month", args.month, "over", len(series60), "runs")
    print("  60N daily (first 5):", np.round(cl60[:5], 2))
    print("  60N monthly mean:", round(float(np.nanmean(cl60)), 2))


if __name__ == "__main__":
    main()
