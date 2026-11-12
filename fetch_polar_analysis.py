"""The polar cap analysis before the forecast, from the IFS open data.

The reference figure's left half is "ECMWF ANALYSIS" - the model's own
analysis, run backwards in time so it ends on the forecast's init.  The
open data bucket keeps every daily cycle for the last month or so, so the
analysis for a given day is the step-0 field of that day's 12Z cycle.

This is the same product as the forecast half (fetch_polar_ifs.py), so the
two halves of the section are consistent by construction: the same grid, the
same levels, the same polar-cap mean.  No queue, no cost limit.

The C3S seasonal archive and the ERA5 reanalysis are the alternatives, and
the CDS queue on this account is the reason this route is preferred.
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from fetch_polar_ifs import fetch_step, COMMON     # noqa: E402


def cycles_between(d0, d1):
    """The 12Z cycles from d0 to d1 inclusive, as YYYYMMDD strings."""
    import datetime
    a = datetime.datetime.strptime(d0, "%Y-%m-%d")
    b = datetime.datetime.strptime(d1, "%Y-%m-%d")
    out = []
    while a <= b:
        out.append(a.strftime("%Y%m%d"))
        a += datetime.timedelta(days=1)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", default="2026-10-13",
                    help="the first analysis day, YYYY-MM-DD")
    ap.add_argument("--to", dest="d1", default="2026-11-11",
                    help="the last analysis day, YYYY-MM-DD")
    ap.add_argument("--out", default=os.path.join(DATA, "polar_analysis.json"))
    args = ap.parse_args()

    out = {}
    if os.path.exists(args.out):
        try:
            out = json.load(open(args.out))
        except Exception:
            out = {}
    rec = out.setdefault("ifs-analysis", {"times": [], "values": []})
    have = set(rec["times"])

    for cyc in cycles_between(args.d0, args.d1):
        try:
            t, v = fetch_step(cyc, 0, "ifs", COMMON, "oper")
        except Exception as e:
            print("   the cycle %s failed: %s" % (cyc, str(e)[:80]), flush=True)
            continue
        if t in have:
            continue
        have.add(t)
        rec["times"].append(t)
        rec["values"].append([v.get(l) for l in COMMON])
        print("   the cycle %s -> %s  the 10 hPa %.0f  the 500 hPa %.0f"
              % (cyc, t, v.get(10, float("nan")), v.get(500, float("nan"))),
              flush=True)

    order = np.argsort(rec["times"])
    rec["times"] = [rec["times"][i] for i in order]
    rec["values"] = [rec["values"][i] for i in order]
    rec["levels"] = COMMON
    tmp = args.out + ".tmp"
    json.dump(out, open(tmp, "w"))
    os.replace(tmp, args.out)
    print("   the analysis: %d days -> %s" % (len(rec["times"]), args.out),
          flush=True)


if __name__ == "__main__":
    main()
