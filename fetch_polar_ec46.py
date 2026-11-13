"""The ECMWF extended range (the 46-day ensemble) from the OPEN DATA portal.

The portal is free and open: since 1 October 2025 the whole real-time
catalogue, the extended-range ensemble included, is published under CC-BY
with no data cost.  What it does have is a delay - the run's contents
appear about two days after the run - so the run that can be had is the one
from roughly 48 hours ago.  The extended range is produced on the days it
runs (Mondays and Thursdays, 00Z), so the search walks back until the
portal answers.

Nothing here needs the ECDS licence: the files are plain GRIB2 on the
public bucket, and every message is fetched by its byte range out of the
run's index file, so only the geopotential height messages are downloaded
rather than whole global files.

What lands on disk:
    data/polar_ec46_z.json   the series for the EC46
    data/polar_model_z.json  the same series merged in under "ec46"

Each entry of the series is
    {"time": "YYYY-MM-DD HH", "levels": {level: metres}, ...}
plus the cap mean, the two sector means and the member count.
"""
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "polar_ec46_z.json")
CACHE = os.path.join(DATA, "polar_model_z.json")
TAG = "ec46"

BUCKET = "https://ecmwf-forecasts.s3.amazonaws.com"
PORTAL = "https://data.ecmwf.int/forecasts"

# the twelve levels the section is drawn on, in hPa
LEVELS = [10, 30, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]

# the run that can be had: the portal holds the run's contents with a two-day
# delay, so the search starts 48 hours back
DELAY_HOURS = 48

# the window the section is drawn over: thirty-five days
MAX_STEP = 840

# the products the portal holds that are NOT the extended range
NOT_OURS = ("ifs", "aifs-ens", "aifs-single")


def _get(url, headers=None, timeout=120, tries=3):
    import requests
    last = None
    for k in range(tries):
        try:
            r = requests.get(url, headers=headers or {}, timeout=timeout)
            if r.status_code == 200:
                return r.content
            last = "HTTP %d" % r.status_code
        except Exception as exc:                        # noqa: BLE001
            last = str(exc)
        time.sleep(2 * (k + 1))
    raise RuntimeError("could not read %s (%s)" % (url, last))


def list_prefix(prefix):
    """-> [the immediate prefixes under a bucket prefix]."""
    xml = _get("%s/?list-type=2&delimiter=/&prefix=%s" % (BUCKET, prefix))
    out = []
    for m in re.finditer(r"<Prefix>([^<]+)</Prefix>", xml.decode()):
        p = m.group(1)
        if p.rstrip("/") == prefix.rstrip("/"):
            continue            # the listing echoes the prefix itself
        out.append(p)
    return out


def find_run(back_days=6):
    """-> (the run path, the product prefix) for the freshest extended range.

    The run the portal can give us is the one from about 48 hours ago; the
    extended range is only produced on the days it runs, so the search
    walks back until a product shows up that is not the IFS or the AIFS.
    """
    first = date.today() - timedelta(hours=DELAY_HOURS)
    for back in range(back_days + 1):
        d = first - timedelta(days=back)
        for hh in ("00", "06", "12", "18"):
            base = "%s/%sz/" % (d.strftime("%Y%m%d"), hh)
            try:
                kids = list_prefix(base)
            except Exception as exc:                    # noqa: BLE001
                print("   %s: %s" % (base, exc))
                continue
            for k in kids:
                name = k.rstrip("/").rsplit("/", 1)[-1]
                if name in NOT_OURS or name.startswith("."):
                    continue
                print("   found the extended range at %s%s" % (base, name))
                return base, k
    return None, None


def list_files(prefix):
    """-> [the file names under a prefix]."""
    xml = _get("%s/?list-type=2&prefix=%s&max-keys=1000" % (BUCKET, prefix))
    return [m.group(1) for m in re.finditer(r"<Key>([^<]+)</Key>", xml.decode())]


def parse_index(text):
    """-> [(the byte start, the byte end, the line)] for every message.

    The ECMWF open-data index has the byte range in the first two fields
    after the message number; the NCEP style (one offset, the end implied
    by the next message) is handled as well.
    """
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        f = line.split(":")
        try:
            start = int(f[1])
        except (IndexError, ValueError):
            continue
        end = None
        if len(f) > 2 and f[2].isdigit():
            end = int(f[2])
        rows.append((start, end, line))
    for i, (start, end, line) in enumerate(rows):
        if end is None:
            nxt = rows[i + 1][0] if i + 1 < len(rows) else None
            rows[i] = (start, nxt, line)
    return rows


def wanted(level, line):
    """Does this index line carry the geopotential height at this level?"""
    if ":HGT:" not in line and ":gh:" not in line \
            and "Geopotential" not in line and "Geopotential height" not in line:
        return False
    m = re.search(r":(\d+)\s*mb:", line)
    if not m:
        return False
    return int(m.group(1)) == level


def decode_blob(blob, levels):
    """-> {level: value} for one GRIB message, and its ensemble member."""
    import eccodes
    gid = eccodes.codes_grib_new_from_message(blob)
    if gid is None:
        return None, None
    try:
        lev = int(eccodes.codes_get(gid, "level"))
        vals = np.asarray(eccodes.codes_get_array(gid, "values"), float)
        lats = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
        lons = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
        ni = int(eccodes.codes_get(gid, "Ni", 0) or 0)
        nj = int(eccodes.codes_get(gid, "Nj", 0) or 0)
        if not (ni and nj and vals.size == ni * nj):
            return None, None
        vals = vals.reshape(nj, ni)
        lats = lats.reshape(nj, ni)
        lons = lons.reshape(nj, ni)
        try:
            member = int(eccodes.codes_get(gid, "number"))
        except Exception:                               # noqa: BLE001
            member = 0
        return (lev, vals, lats, lons, member)
    finally:
        eccodes.codes_release(gid)


def fetch_run(run_prefix, product_prefix, out_path=OUT, limit_steps=None):
    """Download the extended range and reduce it to the polar-cap means."""
    from polar_cap import SECTORS, sector_mean, zonal_mean

    # the product's own tree: <product>/<resolution>/<stream>/<files>
    res = list_prefix(product_prefix)
    stream = None
    for r in res:
        kids = list_prefix(r)
        for k in kids:
            if k.rstrip("/").endswith("enfo"):
                stream = k
                break
        if stream:
            break
    if stream is None:
        # fall back: the first tree that holds .index files
        for r in res:
            for k in list_prefix(r):
                files = list_files(k)
                if any(f.endswith(".index") for f in files):
                    stream = k
                    break
            if stream:
                break
    if stream is None:
        raise RuntimeError("no message stream found under %s" % product_prefix)

    print("   the message stream: %s" % stream)
    files = list_files(stream)
    steps = {}
    for f in files:
        m = re.search(r"-(\d+)h-", f)
        if not m or not f.endswith(".grib2"):
            continue
        steps.setdefault(int(m.group(1)), []).append(f)

    wanted_steps = sorted(s for s in steps if 24 <= s <= MAX_STEP)
    if limit_steps:
        wanted_steps = wanted_steps[:limit_steps]
    if not wanted_steps:
        raise RuntimeError("no steps in the run's file list")

    print("   %d steps to draw (every 24 h out to %d h)" % (len(wanted_steps),
                                                             MAX_STEP))
    series = {}
    members = set()
    for step in wanted_steps:
        got = False
        for name in steps[step]:
            if not name.endswith(".grib2"):
                continue
            url = "%s/%s" % (BUCKET, name)
            idx_url = url[: -len(".grib2")] + ".index"
            try:
                index = _get(idx_url).decode("utf-8", "ignore")
            except Exception as exc:                    # noqa: BLE001
                print("   step %d: no index (%s)" % (step, exc))
                continue
            rows = parse_index(index)
            for level in LEVELS:
                for start, end, line in rows:
                    if not wanted(level, line):
                        continue
                    if end is None:
                        continue
                    blob = _get(url, headers={"Range": "bytes=%d-%d" % (start, end - 1)})
                    try:
                        dec = decode_blob(blob, LEVELS)
                    except Exception:                     # noqa: BLE001
                        continue
                    if dec is None:
                        continue
                    lev, vals, lats, lons, member = dec
                    if lev != level:
                        continue
                    members.add(member)
                    key = "%s" % name
                    rec = series.setdefault(key, {})
                    rec.setdefault(str(step), {})[str(level)] = {
                        "cap": float(zonal_mean(vals, lats)),
                        "sectors": {k: float(sector_mean(vals, lats, lons[0, :], a, b))
                                    for k, (a, b) in SECTORS.items()},
                        "member": member,
                    }
                    got = True
        print("   step %3d h: %s" % (step, "read" if got else "nothing"))

    if not series:
        raise RuntimeError("no data came back - nothing was written")
    payload = {"tag": TAG, "run": run_prefix.strip("/").replace("/", " "),
               "members": len(members) or None, "files": series}
    with open(out_path, "w") as f:
        json.dump(payload, f)
    print("   wrote %s (%d members, %d files)"
          % (out_path, len(members) or 0, len(series)))
    return payload


def merge_into_cache(payload):
    """Put the EC46 series into the shared cache the plotter reads."""
    try:
        cache = json.load(open(CACHE))
    except Exception:                                   # noqa: BLE001
        cache = {}
    cache[TAG] = payload
    with open(CACHE, "w") as f:
        json.dump(cache, f)
    print("   merged into %s under '%s'" % (CACHE, TAG))


def main():
    run, product = find_run()
    if not run:
        print("the portal has no extended range for a run that is %d hours old"
              % DELAY_HOURS)
        return 1
    payload = fetch_run(run, product)
    merge_into_cache(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
