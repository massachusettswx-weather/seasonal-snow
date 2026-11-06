"""Enumerate the CDS seasonal datasets and work out which ones carry a snow
variable - this is the source list for the website's seasonal systems page.

Writes site/data/systems.json with one entry per seasonal dataset.
"""
import json, os, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
API = "https://cds.climate.copernicus.eu/api"

SNOW_KEYS = ("snowfall", "snow_depth", "snow_cover", "total_snow",
             "surface_snow", "snow_grain", "snow_convective")


def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=60).read().decode())


def enum(spec, key):
    try:
        return spec["inputs"][key]["schema"]["items"]["enum"]
    except Exception:
        return []


def main():
    cols = get("%s/catalogue/v1/collections?limit=2000" % API)
    seasonal = [c for c in cols.get("collections", [])
                if "seasonal" in (c.get("id", "") + c.get("title", "")).lower()]
    print("seasonal datasets:", len(seasonal))
    out = []
    for c in seasonal:
        did = c["id"]
        try:
            spec = get("%s/retrieve/v1/processes/%s" % (API, did))
        except Exception as e:
            print("  %-46s spec failed (%s)" % (did, str(e)[:40]))
            continue
        vars_ = enum(spec, "variable")
        snow = [v for v in vars_ if any(k in v for k in SNOW_KEYS)]
        systems = enum(spec, "system")
        centres = enum(spec, "originating_centre")
        ptypes = enum(spec, "product_type")
        rec = dict(id=did,
                   title=c.get("title", did),
                   description=(c.get("description") or "")[:400],
                   snow_variables=snow,
                   n_variables=len(vars_),
                   systems=systems,
                   centres=centres,
                   product_types=ptypes,
                   has_snow=bool(snow))
        out.append(rec)
        print("  %-46s snow=%s vars=%d" % (did, snow[:3] if snow else "-", len(vars_)))

    os.makedirs(os.path.join(SITE, "data"), exist_ok=True)
    with open(os.path.join(SITE, "data", "systems.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("wrote site/data/systems.json  (%d datasets, %d with snow)"
          % (len(out), sum(1 for r in out if r["has_snow"])))


if __name__ == "__main__":
    main()
