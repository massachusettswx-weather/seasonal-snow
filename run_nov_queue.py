"""Keep a few C3S requests in flight and act on each as it completes.

The CDS behaviour that matters (measured on 11 Nov 2026):

  * A request is admitted with HTTP 201 and then, 20-45 s later, is REJECTED
    with "Maximum number queued requests for this dataset has been reached."
    The rejection is fast and costs nothing - the slot comes straight back.
  * A request that is NOT rejected stays "accepted" for hours and then
    completes.  Two of ours have been queued for eight hours and are still
    good.
  * The number that can be held at once is small, and a request is refused
    while we are already holding our share of the slots.

So the strategy is: keep a small pool of requests in flight, one per
dataset where possible, re-submit the ones that get refused, and act the
moment one completes.  Never hold one request open and wait for it - the
other slots go unused that way.

Each request carries as much as possible, because a slot is the scarce
thing: the CDS takes a LIST of variables, so a centre's snowfall and its
sea-surface temperature come back in one request.

    python3 run_nov_queue.py [--only step,step] [--step step] [--dry-run]
    python3 run_nov_queue.py --watch JOBID,STEP[,JOBID,STEP ...]
"""
import os
import sys
import json
import time
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cds_direct                                       # noqa: E402

DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
STATE = os.path.join(DATA, "models_fetched.json")
POOL = os.path.join(DATA, "nov_pool.json")

# The init every centre is being moved onto.
INIT = "2026-11"
LEADS = [str(k) for k in range(1, 7)]

DS_MONTHLY_SL = "seasonal-monthly-single-levels"
DS_MONTHLY_PL = "seasonal-monthly-pressure-levels"
DS_ORIGINAL_SL = "seasonal-original-single-levels"

# How many requests to keep in flight at once.  Measured on 11 Nov: with two
# of ours outstanding a third is often refused after ~30 s, but three have
# been held at once (21:18, 00:14 and 04:25 all sat queued together).  A
# refusal is free - the slot comes straight back - so the pool asks again.
POOL_SIZE = 3

# How long to wait before asking again after a refusal.  The cap is on how
# many requests we hold, so asking again too soon only collects more
# refusals.
REFUSED_WAIT = 300

# Requests that were submitted earlier and are still queued.  They hold a
# slot, so the pool must not submit the same step again - and when one of
# them completes it is acted on like any other.
PENDING = os.path.join(DATA, "nov_pending.json")

# (step, tag, name, centre, system, kind, fields)
STEPS = [
    ("bom-snow", "bom-access-s2", "BOM ACCESS-S2", "bom", "2", "snow", ["snow"]),
    ("eccc-can", "eccc-canesm5", "ECCC CanESM5.1p1bc", "eccc", "4", "snow", ["snow"]),
    ("jma-snow", "jma-jra3", "JMA JRA3-25", "jma", "7", "snow", ["snow"]),
    ("eccc-gem", "eccc-gem5", "ECCC GEM5.2-NEMO", "eccc", "5", "snow", ["snow"]),
    ("jma-rest", "jma-jra3", "JMA JRA3-25", "jma", "7", "clim+u10", ["clim", "u10"]),
    ("ecmwf-ext", "ecmwf-seas5", "ECMWF SEAS5", "ecmwf", "51", "ext", ["ext"]),
    ("ukmo-ext", "ukmo-gloseas6", "UKMO GloSeas6-GC5.1", "ukmo", "610", "ext", ["ext"]),
]


def target_for(tag, kind):
    if kind == "snow":
        return os.path.join(MDIR, tag, "snowfall_monthly.grib")
    if kind == "sst":
        return os.path.join(MDIR, tag, "sst_monthly.grib")
    if kind == "clim":
        return os.path.join(MDIR, tag, "snowfall_hindcast.grib")
    if kind == "u10":
        return os.path.join(MDIR, tag, "u10_monthly.grib")
    if kind == "ext":
        return os.path.join(MDIR, tag, "snowfall_ext.grib")
    return os.path.join(MDIR, tag, "u10_monthly.grib")


def record_init(tag, name, centre, system, init):
    p = os.path.join(DATA, "models_fetched.json")
    st = json.load(open(p)) if os.path.exists(p) else {}
    rec = st.get(tag, {})
    rec.update({"name": name, "centre": centre, "system": system,
                "init": init, "probe_date": time.strftime("%Y-%m-%d")})
    st[tag] = rec
    json.dump(st, open(p, "w"), indent=1)
    print("   %s is on the %s init" % (tag, init), flush=True)


# ---------------------------------------------------------------- requests
def build_requests(kind, centre, system):
    """-> [(dataset, request-dict, [(kind, filename), ...]), ...]"""
    common = {"originating_centre": centre, "system": system,
              "year": INIT[:4], "month": INIT[5:7], "data_format": "grib"}
    if kind == "snow":
        # the snowfall and the SST of a centre come from the same dataset and
        # the same leads, so they travel in ONE request
        return [(DS_MONTHLY_SL,
                 dict(common, variable=["snowfall", "sea_surface_temperature"],
                      product_type="monthly_mean", leadtime_month=LEADS),
                 [("snow", "snowfall_monthly.grib"), ("sst", "sst_monthly.grib")])]
    if kind == "sst":
        return [(DS_MONTHLY_SL,
                 dict(common, variable="sea_surface_temperature",
                      product_type="monthly_mean", leadtime_month=LEADS),
                 [("sst", "sst_monthly.grib")])]
    if kind == "clim":
        return [(DS_MONTHLY_SL,
                 dict(common, variable="snowfall",
                      product_type="hindcast_climate_mean", leadtime_month=LEADS),
                 [("clim", "snowfall_hindcast.grib")])]
    if kind == "u10":
        return [(DS_MONTHLY_PL,
                 dict(common, variable="u_component_of_wind", pressure_level="10",
                      product_type="monthly_mean", leadtime_month=LEADS),
                 [("u10", "u10_monthly.grib")])]
    if kind == "ext":
        # the lead months past the sixth only exist in the sub-daily product,
        # where every step carries its own accumulation
        hours = [str(h) for h in range(181 * 24, 216 * 24, 12)]
        return [(DS_ORIGINAL_SL,
                 dict(common, variable="snowfall", day="01", leadtime_hour=hours),
                 [("ext", "snowfall_ext.grib")])]
    return []


# ----------------------------------------------------------------- helpers
def decode_ext(path, tag):
    """The renderer reads the decoded months, not the GRIB."""
    from fetch_snow_daily import read_snow, save_npz
    months, members, acc, glat, glon = read_snow(path)
    if months and acc is not None:
        save_npz(path.replace(".grib", ".npz"), months, members, acc, glat, glon,
                 meta=dict(tag=tag, init=INIT, kind="extended"))
        print("   %s/ext: %d extended month(s) %s"
              % (tag, len(months), ["%04d-%02d" % m for m in months]), flush=True)
    else:
        print("   %s/ext: nothing past the sixth month" % tag, flush=True)


def split_combined(path, tag, kinds):
    """A request that carried two variables comes back as one file - split it
    into the per-variable files the rest of the pipeline expects.

    The combined file is only deleted once every variable has been split out
    of it, so a failure never loses the download.
    """
    import split_grib
    tmp = path + ".combined"
    os.replace(path, tmp)
    try:
        outs, counts = split_grib.split(tmp, os.path.dirname(path),
                                        [k for k, _ in kinds])
    except Exception as e:
        os.replace(tmp, path)          # put it back
        raise
    ok = True
    for kind, fname in kinds:
        p = os.path.join(os.path.dirname(path), fname)
        if kind in outs:
            shutil.move(outs[kind], p)
            print("   %s: %s split out (%d messages)"
                  % (tag, kind, counts[kind]), flush=True)
        elif not os.path.exists(p):
            print("   %s: %s is MISSING from the combined file" % (tag, kind),
                  flush=True)
            ok = False
    if os.path.exists(tmp):
        os.remove(tmp)
    return ok


def download(c, jid, tag, kinds):
    """Download a completed job and put the files where they belong."""
    outs = [target_for(tag, k) for k, _ in kinds]
    os.makedirs(os.path.dirname(outs[0]), exist_ok=True)
    tmp = outs[0] + ".part"
    c.download_job(jid, tmp)
    if len(kinds) > 1:
        split_combined(tmp, tag, kinds)
        os.remove(tmp) if os.path.exists(tmp) else None
    else:
        os.replace(tmp, outs[0])
    for p in outs:
        if os.path.exists(p):
            print("   %s: saved %s (%.1f MB)"
                  % (tag, os.path.basename(p), os.path.getsize(p) / 1e6),
                  flush=True)
    return True


def status_of(c, jid):
    s = c.job_status(jid)
    if s == "gone":
        # the detail endpoint 404s transiently while a record is
        # re-indexed, and the job list is not a reliable witness either
        # (it only shows the most recent records) - so ask again
        for _ in range(4):
            time.sleep(20)
            s = c.job_status(jid)
            if s != "gone":
                return s
    return s


# -------------------------------------------------------------------- pool
class Pool(object):
    """A small set of requests in flight, acted on as each completes.

    The CDS judges a request 20-45 s after it is admitted, so the pool waits
    for that verdict before drawing its next one: submitting a burst just
    means most of the burst is thrown away.
    """

    def __init__(self, c, steps):
        self.c = c
        self.steps = steps
        self.live = {}          # job id -> (step, dataset, kinds, since)
        self.next_at = {}       # step -> when it may be submitted again
        self.last_submit = 0.0  # when the last request was put in

    def submit(self, step, tag, name, centre, system, kind, fields):
        """Try to start one request for this step.  True if one is now live."""
        if step in self.next_at and time.time() < self.next_at[step]:
            return False
        # one at a time: the verdict on the last one has to come first
        if time.time() - self.last_submit < 75:
            return False
        f = fields[0]
        for dataset, req, kinds in build_requests(f, centre, system):
            try:
                jid = self.c.submit(dataset, req)
            except Exception as e:
                msg = str(e)
                if "Maximum number queued" in msg:
                    print("   %s: %s is full - waiting" % (step, dataset), flush=True)
                    self.next_at[step] = time.time() + REFUSED_WAIT
                    continue
                print("   %s: refused (%s)" % (step, msg[:70]), flush=True)
                self.next_at[step] = time.time() + 300
                continue
            print("   %s: submitted %s on %s" % (step, jid[:12], dataset), flush=True)
            self.live[jid] = (step, dataset, kinds, time.time())
            self.last_submit = time.time()
            return True
        return False

    def poll(self):
        """Act on the live requests.  Returns True when something finished."""
        acted = False
        self.finished = []
        for jid in list(self.live):
            step, dataset, kinds, since = self.live[jid]
            # a request is admitted and then judged 20-45 s later, so give it
            # that long before asking - asking early just adds noise
            if time.time() - since < 60:
                continue
            s = status_of(self.c, jid)
            if s == "successful":
                tag = self.steps[step][1]
                try:
                    download(self.c, jid, tag, kinds)
                    acted = True
                except Exception as e:
                    print("   %s: download failed (%s)" % (step, str(e)[:80]), flush=True)
                del self.live[jid]
                self.finished.append((step, jid, True))
            elif s in ("failed", "rejected", "dismissed", "gone"):
                print("   %s: %s after %d min - will retry"
                      % (step, s, (time.time() - since) / 60), flush=True)
                del self.live[jid]
                self.finished.append((step, jid, False))
                # a refusal means the cap was reached, so wait longer than
                # for a job that simply failed
                wait = REFUSED_WAIT if s == "rejected" else 90
                self.next_at[step] = time.time() + wait
        return acted

    def held(self, step):
        """Is a request for this step already in flight?"""
        return any(v[0] == step for v in self.live.values())


def load_pending(steps):
    """Requests submitted earlier that are still queued.  They hold a slot,
    so their step must not be submitted again."""
    pend = {}
    if not os.path.exists(PENDING):
        return pend
    try:
        pend = json.load(open(PENDING))
    except Exception:
        return {}
    return {k: v for k, v in pend.items() if k in steps}


def save_pending(pend):
    json.dump(pend, open(PENDING, "w"), indent=1)


def run_pool(c, steps, only_step=None, only=None, dry=False):
    pool = Pool(c, steps)
    order = list(steps.values())
    pend = load_pending(steps)
    # adopt the already-queued requests so their slots are not wasted
    for step, jid in list(pend.items()):
        s = c.job_status(jid)
        if s in ("accepted", "running", "queued"):
            tag = steps[step][1]
            kinds = build_requests(steps[step][6][0], steps[step][3],
                                   steps[step][4])[0][2]
            ds = steps[step][6][0]
            pool.live[jid] = (step, DS_ORIGINAL_SL if ds == "ext" else DS_MONTHLY_SL,
                              kinds, time.time())
            print("   %s: adopted the queued request %s (%s)"
                  % (step, jid[:12], s), flush=True)
        else:
            print("   %s: the queued request %s is %s - will re-ask"
                  % (step, jid[:12], s), flush=True)
            del pend[step]
    save_pending(pend)
    last_report = 0
    while True:
        # fill the pool
        if not dry:
            for step, tag, name, centre, system, kind, fields in order:
                if only_step and step != only_step:
                    continue
                if only and step not in only:
                    continue
                if len(pool.live) >= POOL_SIZE:
                    break
                if step in pend:
                    continue          # already queued from before
                if pool.held(step):
                    continue          # already in flight
                # skip a step whose files are already on disk for this init
                st = json.load(open(STATE)) if os.path.exists(STATE) else {}
                rec = st.get(tag, {})
                if rec.get("init") == INIT and kind != "ext":
                    outs = [target_for(tag, k) for k, _
                            in build_requests(fields[0], centre, system)[0][2]]
                    if all(os.path.exists(p) and os.path.getsize(p) > 10000
                           for p in outs):
                        continue
                if pool.submit(step, tag, name, centre, system, kind, fields):
                    pend[step] = [j for j, v in pool.live.items() if v[0] == step][0]
                    save_pending(pend)
                    break               # one at a time: wait for the verdict

        acted = pool.poll()
        for step, jid, ok in getattr(pool, "finished", []):
            # whatever the outcome, the step needs asking again unless its
            # files are now on disk
            pend.pop(step, None)
            save_pending(pend)
        if acted:
            # a centre is on the November init once ITS forecast is on disk
            for step, tag, name, centre, system, kind, fields in order:
                if kind == "ext":
                    continue
                st = json.load(open(STATE)) if os.path.exists(STATE) else {}
                rec = st.get(tag, {})
                if rec.get("init") == INIT:
                    continue
                p = target_for(tag, "snow")
                if os.path.exists(p) and os.path.getsize(p) > 10000:
                    record_init(tag, name, centre, system, INIT)
        if time.time() - last_report > 300:
            last_report = time.time()
            print("   [pool] %d in flight: %s"
                  % (len(pool.live), ", ".join(
                      "%s/%s" % (v[0], v[1].split("-")[-1]) for v in pool.live.values())),
                  flush=True)
        if dry:
            break
        time.sleep(25)


def watch(c, pairs):
    """Act on requests that were submitted elsewhere."""
    live = {}
    for jid, step in pairs:
        live[jid] = step
    while live:
        for jid in list(live):
            step = live[jid]
            s = status_of(c, jid)
            if s == "successful":
                st = json.load(open(STATE)) if os.path.exists(STATE) else {}
                for k, v in st.items():
                    if v.get("name", "").lower() in step.lower() or k in step:
                        tag = k
                        break
                else:
                    tag = None
                if tag:
                    kinds = [("snow", "snowfall_monthly.grib")]
                    try:
                        download(c, jid, tag, kinds)
                    except Exception as e:
                        print("   %s: download failed (%s)" % (step, str(e)[:80]), flush=True)
                del live[jid]
            elif s in ("failed", "rejected", "dismissed", "gone"):
                print("   %s: %s" % (step, s), flush=True)
                del live[jid]
        time.sleep(30)


def main():
    dry = "--dry-run" in sys.argv
    only = []
    if "--only" in sys.argv:
        only = [x for x in sys.argv[sys.argv.index("--only") + 1].split(",") if x]
    only_step = ""
    if "--step" in sys.argv:
        only_step = sys.argv[sys.argv.index("--step") + 1]
    c = cds_direct.CDSDirect()
    steps = {s[0]: s for s in STEPS}

    if "--watch" in sys.argv:
        pairs = []
        for item in sys.argv[sys.argv.index("--watch") + 1].split(","):
            if ":" in item:
                j, s = item.split(":", 1)
                pairs.append((j, s))
        watch(c, pairs)
        return

    if dry:
        for step, tag, name, centre, system, kind, fields in STEPS:
            if only_step and step != only_step:
                continue
            print("== %s (%s:%s) %s" % (tag, centre, system, kind), flush=True)
            for f in fields:
                for ds, req, kinds in build_requests(f, centre, system):
                    print("   would fetch %s from %s"
                          % (", ".join(k for k, _ in kinds), ds), flush=True)
        return

    run_pool(c, steps, only_step=only_step, only=only, dry=dry)


if __name__ == "__main__":
    main()
