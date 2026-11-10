"""Find which inits each non-ECMWF C3S seasonal system actually serves.

The MARS error for these systems is:
    "Restricted access to current C3S seasonal forecast non-ECMWF contribution.
     Please check that your date selection is valid."
i.e. the current init has not been released for that centre yet.  So we scan
backwards over init months until a system returns data, and record the first
init that works (the freshest available).

One request at a time - the CDS queue limit is account-wide.
"""
import os, sys, json, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
KEY = [l.split(":", 1)[1].strip() for l in open(os.path.join(HERE, ".cdsapirc"))
       if l.strip().startswith("key:")][0]
API = "https://cds.climate.copernicus.eu/api"
S = requests.Session()
S.headers.update({"PRIVATE-TOKEN": KEY})

# the centres the site publishes.  NCEP and BOM are in the C3S catalogue but
# are not on the site (NOAA is read from NOAA itself), so probing them only
# burns queue slots.
SYSTEMS = [
    ("ukmo-gloseas6",  "UKMO GloSeas6-GC5.1", "ukmo",  "610"),
    ("eccc-canesm5",   "ECCC CanESM5.1p1bc",  "eccc",  "4"),
    ("eccc-gem5",      "ECCC GEM5.2-NEMO",    "eccc",  "5"),
    ("cmcc-sps4",      "CMCC SPS4",           "cmcc",  "4"),
    ("dwd-gcfs2",      "DWD GCFS2.2",         "dwd",   "22"),
    ("meteo-france-s9","METFR System 9",      "meteo_france", "9"),
]

# scan backwards from the Nov 2026 init
MONTHS = [("2026", "11"), ("2026", "10"), ("2026", "09"), ("2026", "08"),
          ("2026", "07"), ("2026", "06"), ("2026", "05"), ("2026", "04"),
          ("2026", "03"), ("2026", "02"), ("2026", "01"), ("2025", "12"),
          ("2025", "11")]


def submit(ds, req):
    r = S.post("%s/retrieve/v1/processes/%s/execute" % (API, ds),
               json={"inputs": req}, timeout=120)
    if r.status_code not in (200, 201):
        return None, "HTTP %d %s" % (r.status_code, r.text[:120])
    return r.json().get("jobID"), None


def wait(jid, max_s=14400):
    t0 = time.time()
    while time.time() - t0 < max_s:
        time.sleep(10)
        try:
            j = S.get("%s/retrieve/v1/jobs/%s" % (API, jid), timeout=60).json()
        except Exception as e:
            return "err", str(e)[:120]
        st = j.get("status")
        if st in ("successful", "rejected", "failed"):
            return st, None
    return "timeout", None


def wait_long(jid, max_s=14400):
    """Poll one job until it is really finished.

    The CDS queue can hold a job for hours.  A client-side timeout says
    nothing about the data, so the same job is kept polling instead of
    being written off as "no data for this init".
    """
    t0 = time.time()
    while time.time() - t0 < max_s:
        time.sleep(20)
        try:
            j = S.get("%s/retrieve/v1/jobs/%s" % (API, jid), timeout=60).json()
        except Exception as e:
            print("      poll error: %s" % str(e)[:80], flush=True)
            continue
        st = j.get("status")
        if st in ("successful", "rejected", "failed"):
            return st, None
    return "timeout", None


def traceback(jid):
    try:
        r = S.get("%s/retrieve/v1/jobs?limit=30" % API, timeout=60).json()
        for j in r.get("jobs", []):
            if j.get("jobID") == jid:
                return ((j.get("metadata", {}).get("results", {}) or {})
                        .get("traceback", "") or "")
    except Exception:
        pass
    return ""


def try_init(ds, centre, system, y, m, var="snowfall"):
    req = {"originating_centre": centre, "system": system, "variable": var,
           "product_type": "monthly_mean", "year": y, "month": m,
           "leadtime_month": ["1"], "data_format": "grib"}
    jid, err = submit(ds, req)
    if err:
        return None, err
    st, err = wait_long(jid)
    if st == "successful":
        return "OK", None
    tb = traceback(jid)
    if "Restricted access" in tb:
        return "restricted", None
    if "Maximum number queued" in tb:
        return "queue", None
    return "fail", (tb[-400:] or st)


def main():
    out = {}
    p = os.path.join(DATA, "init_scan.json")
    if os.path.exists(p):
        out = json.load(open(p))
    for sid, name, centre, system in SYSTEMS:
        if sid in out and out[sid].get("init"):
            print("skip %s (init %s)" % (sid, out[sid]["init"]), flush=True)
            continue
        print("== %-16s %s:%s" % (sid, centre, system), flush=True)
        found = None
        for (y, m) in MONTHS:
            st, why = try_init("seasonal-monthly-single-levels", centre, system, y, m)
            print("   %s-%s -> %s %s" % (y, m, st, (why or "")[:90]), flush=True)
            if st == "OK":
                found = "%s-%s" % (y, m)
                break
            if st == "queue":
                time.sleep(120)
                continue
        out[sid] = {"name": name, "centre": centre, "system": system, "init": found}
        json.dump(out, open(p, "w"), indent=1)
        time.sleep(5)
    print("\n=== summary ===")
    for sid, v in out.items():
        print("  %-16s %s" % (sid, v.get("init") or "NOT FOUND"))


if __name__ == "__main__":
    main()
