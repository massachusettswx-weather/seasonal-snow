"""Dismiss our own historical CDS jobs.

After the earlier brute-force probe storm the account was left with hundreds of
jobs that the CDS still counts against the MARS-archive request budget, so
every new retrieval - even for datasets we never touched - was rejected with
"Maximum number queued requests for this dataset has been reached".

DELETE /retrieve/v1/jobs/{jobID} dismisses a job.  These calls do not create
MARS retrievals, so they are not subject to the queue limit and can be made
concurrently.
"""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor
from cds_direct import CDSDirect

c = CDSDirect()
jobs = c._request("GET", "/retrieve/v1/jobs?limit=5000").json().get("jobs", [])
todo = [j["jobID"] for j in jobs if j.get("status") != "successful"]
print("jobs: %d total, %d to dismiss" % (len(jobs), len(todo)), flush=True)

done = [0]; failed = [0]
lock_done = [0]

def kill(jid):
    try:
        r = c._request("DELETE", "/retrieve/v1/jobs/%s" % jid)
        if r.status_code < 300:
            done[0] += 1
        else:
            failed[0] += 1
    except Exception:
        failed[0] += 1
    if (done[0] + failed[0]) % 100 == 0:
        print("  dismissed %d, failed %d" % (done[0], failed[0]), flush=True)

t0 = time.time()
with ThreadPoolExecutor(max_workers=3) as ex:
    list(ex.map(kill, todo))
print("done: dismissed %d, failed %d in %.0f s" % (done[0], failed[0], time.time()-t0), flush=True)
