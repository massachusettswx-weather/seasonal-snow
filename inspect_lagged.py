"""Dump the ensemble structure of a seasonal GRIB: members, start dates, leads.

Used to test the "lagged ensemble" hypothesis on files that are already on
disk (the monthly pulls) before spending a single CDS request.

    python3 inspect_lagged.py data/models/ukmo-gloseas6/u10_monthly.grib
"""
import sys
from collections import defaultdict

import eccodes


def get(gid, key, default=None):
    try:
        v = eccodes.codes_get(gid, key)
    except Exception:
        return default
    if isinstance(v, (bytes, bytearray)):
        v = v.decode()
    return v


def main(path, limit_fields=None):
    rows = []
    n = 0
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                rows.append(dict(
                    num=get(gid, "number"),
                    pn=get(gid, "perturbationNumber"),
                    dataDate=get(gid, "dataDate"),
                    dataTime=get(gid, "dataTime"),
                    refDate=get(gid, "referenceDate"),
                    refTime=get(gid, "referenceTime"),
                    validDate=get(gid, "validityDate"),
                    validTime=get(gid, "validityTime"),
                    step=get(gid, "step"),
                    stepType=get(gid, "stepType"),
                    level=get(gid, "level"),
                    levType=get(gid, "typeOfLevel"),
                    centre=get(gid, "centre"),
                    expver=get(gid, "experimentVersionNumber"),
                ))
                n += 1
            finally:
                eccodes.codes_release(gid)
            if limit_fields and n >= limit_fields:
                break

    print("%s: %d messages" % (path, len(rows)))
    if not rows:
        return
    for k in ("centre", "levType", "level", "expver", "stepType"):
        vals = sorted({str(r[k]) for r in rows})
        print("  %-6s : %s" % (k, vals[:12]))

    # member -> the (dataDate,dataTime) it was initialised at
    starts = defaultdict(set)
    for r in rows:
        starts[str(r["num"])].add((str(r["dataDate"]), str(r["dataTime"]),
                                   str(r["refDate"]), str(r["refTime"])))
    print("  distinct `number` values: %d" % len(starts))

    # group members by their start date
    by_start = defaultdict(list)
    for m, ss in starts.items():
        for s in ss:
            by_start[s].append(m)
    print("  distinct (dataDate,dataTime,refDate,refTime) tuples: %d" % len(by_start))
    for s in sorted(by_start, key=lambda x: (x[0], x[1])):
        mm = by_start[s]
        print("    start %s -> %3d member(s): %s"
              % ("/".join(s), len(mm), ",".join(sorted(mm, key=lambda x: int(x))[:12])))

    # validity structure for one member
    print("  sample rows:")
    for r in rows[:6]:
        print("    num=%-4s pn=%-4s dataDate=%s dataTime=%s refDate=%s refTime=%s "
              "valid=%s %s step=%s level=%s"
              % (r["num"], r["pn"], r["dataDate"], r["dataTime"], r["refDate"],
                 r["refTime"], r["validDate"], r["validTime"], r["step"], r["level"]))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
