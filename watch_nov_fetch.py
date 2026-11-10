"""Watch the November-init fetch for a centre and record the answer.

Two outcomes, both useful:
  * the job succeeds -> the centre's November monthly snowfall is saved and
    the centre's init is set to 2026-11, so the rest of the pipeline fetches
    the rest of its November fields;
  * the job fails    -> the centre has no November init and the answer is
    written down (the CDS answers a missing init with MARS error -2).

    python3 watch_nov_fetch.py <job-id> <tag> <centre> <system>
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cds_direct                                       # noqa: E402

DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
STATE = os.path.join(DATA, "models_fetched.json")
RELEASE = os.path.join(DATA, "nov_release.json")


def main():
    jid = sys.argv[1]
    tag = sys.argv[2]
    centre = sys.argv[3] if len(sys.argv) > 3 else ""
    system = sys.argv[4] if len(sys.argv) > 4 else ""
    c = cds_direct.CDSDirect()
    d = os.path.join(MDIR, tag)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "snowfall_monthly.grib")
    for i in range(480):                       # 8 h
        s = c.job_status(jid)
        if s == "successful":
            print("%s: November data retrieved" % tag, flush=True)
            c.download_job(jid, out)
            print("  saved %s (%.1f MB)"
                  % (os.path.basename(out), os.path.getsize(out) / 1e6),
                  flush=True)
            st = json.load(open(STATE)) if os.path.exists(STATE) else {}
            rec = st.get(tag, {})
            rec["init"] = "2026-11"
            rec["probe_date"] = time.strftime("%Y-%m-%d")
            rec.pop("snow", None)
            st[tag] = rec
            json.dump(st, open(STATE, "w"), indent=1)
            rel = json.load(open(RELEASE)) if os.path.exists(RELEASE) else {}
            rel[tag] = {"init": "2026-11", "centre": centre, "system": system}
            json.dump(rel, open(RELEASE, "w"), indent=1)
            print("  %s is on the 2026-11 init" % tag, flush=True)
            return
        if s in ("failed", "rejected", "gone", "dismissed"):
            detail = c._job_detail(jid)
            print("%s: no November init (%s)" % (tag, s), flush=True)
            print("  %s" % detail[:200].replace("\n", " "), flush=True)
            rel = json.load(open(RELEASE)) if os.path.exists(RELEASE) else {}
            rel[tag] = {"init": None, "note": detail[:200]}
            json.dump(rel, open(RELEASE, "w"), indent=1)
            return
        time.sleep(30)
    print("gave up waiting for %s" % jid[:12], flush=True)


if __name__ == "__main__":
    main()
