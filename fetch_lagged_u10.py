"""Fetch the DAILY 10 hPa zonal-mean zonal wind for the LAGGED seasonal
ensembles (UKMO GloSeas6, JMA JRA3, BoM ACCESS-S2).

Why this script exists
----------------------
The C3S sub-daily product `seasonal-original-pressure-levels` stores a
*lagged* ensemble for these three centres.  Their members are NOT all
started on the same day: the UKMO's 62 members are started two per day on
31 consecutive days (2026-10-02 .. 2026-11-01), the JMA's 155 five per day
on the same 31 days, and the BoM's 99 eleven per day on nine days
(2026-10-24 .. 2026-11-01).

The request's `day` input becomes MARS' `date` (with `number: all`), so it
selects the members **started on that day**.  The pipeline's `day=["01"]`
request therefore comes back with 2 members for the UKMO and 5 for the JMA -
and the site then refuses to draw it ("a chart of two lines would read as
the whole ensemble").  The members are all there; the request was only
asking for one start day.  (A date that is not a start date of the run is
not merely empty: MARS refuses the whole request with "Restricted access to
current C3S seasonal forecast non-ECMWF contribution".)

So this pull asks for every start day of the run, and decodes each member
from each record's OWN validity date (never dataDate, which is the member's
start date and differs from member to member).  The lead time is measured
from each member's own start date, so the members that cover a given day
cover it at DIFFERENT lead times - which is what a lagged ensemble is.

How the start days are found
----------------------------
The monthly pull of the same wind (`data/models/<tag>/u10_monthly.grib`) is
already on disk and holds the whole lagged ensemble, one record per member
per lead month.  Reading the members' `dataDate` off it gives the exact
list of start days and the number of members on each, with no request to
the archive at all - and it gives the member numbering the monthly series
uses, so the daily and the monthly series carry the same member ids.

What comes out
--------------
`data/models/<tag>/u10_daily.npz` in the pipeline's format: `dates`,
`members60` (members x days), `members_nh`, `member_numbers`, `meta`.
`members60` is the zonal mean of the zonal wind at 60 N in m/s - the same
quantity the other centres' daily series carry.

usage:
  python3 fetch_lagged_u10.py --tag ukmo-gloseas6
  python3 fetch_lagged_u10.py --tag ukmo-gloseas6,jma-jra3,bom-access-s2
  python3 fetch_lagged_u10.py --tag ... --dry-run      # the plan only
  python3 fetch_lagged_u10.py --tag ... --leads-per-chunk 40

The CDS account holds two requests across the whole pipeline, so this script
keeps at most ONE of its own requests in flight and waits for the other
processes' jobs to clear before it submits.
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from cds_direct import CDSDirect, QueueFull, NoData          # noqa: E402
from u10_daily import load_npz, save_npz, zonal_mean, point_mean  # noqa: E402

DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
DATASET = "seasonal-original-pressure-levels"

# tag -> (originating_centre, system)
CENTRES = {
    "ukmo-gloseas6": ("ukmo", "610"),
    "jma-jra3": ("jma", "4"),
    "bom-access-s2": ("bom", "2"),
}

# The polar cap is not enough: the 60 N band needs the rows on BOTH sides
# of 60 N (the UKMO and the BoM run a 1 deg grid whose rows sit at 59.5
# and 60.5), and the Northern Hemisphere mean needs every row from 0 N up.
AREA = [90, -180, 0, 180]

# the run's own length in days (the C3S seasonal systems run to 215 days)
RUN_DAYS = {"ukmo-gloseas6": 215, "jma-jra3": 215, "bom-access-s2": 215}

LEAD_MAX = 5160          # the archive's own ceiling for leadtime_hour
LEAD_STEP = 24           # the daily 12Z lead times

# the biggest answer this script asks for.  The archive caps the RESPONSE
# SIZE and silently drops members when the request is too big, so every
# request is sized from the number of trajectories it carries.
MAX_MB = 600
BYTES_PER_POINT = 2.1    # a GRIB1 u field is 16-bit packed


# ----------------------------------------------------------------------
# the lagged ensemble's layout, read off the monthly pull
# ----------------------------------------------------------------------
def ensemble_layout(tag):
    """-> (start_days, members_per_start_day, n_members, numbering)

    start_days: [(date, [member numbers]), ...] - the run's start days and
                the monthly member numbers that belong to each of them.
    """
    import eccodes
    p = os.path.join(MDIR, tag, "u10_monthly.grib")
    if not os.path.exists(p):
        return None
    per = defaultdict(set)
    with open(p, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                num = eccodes.codes_get(gid, "number")
                dd = eccodes.codes_get(gid, "dataDate")
                if num is None or dd is None:
                    continue
                d = date(int(dd) // 10000, (int(dd) // 100) % 100, int(dd) % 100)
                per[d].add(int(num))
            finally:
                eccodes.codes_release(gid)
    if not per:
        return None
    days = sorted(per)
    numbering = {d: sorted(per[d]) for d in days}
    nmem = len({m for s in per.values() for m in s})
    return days, numbering, nmem


def init_of(tag):
    """-> (year, month) of the run this centre is on."""
    p = os.path.join(DATA, "models_fetched.json")
    if os.path.exists(p):
        try:
            d = json.load(open(p))
            for key in (tag, tag.replace("-", "_")):
                v = d.get(key)
                if v and v.get("init"):
                    y, m = v["init"].split("-")
                    return int(y), int(m)
        except Exception:
            pass
    return 2026, 11


def start_groups(numbering):
    """-> [(year, month, [days])] the start days grouped by calendar month.

    The archive takes the start date as (year, month, day), and its `day`
    list is combined with the `month` list as a product, so a request that
    mixed a 31-day month with a 30-day month would ask for a 31 November -
    and a date that is not a start date of the run is refused outright by
    MARS.  One request per calendar month keeps every (year, month, day)
    triple real.
    """
    g = defaultdict(list)
    for d in sorted(numbering):
        g[(d.year, d.month)].append(d)
    return [(y, m, g[(y, m)]) for (y, m) in sorted(g)]


def lead_list(n_days):
    """The daily 12Z lead times of a run: 12, 36, 60, ... hours."""
    out = []
    k = 0
    while 12 + LEAD_STEP * k <= min(LEAD_MAX, 12 + LEAD_STEP * (n_days - 1)):
        out.append(12 + LEAD_STEP * k)
        k += 1
    return out


def build_request(tag, year, month, days, leads):
    centre, system = CENTRES[tag]
    return {"originating_centre": centre, "system": system,
            "variable": ["u_component_of_wind"], "pressure_level": ["10"],
            "year": ["%04d" % year], "month": ["%02d" % month],
            "day": ["%02d" % d.day for d in days],
            "leadtime_hour": [str(h) for h in leads],
            "area": AREA, "data_format": "grib"}


# ----------------------------------------------------------------------
# the reader
# ----------------------------------------------------------------------
def _g(gid, key, default=None):
    import eccodes
    try:
        v = eccodes.codes_get(gid, key)
    except Exception:
        return default
    if isinstance(v, (bytes, bytearray)):
        v = v.decode()
    return v


def read_lagged_u10(path, numbering=None):
    """-> (records, members)

    record: dict(valid=datetime.date, member=int, start=datetime.date,
                 step=int, s60=float, sNH=float)

    The valid time is the record's OWN validityDate/validityTime - never
    dataDate, which is the member's start date and is different for every
    member of a lagged ensemble.  The member's start date is kept as well,
    because it is what makes the ensemble's layout visible.

    `numbering` maps a start date to the member numbers the MONTHLY series
    uses for it; the sub-daily product numbers the members of a start day
    1, 2, 3 ... and the two are paired up in order, so the daily and the
    monthly series of a centre carry the same member ids.
    """
    import eccodes
    recs = []
    members = set()
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
                ni = int(_g(gid, "Ni", 0) or 0)
                nj = int(_g(gid, "Nj", 0) or 0)
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

                vd = _g(gid, "validityDate")
                vt = _g(gid, "validityTime")
                if vd is None:
                    continue
                vd = int(vd)
                valid = date(vd // 10000, (vd // 100) % 100, vd % 100)
                if vt is not None:
                    valid += timedelta(hours=int(vt) // 100)
                dd = _g(gid, "dataDate")
                start = None
                if dd is not None:
                    dd = int(dd)
                    start = date(dd // 10000, (dd // 100) % 100, dd % 100)

                num = _g(gid, "number")
                pn = _g(gid, "perturbationNumber")
                if num is None and pn is None:
                    continue
                mem = int(num if num is not None else pn)

                # the member id of the MONTHLY series, so the two agree
                if numbering and start in numbering:
                    pair = sorted(numbering[start])
                    k = mem - 1
                    if 0 <= k < len(pair):
                        mem = pair[k]

                recs.append(dict(valid=valid, member=mem, start=start,
                                 step=int(_g(gid, "step", 0) or 0),
                                 level=_g(gid, "level"),
                                 s60=point_mean(v, lats, 60.0),
                                 sNH=zonal_mean(v, lats)))
                members.add(mem)
            except Exception:
                pass
            finally:
                eccodes.codes_release(gid)
    return recs, sorted(members)


def build_matrix(recs, members):
    """-> (dates, m60[members, dates], mnh[members, dates], per_day)"""
    by_date = defaultdict(lambda: defaultdict(list))
    for r in recs:
        by_date[r["valid"]][r["member"]].append(r)
    dates = sorted(by_date)
    idx = {m: i for i, m in enumerate(members)}
    m60 = np.full((len(members), len(dates)), np.nan)
    mnh = np.full((len(members), len(dates)), np.nan)
    per_day = {}
    for j, d in enumerate(dates):
        per_day[d] = len(by_date[d])
        for m, rows in by_date[d].items():
            i = idx.get(m)
            if i is None:
                continue
            m60[i, j] = float(np.nanmean([r["s60"] for r in rows]))
            mnh[i, j] = float(np.nanmean([r["sNH"] for r in rows]))
    return dates, m60, mnh, per_day


def merge(dst, new):
    """Merge a decoded chunk into the centre's accumulator."""
    dates, m60, mnh, members = dst
    d2, a2, b2, mem2 = new
    allm = sorted(set(members) | set(mem2))
    alld = sorted(set(dates) | set(d2))
    mi = {m: i for i, m in enumerate(allm)}
    di = {d: i for i, d in enumerate(alld)}
    A = np.full((len(allm), len(alld)), np.nan)
    B = np.full((len(allm), len(alld)), np.nan)
    if dates:
        for i, m in enumerate(members):
            A[mi[m], [di[d] for d in dates]] = m60[i]
            B[mi[m], [di[d] for d in dates]] = mnh[i]
    if d2:
        for i, m in enumerate(mem2):
            A[mi[m], [di[d] for d in d2]] = a2[i]
            B[mi[m], [di[d] for d in d2]] = b2[i]
    return alld, A, B, allm


def trim_to_run(acc, init_date, run_days):
    """Cut the series to the window the site charts.

    A lagged ensemble covers a given day with the members whose own run has
    reached it, so the number of members falls away at the end of the run
    (the members that started last run out of lead time first).  The chart
    is drawn over the window in which the WHOLE ensemble is present, from
    the run's reference date onwards.
    """
    dates, m60, mnh, members = acc
    if not dates:
        return acc, {}
    counts = np.sum(~np.isnan(m60), axis=0)
    full = counts.max()
    keep = [j for j, d in enumerate(dates)
            if d >= init_date and counts[j] == full]
    if not keep:
        keep = [j for j, d in enumerate(dates) if d >= init_date]
    if not keep:
        return acc, {}
    j0, j1 = keep[0], keep[-1]
    new_dates = dates[j0:j1 + 1]
    new_m60 = m60[:, j0:j1 + 1]
    new_mnh = mnh[:, j0:j1 + 1]
    per_day = {d: int(np.sum(~np.isnan(new_m60[:, j])))
               for j, d in enumerate(new_dates)}
    return [new_dates, new_m60, new_mnh, members], per_day


# ----------------------------------------------------------------------
# the CDS side
# ----------------------------------------------------------------------
def account_live(c):
    """How many jobs the ACCOUNT holds right now (the gate is account-wide)."""
    n = 0
    try:
        for j in c.live_jobs(limit=60):
            if j.get("status") in ("accepted", "running", "queued"):
                n += 1
    except Exception:
        return None
    return n


def wait_for_slot(c, verbose=True):
    """Block until the account holds fewer than two live jobs.

    The CDS admission gate is ACCOUNT-WIDE at two: the monthly pool and the
    polar puller share it with this script, and a third request is refused
    outright.  So this script waits its turn and keeps only one of its own
    requests in flight.
    """
    while True:
        n = account_live(c)
        if n is None or n < 2:
            if verbose:
                print("   the account holds %s live job(s) - submitting"
                      % (n if n is not None else "?"), flush=True)
            return
        if verbose:
            print("   the account holds %d live job(s) - waiting" % n, flush=True)
        time.sleep(30)


def fetch_chunk(c, tag, year, month, days, leads, gpath):
    """Submit one request, wait for it, download it.  -> True on success."""
    req = build_request(tag, year, month, days, leads)
    wait_for_slot(c)
    try:
        jid = c.submit(DATASET, req)
    except QueueFull as e:
        print("   the queue refused it: %s" % str(e)[:160], flush=True)
        return False
    except NoData as e:
        print("   NO DATA: %s" % str(e)[:300], flush=True)
        return False
    print("   submitted %04d-%02d days %s..%s, %d leads -> %s"
          % (year, month, days[0].day, days[-1].day, len(leads), jid[:8]),
          flush=True)
    status = None
    for _ in range(600):                     # up to two and a half hours
        time.sleep(10)
        status = c.job_status(jid)
        if status in ("successful", "completed", "failed", "rejected",
                      "dismissed", "gone"):
            break
    if status not in ("successful", "completed"):
        print("   the job ended as %s: %s"
              % (status, c._job_detail(jid)[:400]), flush=True)
        return False
    os.makedirs(os.path.dirname(gpath), exist_ok=True)
    c.download_job(jid, gpath)
    print("   downloaded %.1f MB" % (os.path.getsize(gpath) / 1e6), flush=True)
    return True


def chunk_plan(n_traj, n_leads, points_per_field):
    """-> the list of lead windows for a group of n_traj trajectories."""
    per_field_mb = points_per_field * BYTES_PER_POINT / 1e6
    max_fields = max(1, int(MAX_MB / max(per_field_mb, 1e-6)))
    per_chunk = max(1, max_fields // max(n_traj, 1))
    leads = lead_list(n_leads)
    return [leads[i:i + per_chunk] for i in range(0, len(leads), per_chunk)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="ukmo-gloseas6,jma-jra3,bom-access-s2")
    ap.add_argument("--leads-per-chunk", type=int, default=0,
                    help="0 = size the chunks from the response budget")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    tags = [t for t in args.tag.split(",") if t]

    for tag in tags:
        lay = ensemble_layout(tag)
        if not lay:
            print("%s: no monthly u10 pull on disk - cannot enumerate the "
                  "start days" % tag, flush=True)
            continue
        days, numbering, nmem = lay
        groups = start_groups(numbering)
        counts = sorted({len(numbering[d]) for d in days})
        print("\n%s: %d members on %d start days (%s .. %s), %s per day"
              % (tag, nmem, len(days), days[0], days[-1], counts), flush=True)
        n_days = RUN_DAYS.get(tag, 215)
        leads = lead_list(n_days)
        print("   %d daily lead times (%d h .. %d h), %d month group(s)"
              % (len(leads), leads[0], leads[-1], len(groups)), flush=True)
        if args.dry_run:
            for (y, m, ds) in groups:
                ntraj = sum(len(numbering[d]) for d in ds)
                print("   group %04d-%02d: %d start days, %d trajectories"
                      % (y, m, len(ds), ntraj), flush=True)
                print("     the first request would be:", json.dumps(
                    build_request(tag, y, m, ds, leads[:24])), flush=True)
            continue

        c = CDSDirect()
        npz = os.path.join(MDIR, tag, "u10_daily.npz")
        acc = [None, None, None, None]
        for (y, m, ds) in groups:
            ntraj = sum(len(numbering[d]) for d in ds)
            # the grid of the centre: it sets the size of the answer
            points = 360 * 91
            try:
                import eccodes
                p = os.path.join(MDIR, tag, "u10_monthly.grib")
                with open(p, "rb") as f:
                    gid = eccodes.codes_grib_new_from_file(f)
                    ni = int(eccodes.codes_get(gid, "Ni"))
                    nj = int(eccodes.codes_get(gid, "Nj"))
                    eccodes.codes_release(gid)
                points = ni * nj // 2          # only the northern half is asked for
            except Exception:
                pass
            if args.leads_per_chunk:
                chunks = [leads[i:i + args.leads_per_chunk]
                          for i in range(0, len(leads), args.leads_per_chunk)]
            else:
                chunks = chunk_plan(ntraj, n_days, points)
            print("   group %04d-%02d: %d start days, %d trajectories, "
                  "%d chunk(s) of %d leads"
                  % (y, m, len(ds), ntraj, len(chunks), len(chunks[0])),
                  flush=True)
            for k, chunk in enumerate(chunks):
                gpath = os.path.join(MDIR, tag, "_lagged_c%d.grib" % k)
                if not fetch_chunk(c, tag, y, m, ds, chunk, gpath):
                    continue
                try:
                    recs, members = read_lagged_u10(gpath, numbering)
                    dates, m60, mnh, per_day = build_matrix(recs, members)
                finally:
                    if os.path.exists(gpath):
                        os.remove(gpath)
                missing = ntraj - len(members)
                print("   group %04d-%02d chunk %d: %d records, %d members, "
                      "%d dates%s"
                      % (y, m, k, len(recs), len(members), len(dates),
                         (" (SHORT by %d)" % missing) if missing else ""),
                      flush=True)
                if not members:
                    continue
                if acc[0] is None:
                    acc = [dates, m60, mnh, members]
                else:
                    acc = merge(acc, (dates, m60, mnh, members))
                centre, system = CENTRES[tag]
                save_npz(npz, acc[0], acc[1], acc[2], acc[3],
                         meta=dict(tag=tag, centre=centre, system=system,
                                   init="%04d-%02d" % init_of(tag),
                                   lagged=True, start_days=len(days),
                                   members_per_start_day=counts,
                                   members=len(acc[3]), days=len(acc[0]),
                                   source=DATASET))
        # the chart is drawn over the window in which the whole ensemble is
        # present, from the run's reference date onwards
        if acc[0]:
            init_date = max(days)
            trimmed, per_day = trim_to_run(acc, init_date, n_days)
            d, a, b, mem = trimmed
            if not d:
                d, a, b, mem = acc
            centre, system = CENTRES[tag]
            save_npz(npz, d, a, b, mem,
                     meta=dict(tag=tag, centre=centre, system=system,
                               init="%04d-%02d" % init_of(tag),
                               lagged=True, start_days=len(days),
                               members_per_start_day=counts,
                               members=len(mem), days=len(d),
                               members_per_day=sorted(set(per_day.values()))
                               if per_day else [],
                               source=DATASET))
            print("   %s: %d members x %d days (%s .. %s), %d members on "
                  "every day"
                  % (tag, len(mem), len(d), d[0], d[-1],
                     min(per_day.values()) if per_day else 0), flush=True)


if __name__ == "__main__":
    main()
