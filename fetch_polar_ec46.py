"""EC46 (the ECMWF sub-seasonal ensemble) polar-cap geopotential height.

The seasonal route in `fetch_polar_models.py` uses the C3S sub-daily archive,
which has no sub-seasonal system in it.  For the sub-seasonal guidance the
same quantity - the area weighted (cos(lat)) mean geopotential height over
60-90N - has to come out of ECMWF's own store: the ECDS service, dataset
`s2s-forecasts`, system 46 (the 46-day ensemble).

    POST https://ecds.ecmwf.int/api/retrieve/v1/processes/s2s-forecasts/execute
    headers: PRIVATE-TOKEN: <the CDS key in .cdsapirc>
    {
      "inputs": {
        "origin": "ecmwf", "system": 46,
        "year": "2026", "month": "11", "day": "13", "time": "00:00",
        "level_type": "pressure", "variable": ["geopotential_height"],
        "level_value": ["10_hpa", ...],
        "forecast_type": ["control_forecast", "perturbed_forecast"],
        "leadtime_hour": ["24_48", "72_96", ..., "456_480"],
        "area": [90, -180, 60, 180], "data_format": "grib"
      },
      "outputs": {"asset": {"value": {"type": "file"}}}
    }

Two things about the catalogue, both measured from the live form schema
(GET /retrieve/v1/processes/s2s-forecasts):

  * `level_value` holds TEN pressure levels - 10, 50, 100, 200, 300, 500,
    700, 850, 925, 1000 hPa.  There is no 30 hPa and no 400 hPa, so an EC46
    section carries ten levels rather than the reference's twelve.
  * `leadtime_hour` takes 359 values, 98 of them ranges; the weekly ranges
    24_48 ... 456_480 are the ones the sub-seasonal windows are built from.

**The licence is the blocker.**  The account has not accepted the S2S
licence, so every request is refused with

    HTTP 403 {"title": "required licences not accepted",
              "detail": "Not all the required licences have been accepted;
                         please visit https://ecds.ecmwf.int/datasets/
                         s2s-forecasts?tab=download#manage-licences ..."}

The check runs before the request is validated, so a 403 always means the
licence, never a malformed request.  The licence has to be ticked by hand in
the web UI; there is no API for it (`/api/licences` and
`/api/retrieve/v1/licences` both answer 404).  Until that is done this
script reports the refusal and writes NOTHING: a chart must never be
published without real data behind it.
"""
import json
import os
import sys
import time
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import SECTORS, sector_mean, zonal_mean  # noqa: E402

ECDS = "https://ecds.ecmwf.int/api"
EXEC = "%s/retrieve/v1/processes/s2s-forecasts/execute" % ECDS
OUT = os.path.join(DATA, "polar_ec46_z.json")
STATE = os.path.join(DATA, "polar_ec46_jobs.json")
# the shared cache the plotter reads; the series is merged into it under its
# own key, and every other model's record is left exactly as it was found
CACHE = os.path.join(DATA, "polar_model_z.json")
TAG = "ec46"

# the levels the S2S catalogue serves (ten of the reference's twelve: the
# catalogue has no 30 hPa and no 400 hPa)
LEVELS = [10, 50, 100, 200, 300, 500, 700, 850, 925, 1000]
AREA = [90.0, -180.0, 60.0, 180.0]

# The catalogue has no `system` parameter: the product is picked by the RUN
# DATE, so the 46-day extended range is what the archive serves on the days
# it runs (Mondays and Thursdays, 00Z) and the 15-day ensemble on the others.
# The lead times are 24-hour blocks, so the series that comes back is a daily
# one.
SYSTEM = 46

# The lead time ranges, 24_48 up to 816_840: thirty-five days, which is
# the window the section is drawn over.  The extended range runs to day 46
# (1104 h), so day 35 is well inside it.
WEEKLY = ["%d_%d" % (h, h + 24) for h in range(24, 841, 24)]

# The S2S archive holds the run with about a two-day delay, so the run that
# can be had is the one from roughly 48 hours ago.
DELAY_HOURS = 48

LICENCE_URL = ("https://ecds.ecmwf.int/datasets/s2s-forecasts"
               "?tab=download#manage-licences")


def key():
    with open(os.path.join(HERE, ".cdsapirc")) as f:
        return [l.split(":", 1)[1].strip() for l in f
                if l.strip().startswith("key:")][0]


def session():
    import requests
    s = requests.Session()
    s.headers.update({"PRIVATE-TOKEN": key(), "Content-Type": "application/json"})
    return s


def latest_run(s, tries=6):
    """The most recent day the archive holds an ECMWF S2S run for.

    The run date is found by asking the archive backwards from today: the
    catalogue's `day` enum stops at the 20th, and the archive holds a few
    days of runs, so the search starts at the 19th and walks back.
    """
    today = date.today() - timedelta(hours=DELAY_HOURS)
    for back in range(0, tries + 1):
        d = today - timedelta(days=back)
        for t in ("00:00", "12:00"):
            req = {"origin": "ecmwf",
                   "year": "%04d" % d.year, "month": "%02d" % d.month,
                   "day": "%02d" % d.day, "time": t,
                   "level_type": "pressure",
                   "variable": ["geopotential_height"],
                   "level_value": ["%d_hpa" % l for l in LEVELS],
                   "forecast_type": ["control_forecast"],
                   "leadtime_hour": ["24_48"], "area": AREA,
                   "data_format": "grib"}
            r = s.post(EXEC, json={"inputs": req}, timeout=180)
            # the Data Store answers 201 Created for a new job, not 200
            if r.status_code in (200, 201):
                return d, t, r.json()
            if r.status_code == 403:
                raise SystemExit(licence_refusal(r))
            if r.status_code == 400:
                # no run that day
                break
    return None, None, None


def licence_refusal(r):
    return ("the S2S licence has not been accepted yet.  The data is free "
            "(CC BY 4.0) - the account only has to accept the terms once:\n"
            "  %s\n"
            "  the answer was HTTP %d: %s\n"
            "  nothing was written; the series needs real data behind it."
            % (LICENCE_URL, r.status_code, r.text[:200]))


def read_grib(path):
    """-> ({valid_time: {level: polar cap mean}}, {valid_time: {sector: {...}}}).

    The sector means are the same reduction over one longitude sector, so
    the Atlantic and the Pacific can be drawn separately.
    """
    import eccodes
    out = {}
    sout = {}
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:                         # noqa: BLE001
                break
            if gid is None:
                break
            try:
                la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                lo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                ni = int(eccodes.codes_get(gid, "Ni", 0) or 0)
                nj = int(eccodes.codes_get(gid, "Nj", 0) or 0)
                if ni and nj and v.size == ni * nj:
                    lat2d = la.reshape(nj, ni)
                    v = v.reshape(nj, ni)
                else:
                    lats = np.unique(la)[::-1]
                    lons = np.unique(lo)
                    if v.size != lats.size * lons.size:
                        continue
                    v = v.reshape(len(lats), len(lons))
                    lat2d = np.repeat(lats[:, None], len(lons), axis=1)
                lats = lat2d[:, 0]
                lon2d = lo.reshape(nj, ni) if (ni and nj
                                               and v.size == ni * nj) else \
                    np.repeat(np.unique(lo)[None, :], len(lats), axis=0)
                # the VALIDITY time, not the data time: the S2S fields are
                # initialised at 00Z or 12Z and carry the lead time as the
                # step, so validityDate/validityTime is the only pair that
                # gives the right calendar day
                vd = int(eccodes.codes_get(gid, "validityDate"))
                vt = int(eccodes.codes_get(gid, "validityTime"))
                valid = date(vd // 10000, (vd // 100) % 100, vd % 100) \
                    + timedelta(hours=vt // 100, minutes=vt % 100)
                lev = int(eccodes.codes_get(gid, "level"))
                key = valid.strftime("%Y-%m-%d %H")
                out.setdefault(key, {})[lev] = zonal_mean(v, lats)
                for name, (a, b) in SECTORS.items():
                    sout.setdefault(key, {}).setdefault(name, {})[lev] = \
                        sector_mean(v, lats, lon2d[0, :], a, b)
            except Exception:                         # noqa: BLE001
                pass
            finally:
                eccodes.codes_release(gid)
    return out


def submit(s, run_date, run_time, weeks):
    req = {"origin": "ecmwf",
           "year": "%04d" % run_date.year, "month": "%02d" % run_date.month,
           "day": "%02d" % run_date.day, "time": run_time,
           "level_type": "pressure",
           "variable": ["geopotential_height"],
           "level_value": ["%d_hpa" % l for l in LEVELS],
           "forecast_type": ["control_forecast", "perturbed_forecast"],
           "leadtime_hour": weeks,
           "area": AREA, "data_format": "grib"}
    r = s.post(EXEC, json={"inputs": req,
                           "outputs": {"asset": {"value": {"type": "file"}}}},
               timeout=300)
    if r.status_code == 403:
        raise SystemExit(licence_refusal(r))
    if r.status_code >= 400:
        raise RuntimeError("submit failed HTTP %d: %s"
                           % (r.status_code, r.text[:300]))
    j = r.json()
    return j.get("jobID") or j.get("processID")


def wait(s, jid, tries=360):
    for _ in range(tries):
        time.sleep(15)
        r = s.get("%s/retrieve/v1/jobs/%s" % (ECDS, jid), timeout=60)
        if r.status_code != 200:
            continue
        st = r.json().get("status")
        if st in ("successful", "completed"):
            return True
        if st in ("failed", "error", "rejected", "dismissed"):
            print("   the job is %s" % st, flush=True)
            return False
    return False


def download(s, jid, path):
    r = s.get("%s/retrieve/v1/jobs/%s/results" % (ECDS, jid), timeout=120)
    link = r.json()["asset"]["value"]["href"]
    with s.get(link, stream=True, timeout=600) as dr:
        with open(path + ".part", "wb") as f:
            for chunk in dr.iter_content(4 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    os.replace(path + ".part", path)


def main():
    s = session()
    run_date, run_time, _ = latest_run(s)
    if run_date is None:
        print("   no ECMWF S4S run found in the last week")
        return
    print("   the S4S run: %s %s" % (run_date, run_time), flush=True)

    st = json.load(open(STATE)) if os.path.exists(STATE) else {"jobs": []}
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}

    # the weekly windows in chunks: the archive caps the RESPONSE SIZE
    CHUNK = 5
    for i in range(0, len(WEEKLY), CHUNK):
        weeks = WEEKLY[i:i + CHUNK]
        done = [j for j in st["jobs"]
                if j.get("chunk") == i and j.get("status") == "decoded"]
        if done:
            continue
        print("   the weeks %s ..." % (weeks[0] + " to " + weeks[-1]), flush=True)
        jid = submit(s, run_date, run_time, weeks)
        print("   the job %s" % jid, flush=True)
        if not wait(s, jid):
            st["jobs"].append({"chunk": i, "job": jid, "status": "failed"})
            with open(STATE + ".tmp", "w") as f:
                json.dump(st, f, indent=1)
            os.replace(STATE + ".tmp", STATE)
            continue
        path = os.path.join(DATA, "_ec46_%d.grib" % i)
        download(s, jid, path)
        vals, svals = read_grib(path)
        os.remove(path)
        rec = out.setdefault(TAG, {"times": [], "values": [],
                                   "sectors": {}, "levels": list(LEVELS)})
        for t in sorted(vals):
            row = [vals[t].get(l) for l in LEVELS]
            if any(x is None for x in row):
                continue
            rec["times"].append(t)
            rec["values"].append(row)
            for name, sd in svals.get(t, {}).items():
                srow = [sd.get(l) for l in LEVELS]
                if any(x is None for x in srow):
                    continue
                rec.setdefault("sectors", {}).setdefault(name, []).append(srow)
        rec["run"] = "%s %s" % (run_date, run_time)
        rec["members"] = 51
        with open(OUT + ".tmp", "w") as f:
            json.dump(out, f, indent=1)
        os.replace(OUT + ".tmp", OUT)
        # and into the shared cache, under the same key the plotter reads
        cache = {}
        if os.path.exists(CACHE):
            with open(CACHE) as f:
                cache = json.load(f)
        cache[TAG] = {"times": rec["times"], "values": rec["values"],
                      "levels": list(LEVELS), "run": rec["run"],
                      "members": 51}
        if rec.get("sectors"):
            cache[TAG]["sectors"] = rec["sectors"]
        with open(CACHE + ".tmp", "w") as f:
            json.dump(cache, f)
        os.replace(CACHE + ".tmp", CACHE)
        st["jobs"].append({"chunk": i, "job": jid, "status": "decoded"})
        with open(STATE + ".tmp", "w") as f:
            json.dump(st, f, indent=1)
        os.replace(STATE + ".tmp", STATE)
        print("   the chunk decoded: %d times so far" % len(rec["times"]),
              flush=True)

    print("   the EC46 series: %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
