"""Fetch DAILY (subdaily) 10 hPa u for the non-ECMWF seasonal centres.

The monthly product only gives one value per lead month, which makes a very
coarse SPV chart.  The C3S *original* (subdaily) product carries every
ensemble member at 12-hourly resolution, so the same chart can be drawn for
every centre with a realistic daily spread - exactly like the ECMWF panel.

Why this is its own script rather than an extension of fetch_models.py:

  * the CDS subdaily queue is currently ~1000 jobs deep and shared with every
    other C3S user, so every request has to be submitted up front and polled
    rather than blocked on one at a time;
  * a full 215-day pull is ~2 GB per centre, more than the workspace quota
    allows to sit on disk, so each chunk is decoded to a tiny .npz and the
    raw GRIB is deleted immediately;
  * the dataset is called "subdaily" but the C3S ensemble member layout differs
    from centre to centre, so the decoding lives in u10_daily.py.

usage:
  python3 fetch_models_daily.py --submit     # queue every chunk
  python3 fetch_models_daily.py --poll       # download + decode what is ready
  python3 fetch_models_daily.py               # both
"""
import os, sys, json, time, argparse
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cds_direct import CDSDirect, QueueFull, NoData      # noqa: E402
from u10_daily import read_daily_u10, build_matrix, save_npz, load_npz  # noqa: E402

DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
STATE = os.path.join(DATA, "daily_jobs.json")
DATASET = "seasonal-original-pressure-levels"

N_DAYS = 215          # 12Z daily, init day -> ~7 months (same as the ECMWF pull)
CHUNK = 215           # days per job.  The CDS rejects a job when the dataset
                      # queue is saturated, so we keep ONE job in flight per
                      # centre rather than many chunks (the queue is the
                      # scarce resource, not the job size).
MAX_INFLIGHT = 3      # the CDS queue gate lets ~3 of our jobs sit queued at
                      # once; anything beyond that is rejected outright.

# tag, originating_centre, system, init year, init month
CENTRES = [
    ("cmcc-sps4",    "cmcc",         "4",   2026, 10),
    ("dwd-gcfs2",    "dwd",          "22",  2026, 10),
    ("eccc-canesm5", "eccc",         "4",   2026, 10),
    ("eccc-gem5",    "eccc",         "5",   2026, 10),
    ("ukmo-gloseas6", "ukmo",        "610", 2026, 10),
    ("meteo-france-s9", "meteo_france", "9", 2026, 10),
]


def daily_hours(n=N_DAYS):
    return [str(12 + 24 * k) for k in range(n)]


def chunks(n_days=N_DAYS, size=CHUNK):
    hs = daily_hours(n_days)
    return [hs[i:i + size] for i in range(0, len(hs), size)]


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"jobs": []}


def save_state(st):
    json.dump(st, open(STATE, "w"), indent=1)


def live_jobs(st):
    return [j for j in st["jobs"]
            if j.get("job") and j.get("status") in ("accepted", "running", "queued")]


def submit(c, only=None):
    """Queue one job per centre, up to MAX_INFLIGHT in the queue at a time.

    The CDS queue gate rejects a job outright when too many of ours are
    already waiting, so we refill the pool only as jobs come off the queue.
    """
    st = load_state()
    done = {j["tag"] for j in st["jobs"] if j.get("status") == "decoded"}
    live = live_jobs(st)
    live_tags = {j["tag"] for j in live}
    new = 0
    for tag, centre, sysid, yy, mm in CENTRES:
        if only and tag not in only:
            continue
        if tag in done or tag in live_tags:
            continue
        if len(live) + new >= MAX_INFLIGHT:
            print("-- %s deferred (queue pool full: %d live)" % (tag, len(live) + new),
                  flush=True)
            continue
        hs = daily_hours(N_DAYS)
        req = {"originating_centre": centre, "system": sysid,
               "variable": "u_component_of_wind", "pressure_level": "10",
               "year": str(yy), "month": "%02d" % mm, "day": "01",
               "leadtime_hour": hs, "data_format": "grib"}
        try:
            jid = c.submit(DATASET, req)
        except QueueFull:
            print("!! queue full at %s - will retry" % tag, flush=True)
            save_state(st)
            continue
        except NoData as e:
            print("!! %s REJECTED at submit: %s" % (tag, str(e)[:200]), flush=True)
            st["jobs"].append(dict(tag=tag, centre=centre, system=sysid, chunk=0,
                                   hours=hs, job=None, status="rejected",
                                   init="%04d-%02d" % (yy, mm), note=str(e)[:300]))
            save_state(st)
            continue
        st["jobs"].append(dict(tag=tag, centre=centre, system=sysid, chunk=0,
                               hours=hs, job=jid, status="accepted",
                               init="%04d-%02d" % (yy, mm)))
        save_state(st)
        new += 1
        print("submitted %-16s %d steps  job %s" % (tag, len(hs), jid[:8]), flush=True)
        time.sleep(6)
    print("submitted %d new job(s)" % new, flush=True)
    return new


def merge(dst, new):
    """Merge a decoded chunk into the per-centre accumulator."""
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


def poll(c):
    st = load_state()
    changed = False
    for j in st["jobs"]:
        if not j.get("job"):
            continue
        if j.get("status") in ("decoded", "failed"):
            continue
        s = c.job_status(j["job"])
        if s != j.get("status"):
            j["status"] = s
            changed = True
            print("%-16s chunk %d -> %s" % (j["tag"], j["chunk"], s), flush=True)
        if s != "successful":
            if s in ("failed", "rejected", "dismissed"):
                j["status"] = "failed"
                j["note"] = c._job_detail(j["job"])[:300]
            continue

        # download -> decode -> delete the raw GRIB (disk quota!)
        tag, k = j["tag"], j["chunk"]
        gpath = os.path.join(MDIR, tag, "u10_daily_c%d.grib" % k)
        os.makedirs(os.path.dirname(gpath), exist_ok=True)
        try:
            c.download_job(j["job"], gpath)
        except Exception as e:
            print("  download failed:", str(e)[:200], flush=True)
            j["status"] = "download_failed"
            j["note"] = str(e)[:300]
            save_state(st)
            continue
        mb = os.path.getsize(gpath) / 1e6
        print("  downloaded %s chunk %d (%.0f MB) - decoding" % (tag, k, mb), flush=True)
        try:
            recs, members = read_daily_u10(gpath)
            dates, m60, mnh = build_matrix(recs, members)
        except Exception as e:
            print("  decode failed:", str(e)[:200], flush=True)
            j["status"] = "decode_failed"
            j["note"] = str(e)[:300]
            save_state(st)
            continue
        finally:
            if os.path.exists(gpath):
                os.remove(gpath)          # keep the disk small

        npz = os.path.join(MDIR, tag, "u10_daily.npz")
        if os.path.exists(npz):
            old = load_npz(npz)
            merged = merge((old[0], old[1], old[2], old[3]),
                           (dates, m60, mnh, members))
        else:
            merged = (dates, m60, mnh, members)
        save_npz(npz, merged[0], merged[1], merged[2], merged[3],
                 meta=dict(tag=tag, centre=j["centre"], system=j["system"],
                           init=j.get("init", "")))
        j["status"] = "decoded"
        j["records"] = len(recs)
        j["members"] = len(members)
        changed = True
        print("  decoded: %d records, %d members, %d dates -> %s"
              % (len(recs), len(members), len(dates), os.path.basename(npz)), flush=True)
        save_state(st)
    if changed:
        save_state(st)

    # summary
    print("\n--- per-centre daily status")
    for tag, *_ in CENTRES:
        js = [j for j in st["jobs"] if j["tag"] == tag]
        done = sum(1 for j in js if j.get("status") == "decoded")
        pend = sum(1 for j in js if j.get("status") in ("accepted", "running", "queued"))
        bad = sum(1 for j in js if j.get("status") in ("failed", "rejected",
                                                       "download_failed", "decode_failed"))
        npz = os.path.join(MDIR, tag, "u10_daily.npz")
        extra = ""
        if os.path.exists(npz):
            d, a, b, m, meta = load_npz(npz)
            extra = " | %d members x %d days (%s -> %s)" % (
                a.shape[0], a.shape[1], d[0], d[-1])
        print("  %-16s chunks %d/%d done, %d pending, %d failed%s"
              % (tag, done, len(js), pend, bad, extra))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--poll", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--auto", action="store_true",
                    help="loop: keep the queue pool full until every centre is done")
    args = ap.parse_args()
    c = CDSDirect()
    only = [x for x in args.only.split(",") if x] or None
    if args.auto:
        for i in range(400):
            submit(c, only=only)
            poll(c)
            st = load_state()
            have = {j["tag"] for j in st["jobs"] if j.get("status") == "decoded"}
            missing = [t for t, *_ in CENTRES if t not in have and
                       (not only or t in only)]
            if not missing:
                print("ALL CENTRES HAVE DAILY DATA", flush=True)
                break
            print(">> still missing:", ", ".join(missing), flush=True)
            time.sleep(90)
        return
    if not args.poll:
        submit(c, only=only)
    if not args.submit:
        poll(c)


if __name__ == "__main__":
    main()
