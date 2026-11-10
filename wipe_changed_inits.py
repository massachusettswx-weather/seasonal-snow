"""Drop the data of a centre only when its init actually changed.

The restart script used to wipe every October series before the fetch.  If a
centre is still on the October init (the non-ECMWF C3S contributions usually
release later than the ECMWF one) that throws away hours of CDS queue work
for nothing - and the jobs already in the queue are still valid.

So: snapshot the inits before the fetch, compare afterwards, and only remove
what belongs to a centre whose init moved.

    python3 wipe_changed_inits.py snapshot   # before the fetch
    python3 wipe_changed_inits.py wipe      # after the monthly fetch
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
SNAP = os.path.join(DATA, "init_snapshot.json")
STATE = os.path.join(DATA, "models_fetched.json")

# per centre: the files that belong to one init
FILES = ("u10_daily.npz", "snow_daily.npz", "u10_daily.grib", "snow_daily.grib",
         "sst_monthly.grib", "enso.json", "sst_hindcast.npz",
         "sst_extended.npz")
JOBSTATES = ("daily_jobs.json", "snow_daily_jobs.json")


def snapshot():
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    json.dump({k: v.get("init") for k, v in st.items()},
              open(SNAP, "w"), indent=1)
    print("init snapshot:", {k: v.get("init") for k, v in sorted(st.items())})


def wipe():
    snap = json.load(open(SNAP)) if os.path.exists(SNAP) else {}
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    changed = [k for k, v in st.items()
               if v.get("init") and snap.get(k) and snap.get(k) != v.get("init")]
    print("init changed for:", changed or "none")
    for k in changed:
        for f in FILES:
            p = os.path.join(MDIR, k, f)
            if os.path.exists(p):
                os.remove(p)
                print("   removed %s/%s" % (k, f))
        for jf in JOBSTATES:
            p = os.path.join(DATA, jf)
            if not os.path.exists(p):
                continue
            j = json.load(open(p))
            keep = [x for x in j.get("jobs", []) if x.get("tag") != k]
            if len(keep) != len(j.get("jobs", [])):
                j["jobs"] = keep
                json.dump(j, open(p, "w"), indent=1)
                print("   dropped %s jobs from %s" % (k, jf))


if __name__ == "__main__":
    (snapshot if (sys.argv[1] if len(sys.argv) > 1 else "") == "snapshot"
     else wipe)()
