"""A small, direct client for the new CDS retrieve API.

Why not cdsapi?  Its download layer retries a 502 up to 500 times with a
120 s sleep, which blocks for hours and hides the real problem: the CDS
enforces a limit on how many requests may be *queued* for a given dataset at
once, and that limit is shared with every other user.  When the limit is hit
the API answers 400 "Maximum number queued requests for this dataset has been
reached" immediately - so the correct response is a short backoff and a retry,
not a long HTTP retry storm.

This client:
  * creates a job, polls it, downloads the result;
  * treats the queue-limit rejection as a distinct, retryable outcome;
  * treats a 502 as retryable with a short backoff;
  * never runs more than one job at a time.
"""
import os, json, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))


class QueueFull(Exception):
    """The dataset's queue is saturated - retry later."""


class NoData(Exception):
    """The request is valid but the dataset has nothing for it."""


class CDSDirect:
    def __init__(self, key=None, url="https://cds.climate.copernicus.eu/api"):
        if key is None:
            with open(os.path.join(HERE, ".cdsapirc")) as f:
                key = [l.split(":", 1)[1].strip() for l in f
                       if l.strip().startswith("key:")][0]
        self.key = key
        self.url = url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"PRIVATE-TOKEN": key})

    # ------------------------------------------------------------------
    def _request(self, method, path, **kw):
        last = None
        for attempt in range(4):
            try:
                r = self.s.request(method, self.url + path, timeout=180, **kw)
            except requests.exceptions.RequestException as e:
                last = e
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code in (502, 503, 504):
                last = RuntimeError("HTTP %d" % r.status_code)
                time.sleep(10 * (attempt + 1))
                continue
            return r
        raise last

    # ------------------------------------------------------------------
    def retrieve(self, dataset, request, target, poll_s=15, max_wait_s=14400):
        """Submit one job, wait for it, download it.  Raises QueueFull/NoData."""
        r = self._request("POST", "/retrieve/v1/processes/%s/execute" % dataset,
                          json={"inputs": request})
        if r.status_code in (400, 422):
            txt = r.text
            if "Maximum number queued" in txt:
                raise QueueFull(txt)
            if "NoData" in txt or "not available" in txt:
                raise NoData(txt)
            raise RuntimeError("HTTP %d: %s" % (r.status_code, txt[:400]))
        r.raise_for_status()
        job = r.json()
        jid = job.get("jobID") or job.get("processID")
        t0 = time.time()
        status = None
        while time.time() - t0 < max_wait_s:
            time.sleep(poll_s)
            jr = self._request("GET", "/retrieve/v1/jobs/%s" % jid)
            if jr.status_code == 404:
                raise NoData("job vanished")
            j = jr.json()
            status = j.get("status")
            if status == "successful":
                break
            if status in ("rejected", "failed", "dismissed"):
                txt = self._job_detail(jid)
                if "Maximum number queued" in txt:
                    raise QueueFull(txt)
                raise NoData("job %s: %s" % (status, txt[:400]))
        else:
            raise RuntimeError("timed out waiting for job %s (status %s)" % (jid, status))

        # find the result link
        rr = self._request("GET", "/retrieve/v1/jobs/%s/results" % jid)
        if rr.status_code >= 400:
            txt = rr.text
            if "Maximum number queued" in txt:
                raise QueueFull(txt)
            raise RuntimeError("results HTTP %d: %s" % (rr.status_code, txt[:300]))
        try:
            link = rr.json()["asset"]["value"]["href"]
        except Exception:
            link = None
        if not link:
            raise RuntimeError("no result link for job %s" % jid)
        dr = self.s.get(link, stream=True, timeout=180)
        if dr.status_code >= 400:
            raise RuntimeError("download HTTP %d" % dr.status_code)
        # stream to disk: a full 215-day pull is ~2.5 GB and must not be
        # buffered in memory
        tmp = target + ".part"
        with open(tmp, "wb") as f:
            for chunk in dr.iter_content(chunk_size=4 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
        os.replace(tmp, target)
        return target

    # ------------------------------------------------------------------
    def submit(self, dataset, request):
        """Create a job and return its id without waiting for the result.

        Needed because the CDS subdaily queue is currently ~1000 jobs deep and
        shared with every other user: submitting the whole batch at once and
        then polling is far better than blocking on one job at a time.
        """
        r = self._request("POST", "/retrieve/v1/processes/%s/execute" % dataset,
                          json={"inputs": request})
        if r.status_code in (400, 422):
            txt = r.text
            if "Maximum number queued" in txt:
                raise QueueFull(txt)
            raise NoData("HTTP %d: %s" % (r.status_code, txt[:400]))
        r.raise_for_status()
        job = r.json()
        return job.get("jobID") or job.get("processID")

    # ------------------------------------------------------------------
    def resolve_job(self, jid):
        """A partial job id -> the full uuid (the CDS answers 404 for a prefix,
        which used to look like the job had vanished)."""
        if len(jid) >= 36:
            return jid
        r = self._request("GET", "/retrieve/v1/jobs?limit=60")
        for j in r.json().get("jobs", []):
            if j.get("jobID", "").startswith(jid):
                return j["jobID"]
        return jid

    def job_status(self, jid):
        r = self._request("GET", "/retrieve/v1/jobs/%s" % self.resolve_job(jid))
        if r.status_code == 404:
            return "gone"
        return r.json().get("status")

    # ------------------------------------------------------------------
    def download_job(self, jid, target):
        rr = self._request("GET", "/retrieve/v1/jobs/%s/results" % jid)
        if rr.status_code >= 400:
            txt = rr.text
            if "Maximum number queued" in txt:
                raise QueueFull(txt)
            raise RuntimeError("results HTTP %d: %s" % (rr.status_code, txt[:300]))
        try:
            link = rr.json()["asset"]["value"]["href"]
        except Exception:
            link = None
        if not link:
            raise RuntimeError("no result link for job %s" % jid)
        dr = self.s.get(link, stream=True, timeout=180)
        if dr.status_code >= 400:
            raise RuntimeError("download HTTP %d" % dr.status_code)
        # stream to disk: a full 215-day pull is ~2.5 GB and must not be
        # buffered in memory
        tmp = target + ".part"
        with open(tmp, "wb") as f:
            for chunk in dr.iter_content(chunk_size=4 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
        os.replace(tmp, target)
        return target

    # ------------------------------------------------------------------
    def _job_detail(self, jid):
        """The traceback for a rejected job only appears in the job LIST."""
        try:
            r = self._request("GET", "/retrieve/v1/jobs?limit=25")
            for j in r.json().get("jobs", []):
                if j.get("jobID") == jid:
                    return json.dumps(j.get("metadata", {}))
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    def job_list(self, limit=50):
        r = self._request("GET", "/retrieve/v1/jobs?limit=%d" % limit)
        return r.json() if r.status_code == 200 else {}

    # ------------------------------------------------------------------
    def live_jobs(self, limit=60):
        """-> [{jobID, status, dataset, created}, ...] for the requests this
        account still holds.

        The list only carries the most recent records, so it is a useful
        witness for "is my job still there" but NOT a complete inventory -
        always ask about a job by its full uuid as well.
        """
        out = []
        r = self._request("GET", "/retrieve/v1/jobs?limit=%d" % limit)
        if r.status_code != 200:
            return out
        js = r.json()
        for j in js.get("jobs", []):
            jid = j.get("jobID", "")
            if not jid:
                continue
            out.append({"jobID": jid, "status": j.get("status"),
                        "dataset": j.get("processID", ""),
                        "created": j.get("created", "")})
        return out


if __name__ == "__main__":
    import sys
    c = CDSDirect()
    ds = sys.argv[1]
    req = json.loads(sys.argv[2])
    out = sys.argv[3]
    print(c.retrieve(ds, req, out))
