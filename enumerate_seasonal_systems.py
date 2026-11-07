"""Enumerate every (originating_centre, system) pair that actually serves data
for a recent seasonal init, using the cheap 1-step original products.

Writes data/seasonal_systems_probe.json:
    "<centre>:<system>" -> { centre, system, snowfall: {...}, u10: {...} }
where each entry records members, grid, and the init that served it.
"""
import os, sys, json, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
API = "https://cds.climate.copernicus.eu/api"
PATH = os.path.join(DATA, "seasonal_systems_probe.json")

CENTRES = ["ecmwf", "ukmo", "meteo_france", "dwd", "cmcc", "ncep", "jma", "eccc", "bom"]
SYSTEMS = ["51", "1", "2", "3", "4", "5", "6", "7", "8", "9", "12", "13", "14", "15",
           "21", "22", "35", "600", "601", "602", "603", "604", "605", "610"]
INITS = [("2026", "11"), ("2026", "10")]


def client():
    key = os.environ.get("CDS_KEY", "").strip()
    if not key:
        for line in open(os.path.join(HERE, ".cdsapirc")):
            if line.strip().startswith("key:"):
                key = line.split(":", 1)[1].strip()
    import cdsapi
    return cdsapi.Client(url=API, key=key, progress=False)


def decode(path):
    import eccodes
    members, ni, nj, dx, dy, first, last = set(), 0, 0, 0.0, 0.0, 0.0, 0.0
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
                members.add(int(g("perturbationNumber", 0)))
                ni, nj = int(g("Ni")), int(g("Nj"))
                dx = float(g("iDirectionIncrementInDegrees", 0))
                dy = float(g("jDirectionIncrementInDegrees", 0))
                first = float(g("latitudeOfFirstGridPointInDegrees"))
                last = float(g("latitudeOfLastGridPointInDegrees"))
            finally:
                eccodes.codes_release(gid)
    return dict(members=len(members), ni=ni, nj=nj, dx=dx, dy=dy, first=first, last=last)


def probe(c, centre, system, dataset, variable, extra=None):
    for (yr, mo) in INITS:
        target = os.path.join(DATA, "probe_%s_%s.grib" % (centre, system))
        req = {"originating_centre": centre, "system": system, "variable": variable,
               "year": yr, "month": mo, "day": "01",
               "leadtime_hour": ["12"], "data_format": "grib"}
        if extra:
            req.update(extra)
        try:
            c.retrieve(dataset, req, target)
        except Exception:
            if os.path.exists(target):
                os.remove(target)
            continue
        try:
            info = decode(target)
        finally:
            os.remove(target)
        info["init"] = "%s-%s" % (yr, mo)
        return info
    return None


def main():
    c = client()
    out = {}
    if os.path.exists(PATH):
        try:
            out = json.load(open(PATH))
        except Exception:
            out = {}
    only = sys.argv[1] if len(sys.argv) > 1 else "all"
    for centre in CENTRES:
        for system in SYSTEMS:
            key = "%s:%s" % (centre, system)
            rec = out.setdefault(key, {"centre": centre, "system": system})
            if only in ("snow", "all") and "snowfall" not in rec:
                info = probe(c, centre, system, "seasonal-original-single-levels", "snowfall")
                if info:
                    rec["snowfall"] = info
                    print("%-14s snow  members=%2d %dx%d dx=%.2f init=%s"
                          % (key, info["members"], info["ni"], info["nj"],
                             info["dx"], info["init"]), flush=True)
            if only in ("u", "all") and "u10" not in rec:
                info = probe(c, centre, system, "seasonal-original-pressure-levels",
                             "u_component_of_wind", {"pressure_level": "10"})
                if info:
                    rec["u10"] = info
                    print("%-14s u10   members=%2d %dx%d dx=%.2f init=%s"
                          % (key, info["members"], info["ni"], info["nj"],
                             info["dx"], info["init"]), flush=True)
            with open(PATH, "w") as f:
                json.dump(out, f, indent=1)
    live = {k: v for k, v in out.items() if "snowfall" in v or "u10" in v}
    print("DONE - %d live systems" % len(live))


if __name__ == "__main__":
    main()
