"""Probe the CDS seasonal monthly single-levels dataset for available systems
and their native grid resolution, for a given init.

Prints: system -> status, Ni/Nj, grid spacing in degrees, lead months served.
"""
import os, sys, json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DATASET = "seasonal-monthly-single-levels"


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
                out.append(dict(member=int(g("perturbationNumber", 0)), step=int(g("step", 0)),
                                ni=int(g("Ni")), nj=int(g("Nj")),
                                first=float(g("latitudeOfFirstGridPointInDegrees")),
                                last=float(g("latitudeOfLastGridPointInDegrees")),
                                dx=float(g("iDirectionIncrementInDegrees", 0)),
                                dy=float(g("jDirectionIncrementInDegrees", 0))))
            finally:
                eccodes.codes_release(gid)
    return out


def probe(c, system, year, month, leads, var="snowfall"):
    tgt = os.path.join(DATA, f"probe_{system}_{var}.grib")
    req = {"originating_centre": "ecmwf", "system": system, "variable": var,
           "product_type": "monthly_mean", "year": str(year), "month": "%02d" % month,
           "leadtime_month": leads, "data_format": "grib"}
    try:
        c.retrieve(DATASET, req, tgt)
    except Exception as e:
        msg = str(e).replace("\n", " ")[:220]
        print(f"system={system}: FAILED {msg}", flush=True)
        return None
    recs = decode(tgt)
    if not recs:
        print(f"system={system}: empty", flush=True)
        return None
    r = recs[0]
    print(f"system={system}: OK  Ni={r['ni']} Nj={r['nj']} dx={r['dx']} dy={r['dy']} "
          f"lat {r['first']}->{r['last']}  members={len(set(x['member'] for x in recs))} "
          f"steps={sorted(set(x['step'] for x in recs))}", flush=True)
    os.remove(tgt)
    return r


if __name__ == "__main__":
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    month = int(sys.argv[2]) if len(sys.argv) > 2 else 11
    c = client()
    for system in ["51", "6"]:
        probe(c, system, year, month, ["1"])
