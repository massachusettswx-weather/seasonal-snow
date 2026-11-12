"""EC46 (the ECMWF sub-seasonal ensemble) polar-cap geopotential height.

The reference figure is built from the IFS open data and ERA5.  The same
figure for the 46-day sub-seasonal ensemble needs the EC46 forecast, which
is not in the C3S seasonal catalogue and not in the open-data bucket: it
lives in ECMWF's own store (ECDS), dataset "s2s-forecasts", origin "ecmwf",
level_type "pressure".

What the dataset offers, measured from the live form schema:

  variable      geopotential_height
  level_value   10, 50, 100, 200, 300, 500, 700, 850, 925, 1000 hPa
                (the S2S catalogue has no 30 hPa and no 400 hPa, so the
                section for EC46 carries ten levels rather than twelve)
  leadtime_hour daily values out to 1560 h = 65 days; the run is 46 days
  forecast_type control_forecast + perturbed_forecast (51 members)

The only thing standing between this and the data is the licence: the
submit returns 403 "required licences not accepted" until the licence is
ticked at

    https://ecds.ecmwf.int/datasets/s2s-forecasts?tab=download#manage-licences

The script submits, waits, downloads and reduces each chunk to the polar cap
mean per level, exactly like the seasonal puller does.
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

from polar_cap import zonal_mean  # noqa: E402

ECDS = "https://ecds.ecmwf.int/api"
OUT = os.path.join(DATA, "polar_ec46_z.json")
STATE = os.path.join(DATA, "polar_ec46_jobs.json")
# the seasonal puller keeps every model's series in one file, and the
# plotter reads them from there.  The EC46 series is merged into it as
# well, so the same drawing routine serves every route.
CACHE = os.path.join(DATA, "polar_model_z.json")

# the levels the S2S archive serves (the ten of the reference's twelve that
# the S2S catalogue actually carries)
LEVELS = [10, 50, 100, 200, 300, 500, 700, 850, 925, 1000]
AREA = [90.0, -180.0, 60.0, 180.0]
RUN_DAYS = 46

# the days per request: the archive caps the RESPONSE SIZE, and the S4S
# ensemble is 51 members over ten levels, so the chunks are short
CHUNK_DAYS = 8


def key():
    with open(os.path.join(HERE, ".cdsapirc")) as f:
        return [l.split(":", 1)[1].strip() for l in f
                if l.strip().startswith("key:")][0]


def session():
    import requests
    s = requests.Session()
    s.headers.update({"PRIVATE-TOKEN": key()})
    return s


def latest_run():
    """The most recent day the S4S archive has an ECMWF run for.

    The S4S is produced daily; the archive keeps a few days, so the run
    date is found by trying backwards from today.
    """
    s = session()
    today = date.today()
    for k in range(1, 8):
        d = today - timedelta(days=k)
        for t in ("00:00", "12:00"):
            req = {"origin": "ecmwf", "year": "%04d" % d.year,
                   "month": "%02d" % d.month, "day": "%02d" % d.day,
                   "time": t, "level_type": "pressure",
                   "variable": ["geopotential_height"],
                   "level_value": ["1000_hpa"],
                   "forecast_type": ["control_forecast"],
                   "leadtime_hour": ["24"], "area": AREA,
                   "data_format": "grib"}
            r = s.post("%s/retrieve/v1/processes/s2s-forecasts/execute" % ECDS,
                       json={"inputs": req}, timeout=120)
            if r.status_code == 200:
                return d, t, r.json()
            if r.status_code == 403:
                raise SystemExit("the S2S licence has not been accepted yet:\n"
                                 "  https://ecds.ecmwf.int/datasets/s2s-forecasts"
                                 "?tab=download#manage-licences")
    return None, None, None


def read_grib(path):
    """-> {valid_time: {level: polar cap mean geopotential height}}."""
    import eccodes
    out = {}
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
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
                # the VALIDITY time, not the data time: the S2S fields are
                # initialised at 00Z or 12Z and carry the lead time as the
                # step, so validityDate/validityTime is the only pair that
                # gives the right calendar day
                vd = int(eccodes.codes_get(gid, "validityDate"))
                vt = int(eccodes.codes_get(gid, "validityTime"))
                valid = date(vd // 10000, (vd // 100) % 100, vd % 100) \
                    + timedelta(hours=vt)
                lev = int(eccodes.codes_get(gid, "level"))
                key = valid.strftime("%Y-%m-%d %H")
                out.setdefault(key, {})[lev] = zonal_mean(v, lats)
            except Exception:
                pass
            finally:
                eccodes.codes_release(gid)
    return out


def submit(s, run_date, run_time, day0, day1):
    req = {"origin": "ecmwf", "year": "%04d" % run_date.year,
           "month": "%02d" % run_date.month, "day": "%02d" % run_date.day,
           "time": run_time, "level_type": "pressure",
           "variable": ["geopotential_height"],
           # the enum holds the BARE pressure - "1000", "100", "10" - and not
           # "1000_hpa"; that spelling is what the catalogue lists
           "level_value": ["%d" % l for l in LEVELS],
           "forecast_type": ["control_forecast", "perturbed_forecast"],
           # the daily leads run 24...1560; the first day is +24 h
           "leadtime_hour": [str(24 * (k + 1)) for k in range(day0, day1)],
           "area": AREA, "data_format": "grib"}
    r = s.post("%s/retrieve/v1/processes/s2s-forecasts/execute" % ECDS,
               json={"inputs": req,
                     "outputs": {"asset": {"value": {"type": "file"}}}},
               timeout=180)
    if r.status_code >= 400:
        raise RuntimeError("submit failed HTTP %d: %s" % (r.status_code, r.text[:200]))
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
    run_date, run_time, _ = latest_run()
    if run_date is None:
        print("   no ECMWF S4S run found in the last week")
        return
    print("   the S4S run: %s %s" % (run_date, run_time), flush=True)

    st = json.load(open(STATE)) if os.path.exists(STATE) else {"jobs": []}
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}

    for day0 in range(0, RUN_DAYS, CHUNK_DAYS):
        day1 = min(day0 + CHUNK_DAYS, RUN_DAYS)
        done = [j for j in st["jobs"]
                if j["chunk"] == day0 and j.get("status") == "decoded"]
        if done:
            continue
        print("   the chunk %d-%d days ..." % (day0, day1), flush=True)
        jid = submit(s, run_date, run_time, day0, day1)
        print("   the job %s" % jid, flush=True)
        if not wait(s, jid):
            st["jobs"].append({"chunk": day0, "job": jid, "status": "failed"})
            json.dump(st, open(STATE, "w"), indent=1)
            continue
        path = os.path.join(DATA, "_ec46_%d.grib" % day0)
        download(s, jid, path)
        vals = read_grib(path)
        os.remove(path)
        rec = out.setdefault("ec46", {"times": [], "values": [],
                                      "levels": list(LEVELS)})
        for t in sorted(vals):
            row = [vals[t].get(l) for l in LEVELS]
            if any(x is None for x in row):
                continue
            rec["times"].append(t)
            rec["values"].append(row)
        rec["run"] = "%s %s" % (run_date, run_time)
        rec["members"] = 51
        json.dump(out, open(OUT, "w"), indent=1)
        # and into the shared cache, under the same key the plotter reads
        cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
        cache["ec46"] = {"times": rec["times"], "values": rec["values"],
                         "levels": list(LEVELS), "run": rec["run"],
                         "members": 51}
        json.dump(cache, open(CACHE, "w"), indent=1)
        st["jobs"].append({"chunk": day0, "job": jid, "status": "decoded"})
        json.dump(st, open(STATE, "w"), indent=1)
        print("   the chunk decoded: %d times so far" % len(rec["times"]), flush=True)

    print("   the EC46 series: %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
