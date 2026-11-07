"""Probe the CDS seasonal datasets: which (centre, system) pairs actually serve
data for the 1 Nov 2026 init, how many members each has, its grid, and which
variables are available.

Cheap probe: leadtime_month = 1 only (the monthly products return every member,
so one lead month is the smallest possible request).
"""
import os, sys, json, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
API = "https://cds.climate.copernicus.eu/api"

EXTRA_SYSTEMS = [("ncep", s) for s in ("9", "12", "13", "14", "15", "21", "22", "35",
                                       "600", "601", "602", "603", "604", "605", "610")] + \
                [("eccc", s) for s in ("3", "4", "5")] + \
                [("ukmo", s) for s in ("4", "5", "6")] + \
                [("meteo_france", s) for s in ("4", "5", "6", "7")] + \
                [("bom", s) for s in ("3", "4", "5")] + \
                [("jma", s) for s in ("3", "4", "5")] + \
                [("cmcc", s) for s in ("3", "4", "5")] + \
                [("dwd", s) for s in ("3", "4", "5")]

EXTRA_SYSTEMS = [("ncep", s) for s in ("9", "12", "13", "14", "15", "21", "22", "35",
                                       "600", "601", "602", "603", "604", "605", "610")] + \
                [("eccc", s) for s in ("3", "4", "5")] + \
                [("ukmo", s) for s in ("4", "5", "6")] + \
                [("meteo_france", s) for s in ("4", "5", "6", "7")] + \
                [("bom", s) for s in ("3", "4", "5")] + \
                [("jma", s) for s in ("3", "4", "5")] + \
                [("cmcc", s) for s in ("3", "4", "5")] + \
                [("dwd", s) for s in ("3", "4", "5")]

EXTRA_SYSTEMS = [("ncep", s) for s in ("9", "12", "13", "14", "15", "21", "22", "35",
                                       "600", "601", "602", "603", "604", "605", "610")] + \
                [("eccc", s) for s in ("3", "4", "5")] + \
                [("ukmo", s) for s in ("4", "5", "6")] + \
                [("meteo_france", s) for s in ("4", "5", "6", "7")] + \
                [("bom", s) for s in ("3", "4", "5")] + \
                [("jma", s) for s in ("3", "4", "5")] + \
                [("cmcc", s) for s in ("3", "4", "5")] + \
                [("dwd", s) for s in ("3", "4", "5")]

CANDIDATES = [
    ("ecmwf", "51"), ("ecmwf", "5"),
    ("ncep", "1"), ("ncep", "2"), ("ncep", "3"), ("ncep", "4"), ("ncep", "5"),
    ("ncep", "6"), ("ncep", "7"), ("ncep", "8"),
    ("ukmo", "1"), ("ukmo", "2"), ("ukmo", "3"),
    ("meteo_france", "1"), ("meteo_france", "2"), ("meteo_france", "3"),
    ("bom", "1"), ("bom", "2"),
    ("dwd", "1"), ("dwd", "2"),
    ("jma", "1"), ("jma", "2"),
    ("cmcc", "1"), ("cmcc", "2"),
    ("eccc", "1"), ("eccc", "2"),
]


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


def probe(c, centre, system, dataset, variable, extra=None, leads=("1",),
          inits=(("2026", "11"), ("2026", "10"))):
    """Try each init in turn (Nov 2026 first, then Oct 2026)."""
    for (yr, mo) in inits:
        info, err = _probe_one(c, centre, system, dataset, variable, extra,
                               leads, yr, mo)
        if info is not None:
            info["init"] = "%s-%s" % (yr, mo)
            return info, None
    return None, err


def _probe_one(c, centre, system, dataset, variable, extra=None, leads=("1",),
               yr="2026", mo="11"):
    tag = "%s_%s_%s" % (centre, system, variable)
    target = os.path.join(DATA, "probe_%s.grib" % tag)
    if "original" in dataset:
        req = {"originating_centre": centre, "system": system, "variable": variable,
               "year": yr, "month": mo, "day": "01",
               "leadtime_hour": ["12"], "data_format": "grib"}
    else:
        req = {"originating_centre": centre, "system": system, "variable": variable,
               "product_type": "monthly_mean", "year": yr, "month": mo,
               "leadtime_month": list(leads), "data_format": "grib"}
    if extra:
        req.update(extra)
    try:
        c.retrieve(dataset, req, target)
    except Exception as e:
        msg = str(e).replace("\n", " ")[:120]
        if os.path.exists(target):
            os.remove(target)
        return None, msg
    info = decode(target)
    os.remove(target)
    return info, None


WANT = ["snow"]


def main():
    import sys
    if len(sys.argv) > 1:
        WANT[0] = sys.argv[1]
    lo = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    hi = int(sys.argv[3]) if len(sys.argv) > 3 else len(CANDIDATES)
    c = client()
    path = os.path.join(DATA, "seasonal_systems_probe.json")
    out = {}
    if os.path.exists(path):
        out = json.load(open(path))
    pool = CANDIDATES if WANT[0] != "snow2" else EXTRA_SYSTEMS
    for centre, system in pool[lo:hi]:
        todo = [("seasonal-monthly-single-levels", "snowfall", None)] if WANT[0] == "snow2" \
            else [("seasonal-original-single-levels", "snowfall", None)]
        if WANT[0] in ("u", "both"):
            todo.append(("seasonal-original-pressure-levels", "u_component_of_wind",
                         {"pressure_level": "10"}))
        for dataset, variable, extra in todo:
            key = "%s:%s" % (centre, system)
            info, err = probe(c, centre, system, dataset, variable, extra)
            if info is None:
                if "Maximum number" in (err or ""):
                    print("%-14s %-22s QUEUE-BLOCKED" % (key, variable))
                continue
            rec = out.setdefault(key, {"centre": centre, "system": system})
            rec[variable] = info
            with open(path, "w") as f:
                json.dump(out, f, indent=1)
            print("%-14s %-22s init=%s members=%2d  %dx%d  dx=%.2f  lat %.1f->%.1f"
                  % (key, variable, info.get("init"), info["members"], info["ni"],
                     info["nj"], info["dx"], info["first"], info["last"]), flush=True)
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print("wrote", path, "-", len(out), "live systems")


if __name__ == "__main__":
    main()
