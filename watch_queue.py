"""Watch the CDS queue depth and the state of our daily-fetch jobs."""
import json, sys, time
from cds_direct import CDSDirect

c = CDSDirect()
mine = set(sys.argv[1:]) or {"13c08521"}
while True:
    jobs = c._request("GET", "/retrieve/v1/jobs?limit=40").json().get("jobs", [])
    pend = [j for j in jobs if j.get("status") in ("accepted", "running", "queued")]
    q = None
    for j in pend:
        md = (j.get("metadata") or {}).get("qos", {}).get("status", {}).get("limit", [])
        if md:
            q = [(x.get("info", "")[:40], x.get("queued"), x.get("running")) for x in md]
            break
    print(time.strftime("%H:%M:%S"), "pending=%d" % len(pend),
          "| queue(running,queued):", q, flush=True)
    for j in jobs:
        jid = j.get("jobID", "")
        if jid[:8] in mine:
            print("   MINE", jid[:8], j.get("status"), j.get("created"), flush=True)
    time.sleep(120)
