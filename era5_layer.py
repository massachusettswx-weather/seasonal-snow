"""Build the ERA5 climatology layer (1991-2020) at 10 hPa from the committed
daily archive in the Forecast-charts repo. No download.

Source: data/store/archive/u_<dom>.json.gz
  dates : list of daily timestamps 1959-10-01 .. 2020-12-31 (12Z)
  levels: 37 pressure levels (hPa)
  u     : u[level_idx][date_idx]  -> zonal-mean zonal wind (m/s)
  domains: 60 = 60N point, 0 = NH(0-90N) area-weighted mean, 70 = 70N, cap = 65-90N

Outputs a JSON with, for each requested domain and for every calendar day of the
Nov-May season (plus the Oct tail for the November run window):
  mean, sigma, p30,p70, p10,p90, rmin, rmax  (daily series, calendar-day keyed)
"""
import gzip, json, os, sys
from collections import defaultdict
import numpy as np

REPO = "/workspace/repo"
LEVEL = 10
YEARS = range(1991, 2021)


def load_domain(dom: str):
    p = os.path.join(REPO, "data", "store", "archive", f"u_{dom}.json.gz")
    with gzip.open(p, "rt") as f:
        d = json.load(f)
    dates = np.array(d["dates"])
    levels = list(d["levels"])
    li = levels.index(LEVEL)
    u = np.asarray(d["u"][li], dtype=np.float64)
    return dates, u


def build(dom: str, mmdd_list):
    dates, u = load_domain(dom)
    yrs = np.array([int(d[:4]) for d in dates])
    mds = np.array([d[5:10] for d in dates])

    by_md = defaultdict(list)
    for i in range(len(dates)):
        if yrs[i] in YEARS and mds[i] in mmdd_list:
            by_md[mds[i]].append(u[i])

    out = {}
    for md in mmdd_list:
        vals = np.array(by_md.get(md, []), dtype=np.float64)
        if vals.size == 0:
            continue
        out[md] = {
            "n": int(vals.size),
            "mean": float(vals.mean()),
            "sigma": float(vals.std(ddof=1)),
            "p10": float(np.percentile(vals, 10)),
            "p30": float(np.percentile(vals, 30)),
            "p70": float(np.percentile(vals, 70)),
            "p90": float(np.percentile(vals, 90)),
            "rmin": float(vals.min()),
            "rmax": float(vals.max()),
            "rmin_year": int(yrs[[i for i in range(len(dates))
                                  if yrs[i] in YEARS and mds[i] == md][int(np.argmin(vals))]]),
        }
    return out


def season_md_list(start_md="10-01", end_md="06-10"):
    """Calendar-day list from start_md to end_md, wrapping the year."""
    import datetime as dt
    m1, d1 = map(int, start_md.split("-"))
    m2, d2 = map(int, end_md.split("-"))
    res, y = [], 2000
    cur = dt.date(y, m1, d1)
    end = dt.date(y + (1 if (m2, d2) < (m1, d1) else 0), m2, d2)
    while cur <= end:
        res.append(cur.strftime("%m-%d"))
        cur += dt.timedelta(days=1)
    return res


if __name__ == "__main__":
    # the whole calendar year: a model may now run to its own end (up to
    # 12 lead months), so every calendar day needs a climatology
    mds = season_md_list("01-01", "12-31")
    result = {"level": LEVEL, "years": [1991, 2020], "source": "ERA5 ARCO daily 12Z archive (Forecast-charts repo)"}
    for dom, key in (("60", "60N"), ("0", "NH"), ("70", "70N"), ("cap", "cap")):
        result[key] = build(dom, mds)
        print(f"{key}: {len(result[key])} calendar days built")
    with open("/workspace/seas5/era5_clim_10hpa.json", "w") as f:
        json.dump(result, f, indent=1)
    # sanity print
    s = result["60N"]
    for md in ("10-25", "11-01", "12-01", "01-01", "03-01", "05-01"):
        if md in s:
            v = s[md]
            print(f"60N 10hPa {md}: mean={v['mean']:7.2f} sd={v['sigma']:5.2f} "
                  f"p10={v['p10']:7.2f} p90={v['p90']:7.2f} rmin={v['rmin']:7.2f} rmax={v['rmax']:6.2f} n={v['n']}")
