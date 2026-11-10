"""The official NOAA/CPC ENSO indices: ONI and RONI.

Three files come from CPC:

  detrend.nino34.ascii.txt  the monthly Nino 3.4 index (ERSSTv5/v6, with the
                           centred base-period adjustment).  The Oceanic Nino
                           Index is the 3-month running mean of this series.
  Rnino34.ascii.txt        the monthly Relative Oceanic Nino Index (RONI):
                           the Nino 3.4 index minus the tropical-mean (20S-20N)
                           SST anomaly, renormalised so its variance matches
                           the ONI.
  oni.ascii.txt / RONI.ascii.txt
                           the published 3-month (seasonal) ONI and RONI, used
                           to validate the values computed here.

    python3 fetch_oni.py
"""
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ODIR = os.path.join(DATA, "oni")
OUT = os.path.join(ODIR, "indices.json")

FILES = {
    "detrend_nino34.txt":
        "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/"
        "detrend.nino34.ascii.txt",
    "roni_monthly.txt":
        "https://www.cpc.ncep.noaa.gov/data/indices/Rnino34.ascii.txt",
    "oni_seasonal.txt":
        "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
    "roni_seasonal.txt":
        "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt",
}


def fetch():
    os.makedirs(ODIR, exist_ok=True)
    for name, url in FILES.items():
        p = os.path.join(ODIR, name)
        if os.path.exists(p) and os.path.getsize(p) > 500:
            print("  have %s" % name, flush=True)
            continue
        print("  downloading %s" % name, flush=True)
        urllib.request.urlretrieve(url, p)
    return {n: open(os.path.join(ODIR, n)).read() for n in FILES}


def parse_monthly_nino(txt):
    """detrend.nino34: ' YR MON TOTAL ClimAdjust ANOM'."""
    out = {}
    for line in txt.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            y, m = int(parts[0]), int(parts[1])
            v = float(parts[4])
        except ValueError:
            continue
        out["%04d-%02d" % (y, m)] = v
    return out


def parse_monthly_roni(txt):
    """Rnino34: ' YR MTH ANOM'."""
    out = {}
    for line in txt.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            y, m = int(parts[0]), int(parts[1])
            v = float(parts[2])
        except ValueError:
            continue
        out["%04d-%02d" % (y, m)] = v
    return out


def parse_seasonal(txt):
    """oni/roni seasonal: ' SEAS YR [TOTAL] ANOM' - the anomaly is last."""
    out = {}
    for line in txt.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            v = float(parts[-1])
        except ValueError:
            continue
        out["%s %s" % (parts[0], parts[1])] = v
    return out


def running_mean3(monthly):
    """The ONI is the 3-month running mean, labelled by the middle month."""
    keys = sorted(monthly)
    out = {}
    for i in range(1, len(keys) - 1):
        a, b, c = monthly[keys[i - 1]], monthly[keys[i]], monthly[keys[i + 1]]
        out[keys[i]] = round((a + b + c) / 3.0, 3)
    return out


def main():
    txt = fetch()
    nino = parse_monthly_nino(txt["detrend_nino34.txt"])
    roni = parse_monthly_roni(txt["roni_monthly.txt"])
    oni_s = parse_seasonal(txt["oni_seasonal.txt"])
    roni_s = parse_seasonal(txt["roni_seasonal.txt"])
    oni = running_mean3(nino)

    # validate the computed ONI against CPC's published seasonal table.
    # CPC labels a season by the year of its middle month: "DJF 1950" is
    # Dec 1949 + Jan 1950 + Feb 1950, so the centred monthly ONI for the
    # season is January 1950.  "NDJ 1950" is Nov 1949 + Dec 1949 + Jan 1950.
    mid_month = {"DJF": (1, 0), "JFM": (2, 0), "FMA": (3, 0), "MAM": (4, 0),
                 "AMJ": (5, 0), "MJJ": (6, 0), "JJA": (7, 0), "JAS": (8, 0),
                 "ASO": (9, 0), "SON": (10, 0), "OND": (11, 0), "NDJ": (12, 0)}
    err = []
    for seas, (mid, yoff) in mid_month.items():
        for y in range(1951, 2026):
            key = "%s %d" % (seas, y)
            if key not in oni_s:
                continue
            m = "%04d-%02d" % (y + yoff, mid)
            if m in oni:
                err.append(abs(oni[m] - oni_s[key]))
    if err:
        print("  computed ONI vs CPC's published seasonal ONI: "
              "mean |diff| %.3f  max %.3f  (n=%d)" %
              (float(np.mean(err)), float(np.max(err)), len(err)), flush=True)

    out = {"nino34_monthly": nino, "oni_monthly": oni,
           "roni_monthly": roni,
           "oni_seasonal": oni_s, "roni_seasonal": roni_s,
           "source": {k: v for k, v in FILES.items()}}
    json.dump(out, open(OUT, "w"), indent=1)
    print("saved %s" % os.path.relpath(OUT, HERE), flush=True)
    for k in ("nino34_monthly", "oni_monthly", "roni_monthly"):
        d = out[k]
        last = sorted(d)[-1]
        print("  %-16s through %s  (last %+.2f)" % (k, last, d[last]), flush=True)
    for m in ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]:
        print("   %s  nino34 %s  oni %s  roni %s" % (
            m,
            "%+.2f" % nino[m] if m in nino else "  -  ",
            "%+.2f" % oni[m] if m in oni else "  -  ",
            "%+.2f" % roni[m] if m in roni else "  -  "), flush=True)


if __name__ == "__main__":
    import numpy as np
    main()
