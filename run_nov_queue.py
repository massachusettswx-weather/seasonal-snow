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
from datetime import datetime

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
#
# ECMWF's "Data Stores Service protection measures" (22 Oct 2026) ask users
# to "submit requests sequentially, rather than in parallel or in large
# batches", and warn that accounts may be suspended for repeated
# submission of invalid requests.  So: one submission at a time, a real gap
# between them, and a long pause after a refusal rather than a quick retry.
#
# The pause is long because the seasonal datasets are genuinely flooded -
# measured on 11 Nov 2026, with the account holding NOTHING, all three of
# the seasonal datasets (monthly single levels, original single levels,
# original pressure levels) refused a fresh request.  The November release
# has saturated the archive for everyone.  Asking again every two minutes
# would be a large batch of requests against an account under scrutiny and
# would not get the data any sooner.
SUBMIT_GAP = 120
REFUSED_WAIT = 900
# When the archive says it has no data for the selection, asking again in
# a minute cannot help.  The centre has not staged that field for that
# init yet, and hammering it is the "repeated submission of invalid
# requests" pattern ECMWF's protection measures warn about.  Two hours.
NO_DATA_WAIT = 2 * 3600

# How long a request may sit with nothing coming back before the pool
# SAYS SO.  It does not release it: the limit on this archive is the depth
# of the archive's own queue for the dataset, so an admitted request is
# standing in a line that is served in order, and it must be left alone.
#
# The one thing that makes a request never be served is a wrong system
# number - and that is checked in CENTRES before the request is made.
STUCK_S = 60 * 60

# The daily wind comes in 72-day chunks: that size completes, larger ones
# are refused.
DAILY_CHUNK = 72

# How many days each centre's daily series covers - its own forecast range.
DAILY_DAYS = {
    "ecmwf-seas5": 215, "ukmo-gloseas6": 215, "eccc-canesm5": 214,
    "eccc-gem5": 214, "cmcc-sps4": 184, "dwd-gcfs2": 184,
    "meteo-france-s9": 215, "jma-jra3": 215, "bom-access-s2": 215,
}

# How far past the sixth lead month each centre actually runs.  These are
# the systems' own published ranges: the ECMWF and the UKMO to 215 days,
# the ECCC to 214, Meteo-France to 215, the CMCC to 184, the DWD to six
# calendar months.  A centre that does not reach past the sixth month gets
# no extension request at all.
EXT_DAYS = {
    "ecmwf-seas5": 215, "ukmo-gloseas6": 215, "eccc-canesm5": 214,
    "eccc-gem5": 214, "meteo-france-s9": 215, "cmcc-sps4": 184,
    "jma-jra3": 215, "bom-access-s2": 215, "dwd-gcfs2": 180,
}

# tag, name, centre, system
CENTRES = {
    "eccc-gem5": ("ECCC GEM5.2-NEMO", "eccc", "5"),
    "eccc-canesm5": ("ECCC CanESM5.1p1bc", "eccc", "4"),
    "jma-jra3": ("JMA CPS4", "jma", "4"),
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
# CMCC and DWD come first: their wind files were removed in the disk
# clean-up, so their 10 hPa panels were pruned and they have no chart at
# all until the wind comes back.  The rest follow.
DAILY_ORDER = ["cmcc-sps4", "dwd-gcfs2", "ukmo-gloseas6", "meteo-france-s9",
               "eccc-gem5", "eccc-canesm5", "jma-jra3", "bom-access-s2"]


# --------------------------------------------------------------- the work
def monthly_steps():
    """-> [(id, tag, kind)] the monthly requests, in priority order."""
    out = []
    # JMA and BoM are NOT asked for the snowfall: they do not publish that
    # field at all - MARS answers "MarsNoDataError" for it - and asking
    # again and again for a request that can never succeed is exactly the
    # repeated submission of invalid requests that ECMWF's protection
    # measures warn about.  The site says so instead.
    for tag in ("eccc-gem5", "eccc-canesm5"):
        out.append(("snow:" + tag, tag, "snow"))
    # the SST of the centres that are not on the site yet, and of the ECCC
    # centres whose plume still points at the October init - it is what the
    # ENSO plumes are built from
    for tag in ("jma-jra3", "bom-access-s2", "eccc-gem5", "eccc-canesm5"):
        out.append(("sst:" + tag, tag, "sst"))
    return out


def clim_steps():
    """-> [(id, tag, kind)] the hindcast climate of the new centres.

    Without it their anomaly panels cannot be drawn - the anomaly is
    measured against the model's OWN climate, not against ERA5.
    """
    # JMA and BoM are not in this list: they publish no snowfall field at
    # all, so there is no hindcast of it to fetch either.
    return []


def daily_steps():
    """-> [(id, tag, kind)] the daily wind chunks, one centre at a time."""
    out = []
    for tag in DAILY_ORDER:
        n = DAILY_DAYS.get(tag, 215)
        for k in range(0, (n + DAILY_CHUNK - 1) // DAILY_CHUNK):
            out.append(("u10d:%s:%d" % (tag, k), tag, "u10d"))
    return out


def u10m_steps():
    """-> [(id, tag, kind)] the monthly 10 hPa wind, where it is missing or
    on an older init.

    The SPV chart is built from the DAILY wind, and that is what the pool
    fetches in 72-day chunks.  This is the cheap stopgap: one request for
    all six lead months, for a centre whose monthly wind is on an older
    init - the ECCC centres were plotting October wind - or that has no
    wind at all.
    """
    out = []
    for tag in ("eccc-gem5", "eccc-canesm5", "cmcc-sps4", "dwd-gcfs2",
                "jma-jra3", "bom-access-s2"):
        p = os.path.join(MDIR, tag, "u10_monthly.grib")
        if os.path.exists(p) and os.path.getsize(p) > 10000:
            if u10_init_on_disk(p) == INIT:
                continue           # already the newest init
        out.append(("u10m:" + tag, tag, "u10m"))
    return out


def ext_steps():
    """-> [(id, tag, kind)] the extension past the sixth lead month.

    The monthly dataset stops at lead month 6, but the systems run further:
    the ECMWF and the UKMO to 215 days, the ECCC to 214, Meteo-France and
    CMCC to 184, the DWD to six calendar months.  The extra months only
    exist in the sub-daily product, where every step carries its own
    accumulation.

    The ECMWF and the UKMO come first because they are the two systems
    whose extension is what carries the multi-model mean out to the end of
    the C3S range - the mean is over the union of what the centres cover,
    so one centre reaching month 7 extends the whole product.
    """
    out = []
    for tag in ("ecmwf-seas5", "ukmo-gloseas6", "eccc-gem5", "eccc-canesm5",
                "meteo-france-s9", "cmcc-sps4", "jma-jra3", "bom-access-s2"):
        if EXT_DAYS.get(tag, 0) > 180:
            out.append(("ext:" + tag, tag, "ext"))
    return out


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
    # The daily wind and the monthly wind come before the extension.
    # The extension only carries the multi-model mean one month further,
    # while the wind is what a centre's 10 hPa chart is made of, and CMCC
    # and DWD have no chart at all until their wind arrives.  The
    # extension also sits in the archive's queue for the sub-daily
    # product, which is the deepest of the three.
    return (monthly_steps() + clim_steps() + daily_steps() + u10m_steps() +
            ext_steps())


# ----------------------------------------------------------------- helpers
def target_for(tag, kind):
    d = os.path.join(MDIR, tag)
    return {
        "snow": os.path.join(d, "snowfall_monthly.grib"),
        "sst": os.path.join(d, "sst_monthly.grib"),
        "clim": os.path.join(d, "snowfall_hindcast.grib"),
        "u10": os.path.join(d, "u10_monthly.grib"),
        "u10m": os.path.join(d, "u10_monthly.grib"),
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


def centre_init(tag):
    """The init a centre is actually on.

    Every centre is being moved onto the November init, but until its
    November forecast is actually on disk it is still on whatever it was
    serving - and the request has to ask for THAT init, or the archive
    answers with nothing.  The monthly request always asks for the
    November init; the extension and the daily wind follow the init that
    the monthly request established.

    The sea surface temperature is the exception: it is asked for by the
    newest init whatever the centre is on, because a newer init's SST is
    simply better and the plume should use it.  Asking for the state's
    init here is how the ECCC centres kept being given a fresh copy of
    their October SST.
    """
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    return st.get(tag, {}).get("init", INIT)


def u10_init_on_disk(path):
    """The init a monthly 10 hPa wind file belongs to.

    A monthly_mean field is valid at the END of the averaging period, so
    the first lead month is the month before the first valid date - and
    that is the init month.
    """
    try:
        from datetime import datetime as _dt, timedelta as _td
        import eccodes
        with open(path, "rb") as f:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                return None
            step = int(eccodes.codes_get(gid, "step"))
            dd = int(eccodes.codes_get(gid, "dataDate"))
            d0 = _dt(dd // 10000, (dd // 100) % 100, dd % 100)
            m = (d0 + _td(hours=step)) - _td(days=1)
            return "%04d-%02d" % (m.year, m.month)
    except Exception:
        return None


def sst_init_on_disk(path):
    """The init an SST file belongs to, from its first lead month.

    The lead month 1 of a seasonal run is the init month itself, so the
    first lead month says which init the file is.  This is what tells the
    November file apart from the October one - they have the same name
    and the same shape.
    """
    try:
        import eccodes
        from datetime import datetime as _dt, timedelta as _td
        with open(path, "rb") as f:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                return None
            step = int(eccodes.codes_get(gid, "step"))
            dd = int(eccodes.codes_get(gid, "dataDate"))
            d0 = _dt(dd // 10000, (dd // 100) % 100, dd % 100)
            valid = d0 + _td(hours=step)
            month = valid - _td(days=1)
            return "%04d-%02d" % (month.year, month.month)
    except Exception:
        return None


def build_request(tag, kind, chunk=None):
    """-> (dataset, request-dict, [(kind, filename), ...])"""
    name, centre, system = CENTRES[tag]
    init = INIT if kind in ("snow", "clim", "sst", "u10m") else centre_init(tag)
    common = {"originating_centre": centre, "system": system,
              "year": init[:4], "month": init[5:7], "data_format": "grib"}
    if kind == "snow":
        # ONE variable per request.
        #
        # A request that carries a LIST of variables is accepted, but it
        # waits: two such requests sat for 12 hours and 2.5 hours with
        # their `updated` timestamp never moving - no worker ever picked
        # them up - while the single-variable requests for the same
        # centres completed.  The list form appears to wait for every
        # field to be staged before it is worked on, and one field that
        # is not ready holds the whole thing up.
        #
        # So the snowfall and the SST are asked for separately.  It costs
        # an extra request, but a request that is actually served beats a
        # request that is admitted and never touched.
        return (DS_MONTHLY_SL,
                dict(common, variable="snowfall",
                     product_type="monthly_mean", leadtime_month=LEADS),
                [("snow", "snowfall_monthly.grib")])
    if kind == "sst":
        return (DS_MONTHLY_SL,
                dict(common, variable="sea_surface_temperature",
                     product_type="monthly_mean", leadtime_month=LEADS),
                [("sst", "sst_monthly.grib")])
    if kind == "u10m":
        # The monthly 10 hPa wind, one request for all six lead months.
        #
        # The daily wind is what the SPV chart is really built from, but it
        # takes three 72-day chunks per centre.  This is the cheap stopgap
        # for a centre whose monthly wind is on an older init - the ECCC
        # centres were still plotting October wind under a November label
        # - and for a centre with no wind at all.
        return (DS_MONTHLY_PL,
                dict(common, variable="u_component_of_wind",
                     pressure_level="10", product_type="monthly_mean",
                     leadtime_month=LEADS),
                [("u10m", "u10_monthly.grib")])
    if kind == "clim":
        return (DS_MONTHLY_SL,
                dict(common, variable="snowfall",
                     product_type="hindcast_climate_mean", leadtime_month=LEADS),
                [("clim", "snowfall_hindcast.grib")])
    if kind == "ext":
        # The lead months past the sixth only exist in the sub-daily
        # product, where every step carries its own accumulation.  The
        # window is trimmed to the centre's own reach - asking for days a
        # system does not run to is what produces an empty file.
        reach = EXT_DAYS.get(tag, 0)
        if reach <= 180:
            raise SystemExit("%s does not run past the sixth lead month" % tag)
        hours = [str(h) for h in range(181 * 24, reach * 24 + 1, 12)]
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
            st = json.load(open(DAILY_STATE))
            # the file grows without bound - one entry per submission - and
            # only the recent ones matter
            jobs = st.get("jobs", [])
            if len(jobs) > 60:
                keep = [j for j in jobs if j.get("status") == "decoded"]
                keep += jobs[-20:]
                st["jobs"] = keep[-60:]
            return st
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
    months, members, acc, glat, glon, ndays = read_snow(path)
    if months and acc is not None:
        save_npz(path.replace(".grib", ".npz"), months, members, acc, glat, glon,
                 meta=dict(tag=tag, init=INIT, kind="extended"), ndays=ndays)
        print("   %s/ext: %d extended month(s) %s (%s days each)"
              % (tag, len(months), ["%04d-%02d" % m for m in months], ndays),
              flush=True)
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
        # after a refusal the whole pool waits, not just the step that was
        # refused: asking the next step straight away is the "large batch
        # of requests" that ECMWF's protection measures warn about
        self.cooldown_until = 0.0

    def held(self, step):
        return any(v[0] == step for v in self.live.values())

    def submit(self, step, tag, kind):
        """Try to start one request.  True if one is now in flight."""
        if step in self.next_at and time.time() < self.next_at[step]:
            return False
        if time.time() - self.last_submit < SUBMIT_GAP:
            return False
        if time.time() < self.cooldown_until:
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
                # A refusal is free - the slot comes straight back - so ask
                # again soon rather than waiting the full back-off.  The
                # ceiling drifts, and a slot sometimes opens in between.
                print("   %s: the queue is full - the pool waits %d min"
                      % (step, REFUSED_WAIT // 60), flush=True)
                self.next_at[step] = time.time() + REFUSED_WAIT
                self.cooldown_until = time.time() + REFUSED_WAIT
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

    def worker_touched(self, jid):
        """Has this request been judged by the archive?

        The job's `updated` timestamp moves when the archive reaches a
        verdict - a job that is REFUSED carries the later timestamp.  It
        is NOT a progress signal: a job that completes successfully also
        keeps `updated == created`, so this can only tell "the archive
        has refused it" from "it has not refused it yet".

        Returns True when the job has been refused, False when it has
        not, None when the endpoint does not say.
        """
        try:
            r = self.c._request("GET", "/retrieve/v1/jobs/%s" % jid)
            if r.status_code != 200:
                return None
            d = r.json()
            cr, up = d.get("created", ""), d.get("updated", "")
            if not cr or not up:
                return None
            return up != cr
        except Exception:
            return None

    def handle(self, jid):
        step, tag, kind, dataset, since = self.live[jid]
        chunk = int(step.rsplit(":", 1)[1]) if kind == "u10d" else None
        # what this request actually wrote - not every file the centre
        # happens to have on disk
        wrote = []
        if kind == "snow":
            out = target_for(tag, "snow")
            tmp = out + ".part"
            self.c.download_job(jid, tmp)
            os.replace(tmp, out)
            wrote = [out]
        elif kind == "sst":
            out = target_for(tag, "sst")
            tmp = out + ".part"
            self.c.download_job(jid, tmp)
            os.replace(tmp, out)
            wrote = [out]
        elif kind == "clim":
            out = target_for(tag, "clim")
            tmp = out + ".part"
            self.c.download_job(jid, tmp)
            os.replace(tmp, out)
            wrote = [out]
        elif kind == "u10m":
            out = target_for(tag, "u10m")
            tmp = out + ".part"
            self.c.download_job(jid, tmp)
            os.replace(tmp, out)
            wrote = [out]
        elif kind == "ext":
            out = target_for(tag, "ext")
            tmp = out + ".part"
            self.c.download_job(jid, tmp)
            os.replace(tmp, out)
            wrote = [out]
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
            wrote = [os.path.join(MDIR, tag, "u10_daily.npz")]
            # the chunk is decoded and merged - record it, or the pool asks
            # for it again
            daily_set(jid, tag, chunk, "decoded")
        for p in wrote:
            if os.path.exists(p):
                print("   %s: wrote %s (%.1f MB)"
                      % (tag, os.path.basename(p), os.path.getsize(p) / 1e6),
                      flush=True)

    def is_no_data(self, jid):
        """-> True if the job failed because the archive has no data."""
        try:
            r = self.c._request("GET", "/retrieve/v1/jobs/%s/results" % jid)
            t = r.text or ""
            return "MarsNoDataError" in t or "no data" in t.lower()
        except Exception:
            return False

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
                if kind == "u10d":
                    daily_set(jid, tag, int(step.rsplit(":", 1)[1]), "failed")
                del self.live[jid]
                self.done_steps.append((step, tag, kind, False))
                if s == "failed":
                    # A FAILURE is not a refusal.  The reason matters:
                    #
                    #  * "MarsNoDataError" means the archive has no data
                    #    for that selection - the centre has not staged the
                    #    November init for that field yet.  Asking again in
                    #    a minute cannot help, and asking again and again
                    #    is the "repeated submission of invalid requests"
                    #    that ECMWF's protection measures warn about.  So
                    #    this step waits a long time.
                    #  * anything else is an error worth retrying sooner.
                    nodata = self.is_no_data(jid)
                    if nodata:
                        print("   %s: the archive has no data for this "
                              "selection (MarsNoDataError) - waiting %d min"
                              % (step, NO_DATA_WAIT // 60), flush=True)
                        self.next_at[step] = time.time() + NO_DATA_WAIT
                        continue
                print("   %s: %s after %.0f min - will ask again"
                      % (step, s, (time.time() - since) / 60), flush=True)
                # a refusal means the queue was full, so wait longer than
                # for a job that simply failed
                wait = REFUSED_WAIT if s == "rejected" else 90
                self.next_at[step] = time.time() + wait
                if s == "rejected":
                    # the account is over its allowance - back off for the
                    # whole pool, not just this step
                    self.cooldown_until = time.time() + wait
            elif s == "accepted" and time.time() - since > STUCK_S:
                # STILL WAITING, AND THAT IS CORRECT.
                #
                # Measured on 11 Nov 2026: the account held NO jobs at all
                # and a fresh request was still refused with "Maximum
                # number queued requests for this dataset has been reached".
                # So the limit is the depth of the ARCHIVE'S queue for
                # that dataset, not the number of requests this account
                # holds.
                #
                # A request that was admitted is therefore standing in
                # that queue, and the queue is served in order - so it
                # must be LEFT ALONE.  Dismissing it would throw away our
                # place in the line, and asking for the same thing again
                # would put us at the back of it.  (It is also exactly the
                # "repeated submission" pattern that ECMWF's protection
                # measures warn about.)
                #
                # So the pool just says so, and waits.  The only way to
                # tell a request that will never be served is a wrong
                # system number - and that is checked in CENTRES.
                print("   %s: still queued after %.0f min (the archive's queue "
                      "for this dataset is deep - leaving it in the line)"
                      % (step, (time.time() - since) / 60), flush=True)
        return acted


# ------------------------------------------------------------------- main
def load_pending():
    if not os.path.exists(PENDING):
        return {}
    try:
        return json.load(open(PENDING))
    except Exception:
        return {}


def job_age(jid, c):
    """When the job was created, as a timestamp - the age of the REQUEST.

    The job's own `updated` field says whether a worker has touched it:
    if `updated` never moves away from `created`, no worker has picked the
    request up and it is not going anywhere.
    """
    try:
        r = c._request("GET", "/retrieve/v1/jobs/%s" % jid)
        d = r.json() if r.status_code == 200 else {}
        cr = d.get("created", "")
        if cr:
            t = datetime.fromisoformat(cr.replace("Z", "").split(".")[0])
            return t.timestamp()
    except Exception:
        pass
    return time.time()


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
            ch = int(step.rsplit(":", 1)[1]) if kind == "u10d" else None
            dataset = build_request(tag, kind, ch)[0]
            # the age of the request is the age of the JOB, not the age of
            # this process - a request that was submitted hours ago and has
            # not been touched since is already stuck and must be released
            # now, not after another 25 minutes
            since = job_age(jid, c)
            pool.live[jid] = (step, tag, kind, dataset, since)
            if kind == "u10d":
                daily_set(jid, tag, int(step.rsplit(":", 1)[1]), "accepted")
            print("   %s: adopted the queued request %s (%s, %.0f min old)"
                  % (step, jid[:12], s, (time.time() - since) / 60), flush=True)
        elif s == "successful":
            # the request finished while this process was not running -
            # take the result rather than asking for it all over again
            _, tag, kind = stepmap[step]
            ch = int(step.rsplit(":", 1)[1]) if kind == "u10d" else None
            dataset = build_request(tag, kind, ch)[0]
            print("   %s: the queued request %s finished while we were down - "
                  "taking the result" % (step, jid[:12]), flush=True)
            pool.live[jid] = (step, tag, kind, dataset, job_age(jid, c))
            try:
                pool.handle(jid)
            except Exception as e:
                print("   %s: could not use the result (%s)"
                      % (step, str(e)[:120]), flush=True)
            del pend[step]
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
            # Fill the pool.  Two at a time is the measured ceiling, and
            # ECMWF's protection measures ask for sequential submission, so
            # the pool does not chase a third slot - a refusal costs
            # nothing but it does count as another request against an
            # account that is already under scrutiny.
            for step, tag, kind in steps:
                if only and step not in only:
                    continue
                if len(pool.live) >= POOL_SIZE:
                    break
                if pool.held(step) or step in pend:
                    continue
                if step in pool.next_at and time.time() < pool.next_at[step]:
                    continue
                # A file that is already on disk for this init is not asked
                # for again - otherwise the pool keeps re-asking for a field
                # it already has, and the request it makes instead is a
                # duplicate the archive has to serve.
                if kind == "snow":
                    # the forecast belongs to one init only, so it counts
                    # only once the centre is recorded on that init
                    p = target_for(tag, "snow")
                    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
                    if (os.path.exists(p) and os.path.getsize(p) > 10000
                            and st.get(tag, {}).get("init") == INIT):
                        continue
                elif kind == "sst":
                    # the SST has to be the NEWEST init's, not merely a
                    # fresh file - the ECCC centres had a fresh copy of
                    # their October SST on disk, and "fresh" would have
                    # skipped the request for the November one
                    p = target_for(tag, "sst")
                    if (os.path.exists(p) and os.path.getsize(p) > 10000
                            and sst_init_on_disk(p) == INIT):
                        continue
                elif kind == "u10m":
                    # skipped only when the monthly wind on disk is already
                    # the newest init
                    p = target_for(tag, "u10m")
                    if (os.path.exists(p) and os.path.getsize(p) > 10000
                            and u10_init_on_disk(p) == INIT):
                        continue
                elif kind == "clim":
                    # the hindcast climate does not change between inits, so
                    # once it is on disk it never needs fetching again
                    p = target_for(tag, "clim")
                    if os.path.exists(p) and os.path.getsize(p) > 10000:
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
            # A centre is on the November init once ITS OWN forecast for
            # that init is on disk.  The snowfall is what counts - the SST
            # and the hindcast climate are not what the centre's panels
            # are built from, and the climate does not change between
            # inits anyway.
            if ok and kind == "snow":
                p = target_for(tag, "snow")
                # the file must be the one that was just downloaded, not the
                # one the previous init left behind
                if os.path.exists(p) and os.path.getmtime(p) > time.time() - 3600:
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
