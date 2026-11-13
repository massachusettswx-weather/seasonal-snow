"""GEFS v12 (NOAA's sub-seasonal GEFS) polar-cap geopotential height, daily 12Z.

The seasonal route in `fetch_polar_models.py` uses the C3S sub-daily archive
and therefore only reaches the seasonal models.  For the sub-seasonal
guidance the same quantity - the area weighted (cos(lat)) mean geopotential
height over 60-90N on twelve pressure levels - has to come out of NOAA's own
GEFS, which is the suite NOAA now runs as its S2S system.

The route (measured, not assumed):

  * the archive lives on NOMADS under
        https://nomads.ncep.noaa.gov/pub/data/nccf/com/gens/prod/gefs.YYYYMMDD/HH/
    and is mirrored verbatim in the AWS open-data bucket
        https://noaa-gefs-pds.s3.amazonaws.com/gefs.YYYYMMDD/HH/
    The same tree also sits under `.../com/gens/v12.3/` (the version tag).
  * each cycle directory holds `atmos/pgrb2ap5/` and `atmos/pgrb2bp5/`: the
    0.50 degree GRIB2 product, split into two halves (the "a" half carries
    the surface and the middle troposphere, the "b" half the stratosphere).
    `atmos/pgrb2sp25/` is the 0.25 degree SURFACE-only subset, so it cannot
    serve the pressure levels.
  * the ensemble members are the files `gec00.*` (control) and `gep01.*` ...
    `gep30.*` (the perturbed members): 31 members a cycle.  NCEP also
    publishes the ensemble mean and the spread as `geavg.*` and `gespr.*`.
  * the twelve levels of the reference figure are spread over the two
    halves: the "a" half has 10, 50, 100, 200, 300, 500, 700, 850, 925 and
    1000 hPa, the "b" half 30 and 400 hPa.  Both halves are needed.
  * the GRIB2 `HGT` (geopotential height) is in GEOPOTENTIAL METRES, not in
    m2/s2 like the CDS `geopotential`: it is multiplied by 9.80665 here, so
    the series is on the same scale as the ERA5 half of the section.
  * the runs are initialised at 00Z, so the 12Z value of a day sits at a
    lead time of 12 + 24k hours - the same clock as the seasonal archive
    and the ERA5 half, so the series lands on the right calendar days.
  * only the HGT messages are downloaded: the `.idx` file beside every
    GRIB2 lists the byte offset of every message, so each of the twelve
    messages is fetched with an HTTP Range request (about 210 kB each)
    instead of the whole 15-90 MB file.

The ensemble mean is computed here from the 31 member files rather than
taken from NCEP's own `geavg` file, because `geavg` is only published once
the whole ensemble is done, and the live cycle is still in production.
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import LEVELS, read_grib_levels_sectors  # noqa: E402

# the shared cache the plotter reads; this script only ever touches its own
# key in it and never rewrites another model's record
CACHE = os.path.join(DATA, "polar_model_z.json")
STATE = os.path.join(DATA, "polar_gefs_jobs.json")
TAG = "gefsv12"

# the two hosts that serve the same tree
NOMADS = ("https://nomads.ncep.noaa.gov/pub/data/nccf/com/gens/prod/"
          "gefs.{date}/{hour}/")
MIRROR = "https://noaa-gefs-pds.s3.amazonaws.com/gefs.{date}/{hour}/"

# the GRIB2 "HGT" is geopotential metres; the series is in m2/s2
G0 = 9.80665

# the half that carries each level of the reference figure
PART_OF = {}
for _l in (10, 50, 100, 200, 300, 500, 700, 850, 925, 1000):
    PART_OF[_l] = "a"
for _l in (30, 400):
    PART_OF[_l] = "b"

PARTS = {"a": "pgrb2ap5/", "b": "pgrb2bp5/"}

# the forecast length: the S2S product runs out to 16 days
MAX_LEAD_H = 16 * 24

# how many requests at a time
THREADS = 10

UA = {"User-Agent": "Mozilla/5.0 (seas5 polar cap fetcher)"}

# the cycle this run is on; the URLs are built from it
DATE = None
HOUR = None


# ------------------------------------------------------------------ the http
def get(url, headers=None, tries=4, timeout=180):
    """A GET with a few retries: NOMADS answers 503 in bursts."""
    h = dict(UA)
    if headers:
        h.update(headers)
    last = None
    for k in range(tries):
        try:
            r = requests.get(url, headers=h, timeout=timeout)
            # 206 is a byte range answered, which is what most of the
            # requests here are
            if r.status_code in (200, 206):
                return r
            last = "HTTP %d" % r.status_code
        except Exception as e:                      # noqa: BLE001
            last = "%s: %s" % (type(e).__name__, str(e)[:80])
        time.sleep(1.5 * (k + 1))
    raise RuntimeError("%s -> %s" % (url, last))


def candidates(path):
    """The same file on every host that serves the tree."""
    return [t.format(date=DATE, hour=HOUR) + path for t in (NOMADS, MIRROR)]


def get_first(path, headers=None, tries=4):
    """The first host that answers wins."""
    last = None
    for url in candidates(path):
        try:
            return get(url, headers=headers, tries=tries)
        except Exception as e:                      # noqa: BLE001
            last = e
    raise RuntimeError("%s -> %s" % (path, last))


def head_size(path):
    for url in candidates(path):
        try:
            r = requests.head(url, headers=UA, timeout=60)
            if r.status_code == 200:
                return int(r.headers["Content-Length"])
        except Exception:                           # noqa: BLE001
            continue
    raise RuntimeError("no size for %s" % path)


def listing(url):
    """The names in a directory listing (Apache HTML or the S3 XML)."""
    r = get(url)
    t = re.sub(r"<script.*?</script>", "", r.text, flags=re.S)
    out = []
    for m in re.finditer(r"HREF=\"([^\"]+)\"", t, flags=re.I):
        n = m.group(1)
        if n.startswith("/") or n.startswith("?") or n == "../":
            continue
        out.append(n)
    if not out:
        for m in re.finditer(r"<Key>([^<]*)</Key>", t):
            n = m.group(1)
            if n.endswith("/"):
                continue
            out.append(n.rsplit("/", 1)[-1])
    return out


def subdirs(url):
    """The sub-directory names of one directory (the last path part)."""
    r = get(url)
    t = re.sub(r"<script.*?</script>", "", r.text, flags=re.S)
    out = []
    for m in re.finditer(r"HREF=\"([^\"]+)\"", t, flags=re.I):
        n = m.group(1).rstrip("/")
        if n.startswith("/") or n.startswith("?") or n == "..":
            continue
        out.append(n.rsplit("/", 1)[-1])
    if not out:
        for m in re.finditer(r"<Prefix>([^<]*)</Prefix>", t):
            n = m.group(1).rstrip("/")
            if n:
                out.append(n.rsplit("/", 1)[-1])
    return out


# ------------------------------------------------------------------ the cycle
def find_cycle():
    """-> (date, hour) of the newest cycle that has member files."""
    dates = set()
    for tmpl in (NOMADS, MIRROR):
        root = tmpl.split("gefs.")[0]
        try:
            for n in subdirs(root):
                if n.startswith("gefs."):
                    dates.add(n.split(".")[1])
        except Exception:                            # noqa: BLE001
            continue
    for d in sorted(dates, reverse=True):
        for tmpl in (NOMADS, MIRROR):
            root = tmpl.split("gefs.")[0] + "gefs.%s/" % d
            try:
                hours = [h for h in subdirs(root) if re.fullmatch(r"\d{2}", h)]
            except Exception:                        # noqa: BLE001
                continue
            for h in sorted(hours, reverse=True):
                if has_members(tmpl, d, h):
                    return d, h
    raise RuntimeError("no GEFS cycle with member files found")


def has_members(tmpl, d, h):
    """Is there a member file in this cycle?  One HEAD is enough."""
    url = (tmpl.format(date=d, hour=h) +
           "atmos/pgrb2ap5/gep01.t00z.pgrb2a.0p50.f000")
    try:
        r = requests.head(url, headers=UA, timeout=60)
        return r.status_code == 200
    except Exception:                                # noqa: BLE001
        return False


def member_prefixes(tmpl, d, h):
    """-> the member file prefixes of the cycle: gec00 (control) + gep01.."""
    names = listing(tmpl.format(date=d, hour=h) + "atmos/pgrb2ap5/")
    pref = set()
    for n in names:
        if n.endswith(".idx"):
            continue
        p = n.split(".")[0]
        if p.startswith("gec") or p.startswith("gep"):
            pref.add(p)
    ctl = sorted(p for p in pref if p.startswith("gec"))
    per = sorted(p for p in pref if p.startswith("gep"))
    return ctl + per


# ------------------------------------------------------------------ the idx
def read_idx(path):
    """-> [(offset, var, level)] of every message of one file."""
    r = get_first(path)
    out = []
    for line in r.text.strip().split("\n"):
        p = line.split(":")
        if len(p) < 6:
            continue
        try:
            off = int(p[1])
        except ValueError:
            continue
        out.append((off, p[3], p[4]))
    return out


# ------------------------------------------------------------------ one lead
def lead_members(members, fstep):
    """-> {member: {level: bytes}} - the twelve HGT messages of every member."""
    jobs = []

    def plan_for(m):
        plan = {}
        for part in ("a", "b"):
            base = "atmos/%s%s.t00z.pgrb2%s.0p50.f%03d" % (PARTS[part], m,
                                                           part, fstep)
            try:
                msgs = read_idx(base + ".idx")
            except Exception as e:                    # noqa: BLE001
                print("      the %s %s f%03d is not there (%s)"
                      % (m, part, fstep, str(e)[:60]), flush=True)
                continue
            if not msgs:
                continue
            try:
                size = head_size(base)
            except Exception as e:                    # noqa: BLE001
                print("      the %s %s f%03d has no size (%s)"
                      % (m, part, fstep, str(e)[:60]), flush=True)
                continue
            alloff = sorted(set(x[0] for x in msgs))
            for lev in LEVELS:
                if PART_OF[lev] != part:
                    continue
                hit = [o for o, v, l in msgs if v == "HGT" and l == "%d mb" % lev]
                if not hit:
                    continue
                jobs.append((m, part, lev, hit[0], alloff, size))
        return m

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        list(ex.map(plan_for, members))

    def one(job):
        m, part, lev, off, alloff, size = job
        base = "atmos/%s%s.t00z.pgrb2%s.0p50.f%03d" % (PARTS[part], m, part,
                                                       fstep)
        nxt = [o for o in alloff if o > off]
        end = nxt[0] if nxt else size
        r = get_first(base, headers={"Range": "bytes=%d-%d" % (off, end - 1)})
        return m, lev, r.content

    out = {m: {} for m in members}
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        for m, lev, blob in ex.map(one, jobs):
            out[m][lev] = blob
    return out


def read_cap_mean(path):
    """-> ({level: polar cap mean in m2/s2}, {sector: {level: mean}}, time).

    The sector means are the same reduction over one longitude sector, so
    the Atlantic and the Pacific can be drawn separately.
    """
    times, vals, sec = read_grib_levels_sectors(path)
    if not times:
        return {}, {}, None
    t = times[0]
    row = {int(l): float(v) * G0 for l, v in vals[t].items()}
    srow = {name: {int(l): float(v) * G0 for l, v in ld.items()}
            for name, ld in sec.get(t, {}).items()}
    return row, srow, t


# ------------------------------------------------------------------ the main
def main():
    global DATE, HOUR
    date, hour = find_cycle()
    DATE, HOUR = date, hour
    members = member_prefixes(NOMADS.format(date=date, hour=hour), date, hour)
    print("   the GEFS v12 cycle: %s %sZ" % (date, hour), flush=True)
    print("   the host: %s" % NOMADS.format(date=date, hour=hour), flush=True)
    print("   the members: %d (%s ... %s)"
          % (len(members), members[0], members[-1]), flush=True)

    st = json.load(open(STATE)) if os.path.exists(STATE) else {"leads": {}}
    out = {}

    # the daily 12Z leads: the 12Z value of a day is 12 + 24k hours from the
    # 00Z init, the same clock as the seasonal archive and the ERA5 half
    for fstep in range(12, MAX_LEAD_H + 1, 24):
        key = str(fstep)
        if st["leads"].get(key, {}).get("status") == "decoded":
            out[key] = st["leads"][key]
            print("   the lead %s is already decoded" % key, flush=True)
            continue
        print("   the lead f%03d ..." % fstep, flush=True)
        got = lead_members(members, fstep)
        got = {m: v for m, v in got.items() if len(v) == len(LEVELS)}
        if not got:
            print("      no member has this lead; stopping", flush=True)
            break
        # every member's twelve messages in one file: read_grib_levels
        # averages the fields that share a time and a level, which is the
        # ensemble mean
        tmp = os.path.join(DATA, "_gefs_f%03d.grib2" % fstep)
        with open(tmp, "wb") as f:
            for m in sorted(got):
                for lev in LEVELS:
                    f.write(got[m][lev])
        row, srow, t = read_cap_mean(tmp)
        os.remove(tmp)
        if not row or any(l not in row for l in LEVELS):
            print("      the lead f%03d did not carry the twelve levels"
                  % fstep, flush=True)
            continue
        out[key] = {"time": t, "values": [row[l] for l in LEVELS],
                     "members": len(got),
                     "sectors": {name: [sd[l] for l in LEVELS]
                                 for name, sd in srow.items()
                                 if all(l in sd for l in LEVELS)}}
        st["leads"][key] = dict(out[key], status="decoded")
        with open(STATE + ".tmp", "w") as f:
            json.dump(st, f, indent=1)
        os.replace(STATE + ".tmp", STATE)
        print("      %d members, valid %s, 10 hPa = %.0f m2/s2 (%.0f m)"
              % (len(got), t, row[10], row[10] / G0), flush=True)

    if not out:
        print("   nothing was decoded", flush=True)
        return

    # the record, in the shape the seasonal puller writes
    keys = sorted(out, key=lambda k: int(k))
    times = [out[k]["time"] for k in keys]
    values = [out[k]["values"] for k in keys]
    nmem = max(out[k]["members"] for k in keys)
    # the sector means, where the members carried them
    sectors = {}
    if all(out[k].get("sectors") for k in keys):
        # each lead carries the twelve level values for that sector
        sectors = {name: [out[k]["sectors"][name] for k in keys]
                   for name in out[keys[0]]["sectors"]}
    rec = {"times": times, "values": values, "members": nmem,
           "levels": list(LEVELS),
           "run": "%s %sZ" % (date, hour),
           "source": "NOAA GEFS v12 (0.50 deg pgrb2a+pgrb2b), the ensemble "
                     "mean of %d members" % nmem}
    if sectors:
        rec["sectors"] = sectors

    # into the shared cache, under this script's own key only: the file is
    # written whole, but every other model's record is left exactly as it
    # was found
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            cache = json.load(f)
    cache[TAG] = rec
    with open(CACHE + ".tmp", "w") as f:
        json.dump(cache, f)
    os.replace(CACHE + ".tmp", CACHE)
    print("   the %s series: %s (%d days, %s to %s)"
          % (TAG, CACHE, len(times), times[0], times[-1]), flush=True)


if __name__ == "__main__":
    main()
