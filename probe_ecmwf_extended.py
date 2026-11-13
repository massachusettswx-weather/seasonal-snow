"""Is ECMWF's extended-range ensemble (the 46-day run, "EC46") in the C3S?

The ECDS route to EC46 is behind a licence click we cannot make.  But the
C3S seasonal archive carries several ECMWF systems, and the extended-range
ensemble is one of the systems the C3S publishes (it is the same model - the
46-day ensemble - just served from the seasonal archive instead of ECDS).

If it is there, the EC46 section can be built without the licence.

This probes, in order, with one request at a time and never more than one
job of ours in flight:

  1. originating_centre=ecmwf, system=1, one lead time  -> does the system
     exist, and how many members does it carry?
  2. the same system with a long lead time (35 days)      -> how far does it
     actually reach?

It writes data/ecmwf_extended_probe.json.
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cds_direct                                    # noqa: E402
from fetch_polar_models import LV, AREA              # noqa: E402

OUT = os.path.join(HERE, "data", "ecmwf_extended_probe.json")
DATASET = "seasonal-original-pressure-levels"


def inflight(cds):
    n = 0
    for j in cds.live_jobs():
        if j.get("status") in ("accepted", "running", "queued"):
            n += 1
    return n


def wait_for_a_slot(cds, tries=240):
    """The account holds two requests at a time, across every dataset."""
    for _ in range(tries):
        n = inflight(cds)
        if n < 2:
            return True
        time.sleep(30)
    return False


def request(system, lead_hours, day="01", month="11", year="2026"):
    return {
        "originating_centre": "ecmwf",
        "system": system,
        "variable": ["geopotential"],
        "pressure_level": LV,
        "year": [str(year)],
        "month": ["%02d" % int(month)],
        "day": [str(day)],
        "leadtime_hour": [str(h) for h in lead_hours],
        "area": AREA,
        "data_format": "grib",
    }


def submit_and_wait(cds, req, tries=120):
    r = cds.submit(DATASET, req)
    if isinstance(r, str):
        # the archive refuses a submission when the account's queue is full:
        # it answers with a string, not a job record
        print("   refused: %s" % r[:120])
        return None, "refused", {"error": r}
    jid = r.get("job_id") or r.get("id") or r.get("request_id")
    print("   submitted: %s" % str(jid)[:12])
    for _ in range(tries):
        st = cds.status(jid)
        s = (st or {}).get("status")
        if s in ("successful", "failed", "rejected"):
            return jid, s, st
        time.sleep(20)
    return jid, "timeout", None


def members_in(path):
    import eccodes
    mems = set()
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                mems.add((eccodes.codes_get(gid, "number"),))
            except Exception:
                pass
            eccodes.codes_release(gid)
    return len(mems)


def main():
    cds = cds_direct.CDSDirect()
    rec = {"probes": []}

    for system, lead, label in ((1, [12], "system 1, lead 12 h"),
                                (1, [852], "system 1, lead 852 h (35 days)"),
                                (2, [852], "system 2, lead 852 h (35 days)")):
        print("== probing: %s" % label, flush=True)
        if not wait_for_a_slot(cds):
            print("   no free slot in the account; giving up on this probe")
            break
        jid, status, st = submit_and_wait(cds, request(system, lead))
        entry = {"system": system, "leadtime_hour": lead, "status": status,
                 "job": str(jid)}
        if status == "refused":
            # the account's queue was full: wait for it to drain and try again
            for _ in range(40):
                time.sleep(30)
                if wait_for_a_slot(cds):
                    jid, status, st = submit_and_wait(cds, request(system, lead))
                    entry["status"] = status
                    if status == "successful":
                        break
            entry["job"] = str(jid)
        if status == "successful":
            path = os.path.join(HERE, "data", "probe_%s_%s.grib"
                                % (system, lead[0]))
            try:
                cds.download(jid, path)
                entry["members"] = members_in(path)
                entry["file"] = path
                print("   members in the answer: %s" % entry["members"])
            except Exception as e:
                entry["error"] = str(e)
        else:
            entry["detail"] = (st or {}).get("error") or (st or {}).get("messages")
            print("   status %s: %s" % (status, str(entry["detail"])[:200]))
        rec["probes"].append(entry)
        with open(OUT, "w") as f:
            json.dump(rec, f, indent=1)
        time.sleep(5)

    print("\n=== the summary ===")
    for e in rec["probes"]:
        print("  system %s lead %s -> %s  members=%s  %s"
              % (e["system"], e["leadtime_hour"], e["status"],
                 e.get("members"), str(e.get("detail", ""))[:120]))


if __name__ == "__main__":
    main()
