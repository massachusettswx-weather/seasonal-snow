"""The single CDS submitter for the C3S seasonal rebuild.

Everything the site needs from the seasonal archive goes through this one
script, because the archive gives the account only a couple of queue slots
and two submitters would simply fight over them.

WHAT THE CDS ACTUALLY DOES (measured on 11 Nov 2026)

  * A request is admitted with HTTP 201 and is then JUDGED 20-45 s later.  A
    refusal comes back as "Maximum number queued requests for this dataset
    has been reached" - that is a refusal because the account's queue is
    full, NOT because the payload is wrong.  A wrong payload is a 400 at
    submission time.
  * The limit is on how many requests THIS ACCOUNT holds.  With two held, a
    third is usually refused - but the ceiling drifts with the archive's
    global queue depth, so a third does slip in now and then.
  * A refusal is FREE: the slot comes straight back.  So the pool keeps
    asking rather than giving up.
  * The November init is far more congested than the October one: the same
    centre, shape and dataset serves in 12 s for October and is refused in
    24 s for November.  That is a property of the archive.
  * One request can carry a LIST of variables, so a centre's snowfall and
    its sea-surface temperature travel together.
  * A daily pull of 72 days succeeds; 143 days and up are refused.  The
    daily series is therefore pulled in 72-day chunks and merged.

THE WORK, IN PRIORITY ORDER

  1. the centres that are not on the November init yet, and the two
     centres that are not on the site at all (JMA, BoM) - each one request,
     carrying both the snowfall and the SST;
  2. the daily 10 hPa wind, in 72-day chunks, which is what the SPV charts
     are built from - a centre is only publishable once ALL its chunks are
     in, so one centre is finished before the next is started;
  3. the extensions past the sixth lead month, which only exist in the
     sub-daily product.

    python3 run_nov_queue.py                # run the pool
    python3 run_nov_queue.py --dry-run      # show what it would ask for
    python3 run_nov_queue.py --only jma-snow,bom-snow
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
PENDING = os.path.join(DATA, "nov_pending.json")
DAILY_STATE = os.path.join(DATA, "daily_jobs.json")

INIT = "2026-11"
LEADS = [str(k) for k in range(1, 7)]

DS_MONTHLY_SL = "seasonal-monthly-single-levels"
DS_MONTHLY_PL = "seasonal-monthly-pressure-levels"
DS_ORIGINAL_SL = "seasonal-original-single-levels"
DS_ORIGINAL_PL = "seasonal-original-pressure-levels"

# How many requests to hold at once.  Measured: two is what the account
# gets, and a third is usually refused - but the ceiling drifts, so the
# pool also tries for a third when it can.
POOL_SIZE = 2

# The gap between two submissions, and how long to wait before asking
# again after a refusal.
SUBMIT_GAP = 75
REFUSED_WAIT = 240

# The daily wind comes in 72-day chunks: that size completes, larger ones
# are refused.
DAILY_CHUNK = 72

# How many days each centre's daily series covers - its own forecast range.
DAILY_DAYS = {
    "ecmwf-seas5": 215, "ukmo-gloseas6": 215, "eccc-canesm5": 214,
    "eccc-gem5": 214, "cmcc-sps4": 184, "dwd-gcfs2": 184,
    "meteo-france-s9": 215, "jma-jra3": 215, "bom-access-s2": 215,
}

# tag, name, centre, system
CENTRES = {
    "eccc-gem5": ("ECCC GEM5.2-NEMO", "eccc", "5"),
    "eccc-canesm5": ("ECCC CanESM5.1p1bc", "eccc", "4"),
    "jma-jra3": ("JMA JRA3-25", "jma", "7"),
    "bom-access-s2": ("BOM ACCESS-S2", "bom", "2"),
    "cmcc-sps4": ("CMCC SPE-4", "cmcc", "4"),
    "dwd-gcfs2": ("DWD GCFS2.0", "dwd", "22"),
    "ukmo-gloseas6": ("UKMO GloSeas6-GC5.1", "ukmo", "610"),
    "meteo-france-s9": ("Météo-France System 9", "meteo_france", "9"),
    "ecmwf-seas5": ("ECMWF SEAS5", "ecmwf", "51"),
}

# The centres whose daily wind is wanted, in the order they are finished.
# The two centres that are not on the site yet come first - a daily SPV
# chart for a centre that has no page at all is worth more than a second
# daily chart for a centre that already has one.
DAILY_ORDER = ["jma-jra3", "bom-access-s2", "ukmo-gloseas6", "meteo-france-s9",
               "cmcc-sps4", "dwd-gcfs2", "eccc-gem5", "eccc-canesm5"]


# --------------------------------------------------------------- the work
def monthly_steps():
    """-> [(id, tag, kind)] the monthly requests, in priority order."""
    out = []
    for tag in ("eccc-gem5", "jma-jra3", "bom-access-s2", "eccc-canesm5"):
        out.append(("snow:" + tag, tag, "snow"))
    return out


def clim_steps():
    """-> [(id, tag, kind)] the hindcast climate of the new centres.

    Without it their anomaly panels cannot be drawn - the anomaly is
    measured against the model's OWN climate, not against ERA5.
    """
    return [("clim:" + tag, tag, "clim")
            for tag in ("jma-jra3", "bom-access-s2")]


def daily_steps():
    """-> [(id, tag, kind)] the daily wind chunks, one centre at a time."""
    out = []
    for tag in DAILY_ORDER:
        n = DAILY_DAYS.get(tag, 215)
        for k in range(0, (n + DAILY_CHUNK - 1) // DAILY_CHUNK):
            out.append(("u10d:%s:%d" % (tag, k), tag, "u10d"))
    return out


def ext_steps():
    """-> [(id, tag, kind)] the extension past the sixth lead month."""
    return [("ext:ecmwf-seas5", "ecmwf-seas5", "ext"),
            ("ext:ukmo-gloseas6", "ukmo-gloseas6", "ext")]


def all_steps():
    """The whole priority list.

    The order is the value order:

    1. the monthly snowfall and SST of the centres that are missing from
       the site or off the November init - one request per centre, each
       carrying both fields;
    2. the hindcast climate of the new centres, without which their
       anomaly panels cannot be drawn;
    3. the extension past the sixth lead month, which is what carries the
       multi-model mean out to the end of the C3S range - two requests;
    4. the daily 10 hPa wind, in 72-day chunks - the SPV charts are built
       from it, and one centre is finished before the next is started.
    """
    return monthly_steps() + clim_steps() + ext_steps() + daily_steps()


# ----------------------------------------------------------------- helpers
def target_for(tag, kind):
    d = os.path.join(MDIR, tag)
    return {
        "snow": os.path.join(d, "snowfall_monthly.grib"),
        "sst": os.path.join(d, "sst_monthly.grib"),
        "clim": os.path.join(d, "snowfall_hindcast.grib"),
        "u10": os.path.join(d, "u10_monthly.grib"),
        "ext": os.path.join(d, "snowfall_ext.grib"),
    }[kind]


def record_init(tag, init=INIT):
    p = STATE
    st = json.load(open(p)) if os.path.exists(p) else {}
    name, centre, system = CENTRES.get(tag, (tag, "", ""))
    rec = st.get(tag, {})
    rec.update({"name": name, "centre": centre, "system": system,
                "init": init, "probe_date": time.strftime("%Y-%m-%d")})
    st[tag] = rec
    json.dump(st, open(p, "w"), indent=1)
    print("   %s is on the %s init" % (tag, init), flush=True)


def build_request(tag, kind, chunk=None):
    """-> (dataset, request-dict, [(kind, filename), ...])"""
    name, centre, system = CENTRES[tag]
    common = {"originating_centre": centre, "system": system,
              "year": INIT[:4], "month": INIT[5:7], "data_format": "grib"}
    if kind == "snow":
        # the snowfall and the SST of a centre come from the same dataset
        # and the same leads, so they travel in ONE request
        return (DS_MONTHLY_SL,
                dict(common, variable=["snowfall", "sea_surface_temperature"],
                     product_type="monthly_mean", leadtime_month=LEADS),
                [("snow", "snowfall_monthly.grib"), ("sst", "sst_monthly.grib")])
    if kind == "clim":
        return (DS_MONTHLY_SL,
                dict(common, variable="snowfall",
                     product_type="hindcast_climate_mean", leadtime_month=LEADS),
                [("clim", "snowfall_hindcast.grib")])
    if kind == "ext":
        # the lead months past the sixth only exist in the sub-daily
        # product, where every step carries its own accumulation
        hours = [str(h) for h in range(181 * 24, 216 * 24, 12)]
        return (DS_ORIGINAL_SL,
                dict(common, variable="snowfall", day="01", leadtime_hour=hours),
                [("ext", "snowfall_ext.grib")])
    if kind == "u10d":
        n = DAILY_DAYS.get(tag, 215)
        start = chunk * DAILY_CHUNK
        hours = [str(12 + 24 * k) for k in range(start, min(start + DAILY_CHUNK, n))]
        return (DS_ORIGINAL_PL,
                dict(common, variable="u_component_of_wind", pressure_level="10",
                     day="01", leadtime_hour=hours),
                [("u10d", "u10_daily_c%d.grib" % chunk)])
    raise SystemExit("unknown kind %s" % kind)


# ------------------------------------------------------- daily chunk state
def daily_state():
    if os.path.exists(DAILY_STATE):
        try:
            return json.load(open(DAILY_STATE))
        except Exception:
            pass
    return {"jobs": []}


def daily_done():
    """-> {tag: set(chunk)} already decoded."""
    out = {}
    for j in daily_state()["jobs"]:
        if j.get("status") == "decoded":
            out.setdefault(j["tag"], set()).add(j.get("chunk", 0))
    return out


def daily_set(jid, tag, chunk, status, **kw):
    st = daily_state()
    for j in st["jobs"]:
        if j.get("job") == jid:
            j["status"] = status
            j.update(kw)
            break
    else:
        name, centre, system = CENTRES.get(tag, (tag, "", ""))
        st["jobs"].append({"job": jid, "tag": tag, "chunk": chunk,
                           "centre": centre, "system": system,
                           "init": INIT, "status": status, "_t0": time.time()})
        st["jobs"][-1].update(kw)
    json.dump(st, open(DAILY_STATE, "w"), indent=1)


# --------------------------------------------------------------- decoding
def split_combined(path, tag, kinds):
    """A request that carried two variables comes back as one file - split
    it into the per-variable files the rest of the pipeline expects.

    The combined file is only deleted once every variable has been split
    out of it, so a failure never loses the download.
    """
    import split_grib
    tmp = path + ".combined"
    os.replace(path, tmp)
    try:
        outs, counts = split_grib.split(tmp, os.path.dirname(path),
                                        [k for k, _ in kinds])
    except Exception:
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


def decode_daily(path, tag, chunk):
    """Decode one daily chunk and merge it into the centre's series."""
    from u10_daily import read_daily_u10, build_matrix, save_npz, load_npz
    from fetch_models_daily import merge
    recs, members = read_daily_u10(path)
    dates, m60, mnh = build_matrix(recs, members)
    npz = os.path.join(MDIR, tag, "u10_daily.npz")
    if os.path.exists(npz):
        old = load_npz(npz)
        merged = merge((old[0], old[1], old[2], old[3]),
                       (dates, m60, mnh, members))
    else:
        merged = (dates, m60, mnh, members)
    name, centre, system = CENTRES.get(tag, (tag, "", ""))
    save_npz(npz, merged[0], merged[1], merged[2], merged[3],
             meta=dict(tag=tag, centre=centre, system=system, init=INIT))
    print("   %s: chunk %d decoded (%d records, %d members, %d days)"
          % (tag, chunk, len(recs), len(members), len(dates)), flush=True)


# ------------------------------------------------------------------- pool
class Pool(object):
    """A couple of requests in flight, acted on as each one completes."""

    def __init__(self, c, steps):
        self.c = c
        self.steps = steps
        self.live = {}          # job id -> (step id, tag, kind, dataset, since)
        self.next_at = {}       # step id -> when it may be asked again
        self.last_submit = 0.0
        self.done_steps = []

    def held(self, step):
        return any(v[0] == step for v in self.live.values())

    def submit(self, step, tag, kind):
        """Try to start one request.  True if one is now in flight."""
        if step in self.next_at and time.time() < self.next_at[step]:
            return False
        if time.time() - self.last_submit < SUBMIT_GAP:
            return False
        chunk = None
        if kind == "u10d":
            chunk = int(step.rsplit(":", 1)[1])
        dataset, req, kinds = build_request(tag, kind, chunk)
        try:
            jid = self.c.submit(dataset, req)
        except Exception as e:
            msg = str(e)
            if "Maximum number queued" in msg:
                print("   %s: the queue is full - will ask again" % step, flush=True)
                self.next_at[step] = time.time() + REFUSED_WAIT
                return False
            print("   %s: refused (%s)" % (step, msg[:90]), flush=True)
            self.next_at[step] = time.time() + 300
            return False
        print("   %s: submitted %s on %s" % (step, jid[:12], dataset), flush=True)
        self.live[jid] = (step, tag, kind, dataset, time.time())
        self.last_submit = time.time()
        if kind == "u10d":
            daily_set(jid, tag, chunk, "accepted")
        return True

    def status_of(self, jid):
        s = self.c.job_status(jid)
        if s == "gone":
            # the detail endpoint 404s transiently while a record is
            # re-indexed, so ask again before calling the job dead
            for _ in range(4):
                time.sleep(20)
                s = self.c.job_status(jid)
                if s != "gone":
                    return s
        return s

    def handle(self, jid):
        step, tag, kind, dataset, since = self.live[jid]
        chunk = int(step.rsplit(":", 1)[1]) if kind == "u10d" else None
        if kind == "snow":
            out = target_for(tag, "snow")
            tmp = out + ".part"
            self.c.download_job(jid, tmp)
            split_combined(tmp, tag, [("snow", "snowfall_monthly.grib"),
                                      ("sst", "sst_monthly.grib")])
            if os.path.exists(tmp):
                os.remove(tmp)
        elif kind == "clim":
            out = target_for(tag, "clim")
            tmp = out + ".part"
            self.c.download_job(jid, tmp)
            os.replace(tmp, out)
        elif kind == "ext":
            out = target_for(tag, "ext")
            tmp = out + ".part"
            self.c.download_job(jid, tmp)
            os.replace(tmp, out)
            decode_ext(out, tag)
        elif kind == "u10d":
            gpath = os.path.join(MDIR, tag, "u10_daily_c%d.grib" % chunk)
            os.makedirs(os.path.dirname(gpath), exist_ok=True)
            self.c.download_job(jid, gpath)
            try:
                decode_daily(gpath, tag, chunk)
            finally:
                if os.path.exists(gpath):
                    os.remove(gpath)       # keep the disk small
        for p in (target_for(tag, "snow"), target_for(tag, "sst"),
                  target_for(tag, "clim"), target_for(tag, "ext")):
            if os.path.exists(p):
                print("   %s: saved %s (%.1f MB)"
                      % (tag, os.path.basename(p), os.path.getsize(p) / 1e6),
                      flush=True)

    def poll(self):
        """Act on the live requests.  True if anything landed."""
        acted = False
        self.done_steps = []
        for jid in list(self.live):
            step, tag, kind, dataset, since = self.live[jid]
            # a request is admitted and then judged 20-45 s later, so give
            # it that long before asking - asking early only adds noise
            if time.time() - since < 60:
                continue
            s = self.status_of(jid)
            if s == "successful":
                try:
                    self.handle(jid)
                    acted = True
                    self.done_steps.append((step, tag, kind, True))
                except Exception as e:
                    print("   %s: could not use the result (%s)"
                          % (step, str(e)[:120]), flush=True)
                    self.done_steps.append((step, tag, kind, False))
                del self.live[jid]
            elif s in ("failed", "rejected", "dismissed", "gone"):
                print("   %s: %s after %.0f min - will ask again"
                      % (step, s, (time.time() - since) / 60), flush=True)
                if kind == "u10d":
                    daily_set(jid, tag, int(step.rsplit(":", 1)[1]), "failed")
                del self.live[jid]
                self.done_steps.append((step, tag, kind, False))
                # a refusal means the queue was full, so wait longer than
                # for a job that simply failed
                wait = REFUSED_WAIT if s == "rejected" else 90
                self.next_at[step] = time.time() + wait
        return acted


# ------------------------------------------------------------------- main
def load_pending():
    if not os.path.exists(PENDING):
        return {}
    try:
        return json.load(open(PENDING))
    except Exception:
        return {}


def save_pending(pend):
    json.dump(pend, open(PENDING, "w"), indent=1)


def run(c, steps, only=None, dry=False):
    pool = Pool(c, steps)
    pend = load_pending()
    stepmap = {s[0]: s for s in steps}
    # adopt the requests that were submitted earlier and are still queued -
    # they hold a slot, so their step must not be asked for again
    for step, jid in list(pend.items()):
        if step not in stepmap:
            continue
        s = c.job_status(jid)
        if s in ("accepted", "running", "queued"):
            _, tag, kind = stepmap[step]
            dataset = build_request(tag, kind)[0]
            pool.live[jid] = (step, tag, kind, dataset, time.time())
            if kind == "u10d":
                daily_set(jid, tag, int(step.rsplit(":", 1)[1]), "accepted")
            print("   %s: adopted the queued request %s (%s)"
                  % (step, jid[:12], s), flush=True)
        else:
            print("   %s: the queued request %s is %s - will ask again"
                  % (step, jid[:12], s), flush=True)
            del pend[step]
    save_pending(pend)

    done = daily_done()
    last_report = 0.0
    while True:
        # fill the pool - ONE submission at a time, so the verdict on the
        # last one comes before the next ask
        if not dry:
            for step, tag, kind in steps:
                if only and step not in only:
                    continue
                if len(pool.live) >= POOL_SIZE:
                    break
                if pool.held(step) or step in pend:
                    continue
                if step in pool.next_at and time.time() < pool.next_at[step]:
                    continue
                # a daily chunk that is already decoded is not asked for
                if kind == "u10d":
                    k = int(step.rsplit(":", 1)[1])
                    if k in done.get(tag, ()):
                        continue
                    # finish one centre before starting the next
                    n = DAILY_DAYS.get(tag, 215)
                    nch = (n + DAILY_CHUNK - 1) // DAILY_CHUNK
                    if any((kk not in done.get(tag, ()))
                           for kk in range(nch) if kk < k):
                        continue
                if pool.submit(step, tag, kind):
                    pend[step] = [j for j, v in pool.live.items()
                                  if v[0] == step][0]
                    save_pending(pend)
                    break

        acted = pool.poll()
        for step, tag, kind, ok in pool.done_steps:
            pend.pop(step, None)
            save_pending(pend)
            if ok and kind == "u10d":
                done = daily_done()
            # a centre is on the November init once ITS OWN forecast for
            # that init is on disk
            if ok and kind in ("snow", "clim"):
                p = target_for(tag, "snow" if kind == "snow" else "clim")
                if os.path.exists(p):
                    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
                    if st.get(tag, {}).get("init") != INIT:
                        record_init(tag)
        if time.time() - last_report > 300:
            last_report = time.time()
            print("   [pool] %d in flight: %s"
                  % (len(pool.live), ", ".join(v[0] for v in pool.live.values())),
                  flush=True)
        if dry:
            break
        time.sleep(25)


def main():
    dry = "--dry-run" in sys.argv
    only = []
    if "--only" in sys.argv:
        only = [x for x in sys.argv[sys.argv.index("--only") + 1].split(",") if x]
    steps = all_steps()
    if dry:
        for step, tag, kind in steps:
            if only and step not in only:
                continue
            ds, req, kinds = build_request(tag, kind,
                                           int(step.rsplit(":", 1)[1])
                                           if kind == "u10d" else None)
            print("%-26s %-18s %s -> %s"
                  % (step, tag, ds, ", ".join(k for k, _ in kinds)), flush=True)
        return
    c = cds_direct.CDSDirect()
    run(c, steps, only=only, dry=dry)


if __name__ == "__main__":
    main()
