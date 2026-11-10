"""Watch the November-init probe job and record the answer.

The probe asks the CDS for one lead month of a centre's November init.
While the seasonal queue is congested the request simply sits there; this
watches it and writes data/nov_release.json when it comes back.

    python3 watch_probe_job.py <job-id> <tag> [centre] [system]
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cds_direct                                       # noqa: E402

DATA = os.path.join(HERE, "data")


def main():
    jid = sys.argv[1]
    tag = sys.argv[2]
    centre = sys.argv[3] if len(sys.argv) > 3 else ""
    system = sys.argv[4] if len(sys.argv) > 4 else ""
    c = cds_direct.CDSDirect()
    for i in range(720):                      # 6 h
        s = c.job_status(jid)
        if s == "successful":
            print("%s: NOVEMBER IS OUT (job %s)" % (tag, jid[:12]), flush=True)
            p = os.path.join(DATA, "nov_release.json")
            out = json.load(open(p)) if os.path.exists(p) else {}
            out[tag] = {"init": "2026-11", "centre": centre, "system": system}
            json.dump(out, open(p, "w"), indent=1)
            return
        if s in ("failed", "rejected", "gone", "dismissed"):
            print("%s: no November init (job %s -> %s)" % (tag, jid[:12], s),
                  flush=True)
            p = os.path.join(DATA, "nov_release.json")
            out = json.load(open(p)) if os.path.exists(p) else {}
            out[tag] = {"init": None}
            json.dump(out, open(p, "w"), indent=1)
            return
        time.sleep(30)
    print("gave up waiting for %s" % jid[:12], flush=True)


if __name__ == "__main__":
    main()
