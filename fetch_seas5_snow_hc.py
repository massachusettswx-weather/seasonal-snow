"""Fetch the ECMWF SEAS5 snowfall products that define the anomaly baseline.

  * hindcast_climate_mean  -> ECMWF's own 30-year hindcast climatology for the
    lead month (the baseline ECMWF/C3S use for seasonal anomalies)
  * ensemble_mean          -> the ensemble-mean product (used to PROVE that the
    51 monthly_mean members we downloaded are genuine SEAS5)

dataset: seasonal-monthly-single-levels, system 51, variable snowfall
Requests are submitted sequentially (the CDS rejects parallel submissions).
"""
import os, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DATASET = "seasonal-monthly-single-levels"
SYSTEM = 51
LEADS = ["1", "2", "3", "4", "5", "6"]


def client():
    key = os.environ.get("CDS_KEY", "").strip()
    if not key:
        for line in open(os.path.join(HERE, ".cdsapirc")):
            if line.strip().startswith("key:"):
                key = line.split(":", 1)[1].strip()
    import cdsapi
    return cdsapi.Client(url="https://cds.climate.copernicus.eu/api", key=key, progress=False)


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
                ni, nj = int(g("Ni")), int(g("Nj"))
                vals = np.asarray(eccodes.codes_get_array(gid, "values"), dtype=np.float64)
                recs.append(dict(member=int(g("perturbationNumber", 0)), step=int(g("step", 0)),
                                 ni=ni, nj=nj,
                                 first=float(g("latitudeOfFirstGridPointInDegrees")),
                                 last=float(g("latitudeOfLastGridPointInDegrees")),
                                 vals=vals[:ni * nj].reshape(nj, ni)))
            finally:
                eccodes.codes_release(gid)
    return recs


def retrieve(c, product, target, tries=8):
    req = {"originating_centre": "ecmwf", "system": SYSTEM, "variable": "snowfall",
           "product_type": product, "year": "2026", "month": "11",
           "leadtime_month": LEADS, "data_format": "grib"}
    for attempt in range(tries):
        try:
            print("  request %s -> %s" % (product, os.path.basename(target)), flush=True)
            c.retrieve(DATASET, req, target)
            return True
        except Exception as e:
            msg = str(e).replace("\n", " ")[:180]
            print("   attempt %d failed: %s" % (attempt + 1, msg), flush=True)
            time.sleep(60 * (attempt + 1))
    return False


def main():
    c = client()
    tag = "202611"

    # ---- 1) hindcast climate mean (ECMWF's own climatology baseline)
    hc_grib = os.path.join(DATA, "seas5_%s_snow_hc.grib" % tag)
    hc_npz = os.path.join(DATA, "seas5_%s_snow_hc.npz" % tag)
    if not os.path.exists(hc_npz):
        if retrieve(c, "hindcast_climate_mean", hc_grib):
            recs = decode(hc_grib)
            r0 = recs[0]
            lat = np.linspace(r0["first"], r0["last"], r0["nj"])
            lon = np.arange(r0["ni"]) + 0.5
            arr = np.zeros((len(LEADS), r0["nj"], r0["ni"]))
            steps = []
            for rec in sorted(recs, key=lambda r: r["step"]):
                k = len(steps)
                steps.append(rec["step"])
                v = rec["vals"]
                if rec["first"] < rec["last"]:
                    v = v[::-1, :]
                arr[k] = v
            print("  hindcast steps:", steps, flush=True)
            np.savez_compressed(hc_npz, rates=arr.astype(np.float32), lat=lat, lon=lon,
                                steps=np.array(steps))
            print("wrote", hc_npz, arr.shape, flush=True)
            os.remove(hc_grib)

    # ---- 2) ensemble_mean -> provenance check against the 51 members
    em_grib = os.path.join(DATA, "seas5_%s_snow_em.grib" % tag)
    em_npz = os.path.join(DATA, "seas5_%s_snow_em.npz" % tag)
    if not os.path.exists(em_npz):
        if retrieve(c, "ensemble_mean", em_grib):
            recs = decode(em_grib)
            r0 = recs[0]
            lat = np.linspace(r0["first"], r0["last"], r0["nj"])
            lon = np.arange(r0["ni"]) + 0.5
            arr = np.zeros((len(LEADS), r0["nj"], r0["ni"]))
            steps = []
            for rec in sorted(recs, key=lambda r: r["step"]):
                k = len(steps)
                steps.append(rec["step"])
                v = rec["vals"]
                if rec["first"] < rec["last"]:
                    v = v[::-1, :]
                arr[k] = v
            print("  ensemble_mean steps:", steps, flush=True)
            np.savez_compressed(em_npz, rates=arr.astype(np.float32), lat=lat, lon=lon,
                                steps=np.array(steps))
            print("wrote", em_npz, arr.shape, flush=True)
            os.remove(em_grib)

    # ---- 3) provenance check
    mem = np.load(os.path.join(DATA, "seas5_%s_snow.npz" % tag))
    em = np.load(em_npz)
    mm = mem["rates"].mean(axis=0)
    ens = em["rates"]
    d = np.abs(mm - ens)
    print("PROVENANCE  mean(51 monthly_mean members) vs ensemble_mean:")
    print("   max abs diff %.3e m/s   mean abs diff %.3e" % (d.max(), d.mean()))
    scale = max(np.abs(ens).max(), 1e-30)
    print("   max |value| %.3e -> relative diff %.2e" % (scale, d.max() / scale))
    hc = np.load(hc_npz)
    for k in range(6):
        print("   lead %d: member-mean %.4e  ens_mean %.4e  hc_mean %.4e m w.e./s"
              % (k + 1, mm[k].mean(), ens[k].mean(), hc["rates"][k].mean()))


if __name__ == "__main__":
    main()
