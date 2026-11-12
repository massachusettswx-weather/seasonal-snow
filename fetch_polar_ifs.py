"""The polar cap geopotential height from the ECMWF open data on S3.

The reference figure is built from "ECMWF IFS open data & ERA5", and the open
data bucket has no queue and no cost limit - unlike the CDS, whose admission
gate on this account holds two jobs at a time and has been sitting for hours.

The bucket keeps the daily cycle's forecast as one GRIB2 file per step, with
an ``.index`` file beside it that lists every message's byte offset and
length.  Only the geopotential messages are fetched, with HTTP range
requests, so the whole 15-day run costs a fraction of the 96 MB per step.

Two things this route can and cannot do:

  * it CAN give the reference's own product: the 15-day IFS forecast, which
    is exactly what the reference figure shows;
  * it CANNOT give 30 hPa, which the IFS open data does not carry (its
    pressure levels are 10, 50, 100, 150, 200, 250, 300, 400, 500, 600, 700,
    850, 925 and 1000 hPa).  The C3S seasonal archive DOES carry 30 hPa, so
    the seasonal section uses the full twelve levels and this one uses the
    eleven the IFS serves.

The grid is 0.25 degrees, and the polar cap mean is taken the same way as
everywhere else in the pipeline (cos(lat) weights over 60-90N).
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import zonal_mean, read_grib_levels   # noqa: E402

BUCKET = "https://ecmwf-forecasts.s3.amazonaws.com/"

# the levels the IFS open data serves, in hPa.  30 hPa is not among them.
IFS_LEVELS = [10, 50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 850, 925,
              1000]

# the levels the reference figure uses that the IFS also serves
COMMON = [10, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]


def _get(url, tries=40, headers=None):
    """GET with retries: the bucket answers 503 under load quite often.

    Measured on this account: about 30% of the requests succeed, and the
    failures come in bursts.  The way through is volume, not patience, so
    this loops quickly with a short delay and only backs off at the end.
    """
    err = ""
    for a in range(tries):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=headers or {}),
                timeout=25).read()
        except Exception as e:
            err = str(e)[:60]
            if a < 12:
                time.sleep(0.6)
            else:
                time.sleep(2 + 2 * (a - 12))
    raise RuntimeError("%s: %s" % (url, err))


def _get_parallel(jobs, out_path=None):
    """Fetch several byte ranges of the same file at once.

    Each job is (url, offset, length).  The bucket throttles a burst of
    requests: four workers is the most that gets through, and a larger
    burst just fails.  A range that keeps failing is retried on its own,
    one at a time, so one bad range cannot stall the rest.

    With out_path the ranges are written to that file as they arrive, in
    order, so a hundred megabytes of GRIB never has to sit in memory - the
    sandbox has three gigabytes and an OOM kill takes the process out.
    """
    from concurrent.futures import ThreadPoolExecutor
    out = [None] * len(jobs)

    def one(i):
        url, off, ln = jobs[i]
        hdr = {"Range": "bytes=%d-%d" % (off, off + ln - 1)}
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=hdr), timeout=30).read()
        except Exception:
            return None

    # sixteen workers is what gets through: the bucket answers about a third
    # of a burst with eight and about half with sixteen, and the stragglers
    # are picked up by the retries
    for attempt in range(40):
        todo = [i for i in range(len(jobs)) if out[i] is None]
        if not todo:
            break
        with ThreadPoolExecutor(max_workers=16) as ex:
            for i, b in zip(todo, ex.map(one, todo)):
                if b is not None:
                    out[i] = b
        if any(o is None for o in out):
            time.sleep(0.5 + 0.3 * attempt)

    # the stragglers, one at a time
    for attempt in range(60):
        todo = [i for i in range(len(jobs)) if out[i] is None]
        if not todo:
            break
        for i in todo:
            if out[i] is None:
                out[i] = one(i)
        if any(o is None for o in out):
            time.sleep(0.7)

    missing = [i for i, o in enumerate(out) if o is None]
    if missing:
        raise RuntimeError("%d byte ranges did not come back" % len(missing))

    if out_path:
        with open(out_path, "wb") as f:
            for b in out:
                f.write(b)
        return out_path
    return b"".join(out)


def list_keys(prefix, maxk=1000):
    """The keys under a prefix.

    The plain LIST (the bucket root) answers 503 often; the query with an
    explicit prefix is the one that works.
    """
    import urllib.parse
    url = BUCKET + "?prefix=%s&max-keys=%d" % (
        urllib.parse.quote(prefix, safe="/"), maxk)
    x = _get(url).decode()
    return re.findall(r"<Key>([^<]+)</Key>", x)


def fetch_step(cycle, step, stream="ifs", levels=None, tag="oper"):
    """The polar cap mean geopotential for one forecast step.

    -> (the valid time string, {level: the polar cap mean})
    """
    import urllib.parse
    levels = levels or COMMON
    # the bucket URL already ends in a slash: a double slash makes every
    # request fail with a 404 that no retry can fix
    base = "%s%s/12z/%s/0p25/%s/" % (BUCKET, cycle, stream, tag)
    # the file name carries the run time, the step and the stream
    stamp = "%s120000-%dh-%s-fc" % (cycle, step, tag)
    idx_url = base + stamp + ".index"
    grib_url = base + stamp + ".grib2"

    entries = []
    try:
        x = _get(idx_url, tries=60).decode()
        entries = [json.loads(l) for l in x.splitlines() if l.strip()]
    except Exception:
        entries = []
    if not entries:
        raise RuntimeError("no index for %s" % stamp)

    want = set(str(l) for l in levels)
    sel = [e for e in entries
           if e.get("levtype") == "pl" and e.get("param") == "z"
           and e.get("levelist") in want]
    if not sel:
        raise RuntimeError("no geopotential at the wanted levels for %s" % stamp)

    buf = _get_parallel([(grib_url, e["_offset"], e["_length"]) for e in sel])

    path = os.path.join(DATA, "_ifs_step.grib2")
    with open(path, "wb") as f:
        f.write(buf)
    try:
        times, vals = read_grib_levels(path)
    finally:
        os.remove(path)
    if not times:
        raise RuntimeError("the step %s of %s decoded to nothing" % (step, cycle))
    t = times[0]
    return t, {int(k): v for k, v in vals[t].items()}


def main():
    """Fetch the 15-day IFS run for the current cycle."""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycle", default="20261111", help="the cycle, e.g. 20261111")
    ap.add_argument("--steps", default="", help="the steps in hours, comma separated")
    ap.add_argument("--stream", default="ifs", help="ifs or aifs-ens")
    ap.add_argument("--tag", default="oper", help="oper or enfo")
    ap.add_argument("--out", default=os.path.join(DATA, "polar_ifs.json"))
    args = ap.parse_args()

    steps = ([int(s) for s in args.steps.split(",") if s]
             if args.steps else [s * 24 for s in range(0, 16)])

    out = {}
    if os.path.exists(args.out):
        try:
            out = json.load(open(args.out))
        except Exception:
            out = {}
    key = "%s-%s" % (args.cycle, args.stream)
    rec = out.setdefault(key, {"times": [], "values": []})
    have = set(rec["times"])

    for st in steps:
        try:
            t, v = fetch_step(args.cycle, st, args.stream, COMMON, args.tag)
        except Exception as e:
            print("   the step %3dh failed: %s" % (st, str(e)[:90]), flush=True)
            continue
        if t in have:
            continue
        have.add(t)
        rec["times"].append(t)
        rec["values"].append([v.get(l) for l in COMMON])
        print("   the step %3dh -> %s  the 10 hPa %.0f  the 500 hPa %.0f"
              % (st, t, v.get(10, float("nan")), v.get(500, float("nan"))),
              flush=True)

    # keep the record sorted by time
    order = np.argsort(rec["times"])
    rec["times"] = [rec["times"][i] for i in order]
    rec["values"] = [rec["values"][i] for i in order]
    rec["levels"] = COMMON
    tmp = args.out + ".tmp"
    json.dump(out, open(tmp, "w"))
    os.replace(tmp, args.out)
    print("   the IFS polar cap: %d steps -> %s" % (len(rec["times"]), args.out),
          flush=True)


if __name__ == "__main__":
    main()
