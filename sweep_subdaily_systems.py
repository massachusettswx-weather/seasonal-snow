"""Sweep the candidate system numbers for the sub-daily (original) product.

The UKMO, the JMA and the BoM all come back from
`seasonal-original-pressure-levels` with a handful of members instead of their
whole ensemble: 610 (UKMO) serves two members of sixty and 4 (JMA) five of a
hundred and fifty-five, while the monthly product serves the same centres
whole.  The dataset's own help text says the system identifier can differ
between originating centres AND between start dates, so the number that works
for one product is not necessarily the number that works for the other.

This asks for the smallest possible request for each candidate system and
counts the members in the raw GRIB, two requests at a time, and stops a
centre's sweep as soon as a system comes back with a real ensemble.

    python3 sweep_subdaily_systems.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cds_direct import CDSDirect  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "subdaily_system_sweep.json")
SLOTS = 2

# (centre, system) candidates.  The number that works for the MONTHLY product
# is included as a control: if it comes back whole here, the problem is
# elsewhere.
CANDIDATES = [
    ("ukmo", "600"), ("ukmo", "601"), ("ukmo", "602"),
    ("ukmo", "603"), ("ukmo", "604"), ("ukmo", "605"),
    ("jma", "1"), ("jma", "2"), ("jma", "3"), ("jma", "5"),
    ("jma", "6"), ("jma", "7"), ("jma", "8"), ("jma", "12"),
    ("jma", "13"), ("jma", "14"), ("jma", "15"),
    ("bom", "21"), ("bom", "35"), ("bom", "22"),
]


def count_members(path):
    """-> the number of distinct ensemble members in a GRIB file."""
    import eccodes
    nums = set()
    with open(path, "rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            try:
                v = eccodes.codes_get(gid, "number")
                nums.add(int(v) if v is not None else -1)
            finally:
                eccodes.codes_release(gid)
    return len(nums)


def load():
    if os.path.exists(OUT):
        try:
            return json.load(open(OUT))
        except Exception:
            pass
    return {"done": {}, "found": {}}


def main():
    c = CDSDirect()
    st = load()
    done = st["done"]
    found = st["found"]
    todo = [(c_, s) for (c_, s) in CANDIDATES
            if "%s:%s" % (c_, s) not in done]
    print("%d candidate systems to try" % len(todo), flush=True)

    inflight = {}
    while todo or inflight:
        # top the queue up
        while todo and len(inflight) < SLOTS:
            centre, system = todo.pop(0)
            key = "%s:%s" % (centre, system)
            req = {"originating_centre": centre, "system": system,
                   "variable": "u_component_of_wind", "pressure_level": "10",
                   "year": "2026", "month": "11", "day": ["01"],
                   "leadtime_hour": ["12"], "area": [90, -180, 60, 180],
                   "data_format": "grib"}
            try:
                jid = c.submit("seasonal-original-pressure-levels", req)
            except Exception as e:
                print("  %s refused: %s" % (key, str(e)[:80]), flush=True)
                done[key] = {"members": 0, "note": "refused"}
                continue
            inflight[jid] = (centre, system, key, time.time())
            print("  %s -> %s" % (key, jid), flush=True)
            time.sleep(20)

        time.sleep(25)
        for jid in list(inflight):
            centre, system, key, since = inflight[jid]
            try:
                js = c.job_status(jid)
            except Exception:
                continue
            s = js.get("status") if isinstance(js, dict) else str(js)
            if s in ("successful", "completed"):
                path = os.path.join(HERE, "data", "sweep_%s.grib" % key.replace(":", "_"))
                try:
                    c.download_job(jid, path)
                    n = count_members(path)
                except Exception as e:
                    n, path = 0, str(e)[:80]
                done[key] = {"members": n, "file": os.path.basename(path)}
                print("  %s: %d members" % (key, n), flush=True)
                if n >= 10 and centre not in found:
                    found[centre] = {"system": system, "members": n}
                    print("  ==> %s: system %s serves %d members"
                          % (centre, system, n), flush=True)
                    # this centre is done - drop its remaining candidates
                    todo = [t for t in todo if t[0] != centre]
                os.remove(path) if os.path.exists(path) else None
                inflight.pop(jid)
                json.dump(st, open(OUT, "w"), indent=1)
            elif s in ("failed", "rejected", "dismissed", "gone"):
                done[key] = {"members": 0, "note": s}
                print("  %s: %s" % (key, s), flush=True)
                inflight.pop(jid)
                json.dump(st, open(OUT, "w"), indent=1)
            elif time.time() - since > 3600:
                print("  %s: still queued after an hour" % key, flush=True)
                inflight.pop(jid)
                json.dump(st, open(OUT, "w"), indent=1)

    st["found"] = found
    json.dump(st, open(OUT, "w"), indent=1)
    print("the sweep is done:", json.dumps(found), flush=True)


if __name__ == "__main__":
    main()
