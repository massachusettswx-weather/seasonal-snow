"""Fetch ECMWF SEAS5 from the Copernicus CDS and reduce it to the zonal-mean
zonal wind (u) at 10 hPa for 60N and for the NH (0-90N).

Notes learned the hard way:
  * system=51 is the current SEAS5 version in C3S (since Nov 2022). system=5 is
    retired for real-time data -> "MarsNoDataError" for recent inits.
  * Do NOT pass "area": the CDS seasonal retrieval fails (NoData) with an area
    selection. The global 1.00 deg grid comes back instead (60N is a grid point).
  * ECMWF's seasonal contribution is released on the 6th of each month at 12 UTC.
    Before that, the current init returns
    "AccessError: Restricted access to current C3S seasonal forecast ECMWF contribution".
  * product_type: monthly_mean = the 51 individual members,
                  ensemble_mean = the ensemble mean,
                  hindcast_climate_mean = ECMWF's model climate mean (HCMEAN).

Token: env CDS_KEY, or `key:` in /workspace/seas5/.cdsapirc
Outputs: data/seas5_<init>_u10.npz, data/seas5_<init>_clim.npz
"""
import os, sys, json, time, argparse
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

DATASET = "seasonal-monthly-pressure-levels"
URL = "https://cds.climate.copernicus.eu/api"
LEADS = list(range(1, 7))      # this dataset exposes lead months 1-6
SYSTEM = 51


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


def base_req(product_type, year, month, leads=LEADS):
    return {
        "originating_centre": "ecmwf",
        "system": SYSTEM,
        "variable": "u_component_of_wind",
        "pressure_level": "10",
        "product_type": product_type,
        "year": str(year),
        "month": "%02d" % month,
        "leadtime_month": [str(x) for x in leads],
        "data_format": "grib",
    }


def retrieve(client, req, target):
    if os.path.exists(target) and os.path.getsize(target) > 1000:
        print("exists, skip:", target, flush=True)
        return target
    print("request ->", os.path.basename(target), json.dumps(req), flush=True)
    for attempt in range(3):
        try:
            client.retrieve(DATASET, req, target)
            if os.path.exists(target) and os.path.getsize(target) > 1000:
                return target
        except Exception as e:
            msg = str(e)
            brief = [l for l in msg.split("\n") if ("ERROR" in l or "NoData" in l or "Access" in l)]
            print("  attempt %d failed: %s" % (attempt + 1, (brief[0][:160] if brief else msg[:160])),
                  flush=True)
            if "Restricted access to current" in msg:
                raise
            time.sleep(10 * (attempt + 1))
    raise RuntimeError("download failed: " + target)


def decode_grib(path):
    """-> list of dicts: member, ref, valid, lat, zonal profile."""
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
                valid = int(g("date"))
                ref = g("forecastReferenceDate")
                ref = int(ref) if ref else None
                step = int(g("step", 0))       # cumulative hours to the lead month's end
                ni = int(g("Ni")); nj = int(g("Nj"))
                first = float(g("latitudeOfFirstGridPointInDegrees"))
                last = float(g("latitudeOfLastGridPointInDegrees"))
                vals = np.asarray(eccodes.codes_get_array(gid, "values"), dtype=np.float64)
                if vals.size < ni * nj:
                    raise RuntimeError("short field")
                lats = np.linspace(first, last, nj) if nj > 1 else np.array([first])
                zonal = vals[: ni * nj].reshape(nj, ni).mean(axis=1)
                out.append(dict(member=member, ref=ref, valid=valid, step=step,
                                lat=lats, zonal=zonal))
            finally:
                eccodes.codes_release(gid)
    return out


def pick60(lats, zonal):
    """Value at 60N.

    The SEAS5 1.00 deg grid is centred on half-degrees (89.5 ... 0.5 ... -89.5),
    so 60N is generally NOT a grid point -> linear interpolation. The latitude
    axis runs north -> south, but np.interp needs it ascending.
    """
    lats = np.asarray(lats, dtype=float)
    zonal = np.asarray(zonal, dtype=float)
    order = np.argsort(lats)
    lats_s, zonal_s = lats[order], zonal[order]
    if np.any(np.isclose(lats_s, 60.0, atol=1e-6)):
        return float(zonal_s[int(np.argmin(np.abs(lats_s - 60.0)))])
    return float(np.interp(60.0, lats_s, zonal_s))


def nh_mean(lats, zonal):
    lats = np.asarray(lats); zonal = np.asarray(zonal)
    m = lats >= -0.001
    w = np.cos(np.deg2rad(lats[m]))
    return float((zonal[m] * w).sum() / w.sum())


def lead_map(recs):
    """Map each record to its lead month (1..6).

    The seasonal GRIBs carry no forecastReferenceDate; the validity date stays
    on the init date and the lead is encoded in "step" (cumulative hours to the
    end of each lead month). Ranking the distinct steps gives the lead index.
    """
    steps = sorted({r["step"] for r in recs})
    return {s: i for i, s in enumerate(steps)}, steps


def series_from(recs, nlead=6):
    v60 = np.full(nlead, np.nan); vnh = np.full(nlead, np.nan)
    smap, steps = lead_map(recs)
    for r in recs:
        li = smap.get(r["step"], -1)
        if not (0 <= li < nlead):
            continue
        v60[li] = pick60(r["lat"], r["zonal"])
        vnh[li] = nh_mean(r["lat"], r["zonal"])
    return v60, vnh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--month", type=int, default=11)
    args = ap.parse_args()
    y, m = args.year, args.month
    tag = "%04d%02d" % (y, m)
    client = get_client()

    # ---------- individual members ----------------------------------------
    t_mem = os.path.join(DATA, "seas5_%s_members.grib" % tag)
    retrieve(client, base_req("monthly_mean", y, m), t_mem)
    recs = decode_grib(t_mem)
    print("decoded", len(recs), "member fields", flush=True)
    memnums = sorted({r["member"] for r in recs})
    print("member numbers:", memnums[:4], "...", memnums[-2:], "n =", len(memnums), flush=True)
    lats = np.asarray(recs[0]["lat"])
    nlat = len(lats)
    print("grid: %d lat rows, %.2f..%.2f" % (nlat, lats.max(), lats.min()), flush=True)
    smap, steps = lead_map(recs)
    print("lead steps (h):", steps, flush=True)
    m60 = np.full((len(memnums), len(steps)), np.nan)
    mnh = np.full((len(memnums), len(steps)), np.nan)
    for r in recs:
        mi = memnums.index(r["member"])
        li = smap.get(r["step"], -1)
        if 0 <= li < len(steps):
            m60[mi, li] = pick60(r["lat"], r["zonal"])
            mnh[mi, li] = nh_mean(r["lat"], r["zonal"])
    np.savez_compressed(os.path.join(DATA, "seas5_%s_u10.npz" % tag),
                        members60=m60, members_nh=mnh,
                        member_numbers=np.array(memnums), lats=lats)
    print("members60", m60.shape, "| ensemble mean per lead:",
          np.round(np.nanmean(m60, axis=0), 2), flush=True)

    # ---------- ensemble mean + model climate mean ------------------------
    t_ens = os.path.join(DATA, "seas5_%s_ensmean.grib" % tag)
    retrieve(client, base_req("ensemble_mean", y, m), t_ens)
    e60, enh = series_from(decode_grib(t_ens))
    print("ensemble mean 60N:", np.round(e60, 2), flush=True)

    t_hcm = os.path.join(DATA, "seas5_%s_hcmmean.grib" % tag)
    retrieve(client, base_req("hindcast_climate_mean", y, m), t_hcm)
    h60, hnh = series_from(decode_grib(t_hcm))
    print("model climate 60N:", np.round(h60, 2), flush=True)

    np.savez_compressed(os.path.join(DATA, "seas5_%s_clim.npz" % tag),
                        ens60=e60, ens_nh=enh, clim60=h60, clim_nh=hnh)
    print("done", flush=True)


if __name__ == "__main__":
    main()
