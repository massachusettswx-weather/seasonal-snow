"""Daily (sub-daily) seasonal snowfall pull.

Why this exists
---------------
The C3S *monthly* seasonal product caps at ``leadtime_month = 6``, so every
model on the site stopped at lead month 6 no matter how long its own forecast
actually ran.  The *original* (sub-daily) product carries the same variables
at 12-hourly resolution and accepts lead times well past its documented
5160 h ceiling, so it is the only route to a model's real lead time.

This script pulls ``snowfall`` from ``seasonal-original-single-levels`` for
each centre, streams the GRIB and accumulates it into

    * a monthly total per member (lead months 1..N of the model's own run)
    * a CONUS crop of the field (so the map panels can be drawn)

and stores it in ``data/models/<tag>/snow_daily.npz``.

Units
-----
The monthly product's snowfall is a *rate* (m w.e. s-1); the sub-daily product
may store an accumulation over the step (m) instead.  The reader looks at the
GRIB ``units`` and converts to metres of water equivalent per step, so both
conventions come out the same.  The cross-check is that lead month 1 from this
pull reproduces the monthly product's lead month 1 to within a few percent.
"""
import os, sys, json, time, argparse
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import eccodes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
STATE = os.path.join(DATA, "snow_daily_jobs.json")
DATASET = "seasonal-original-single-levels"

CHUNK = 72              # 12-hourly steps per CDS request (= 36 days)
MAX_INFLIGHT = 3        # the CDS queue gate lets ~3 of our jobs sit queued
WEDGE_S = 3 * 3600
N_DAYS_MAX = 365        # generous ceiling; each model is trimmed to its own end

# CONUS crop for the map panels (a little wider than the display domain)
LAT0, LAT1 = 20.0, 56.0
LON0, LON1 = -134.0, -56.0

CENTRES = [
    ("ecmwf-seas5", "ecmwf", "51", 2026, 11),
    ("cmcc-sps4", "cmcc", "4", 2026, 10),
    ("dwd-gcfs2", "dwd", "22", 2026, 10),
    ("eccc-canesm5", "eccc", "4", 2026, 10),
    ("eccc-gem5", "eccc", "5", 2026, 10),
    ("ukmo-gloseas6", "ukmo", "610", 2026, 10),
    ("meteo-france-s9", "meteo_france", "9", 2026, 10),
    ("ncep-cfsv2", "ncep", "2", 2026, 10),
    ("ncep-sfsv1", "ncep", "3", 2026, 10),
]


def load_centres():
    p = os.path.join(DATA, "snow_daily_centres.json")
    if not os.path.exists(p):
        return [(t, c, s, y, m, N_DAYS_MAX) for (t, c, s, y, m) in CENTRES]
    out = []
    # pull each centre at ITS OWN init: the non-ECMWF C3S contributions are
    # often a month behind the ECMWF one, and fetch_models.py probed and
    # recorded the freshest init each one actually serves.
    probed = {}
    fp = os.path.join(DATA, "models_fetched.json")
    if os.path.exists(fp):
        for k, v in json.load(open(fp)).items():
            if v.get("init"):
                probed[k] = v["init"]
    for e in json.load(open(p)):
        init = probed.get(e["tag"])
        y, m = int(e["year"]), int(e["month"])
        if init:
            yy, mm = init.split("-")
            y, m = int(yy), int(mm)
        out.append((e["tag"], e["centre"], str(e["system"]), y, m,
                    int(e.get("n_days", N_DAYS_MAX))))
    return out


# ---------------------------------------------------------------- decoding --

def _g(gid, key, default=None):
    try:
        return eccodes.codes_get(gid, key)
    except Exception:
        return default


def _normlon(lon):
    lon = np.asarray(lon, float)
    return np.where(lon > 180.0, lon - 360.0, lon)


def read_snow(path):
    """-> (months, members, acc[nmem, nmon, nlat, nlon], lats, lons)

    ``acc`` holds metres of water equivalent accumulated in each lead month
    for each ensemble member, on the CONUS crop.
    """
    months = []
    midx = {}
    members = []
    mid = {}
    acc = None
    lats = lons = None
    grid = None
    seen = set()

    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                dd = _g(gid, "dataDate")
                if dd is None:
                    continue
                dd = int(dd)
                st = int(_g(gid, "step", 0) or 0)
                valid = date(dd // 10000, (dd // 100) % 100, dd % 100) + timedelta(hours=st)
                # the accumulation covers [valid-step, valid); a 12 h step that
                # lands at 12Z belongs to the same calendar day, so the lead
                # month is the month of the valid date.
                ref = valid - timedelta(hours=st)
                key = (ref.year, ref.month)
                if key not in midx:
                    midx[key] = len(months)
                    months.append(key)
                mi = midx[key]

                pn = int(_g(gid, "perturbationNumber", 0) or 0)
                num = int(_g(gid, "number", 0) or 0)
                mem = num if num else pn
                if mem not in mid:
                    mid[mem] = len(members)
                    members.append(mem)
                ii = mid[mem]

                # --- the field
                la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                lo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                ni = int(_g(gid, "Ni", 0) or 0)
                nj = int(_g(gid, "Nj", 0) or 0)
                if ni and nj and v.size == ni * nj:
                    lat2d = la.reshape(nj, ni)
                    v = v.reshape(nj, ni)
                    lon2d = lo.reshape(nj, ni) if lo.size == ni * nj else lat2d.copy()
                else:
                    ulat = np.unique(la)[::-1]
                    ulon = np.unique(lo)
                    if v.size != ulat.size * ulon.size:
                        continue
                    v = v.reshape(len(ulat), len(ulon))
                    lat2d = np.repeat(ulat[:, None], len(ulon), axis=1)
                    lon2d = np.repeat(ulon[None, :], len(ulat), axis=0)

                # normalise the longitudes to -180..180 and apply the SAME
                # column permutation to the values
                lons = _normlon(lon2d[0, :]).copy()
                order = np.argsort(lons)
                lons = lons[order]
                v = v[:, order]
                lat2d = lat2d[:, order]
                lon2d = lon2d[:, order]
                lats = lat2d[:, 0].copy()

                if grid is None:
                    rlat = np.where((lats >= LAT0) & (lats <= LAT1))[0]
                    rlon = np.where((lons >= LON0) & (lons <= LON1))[0]
                    if not len(rlat) or not len(rlon):
                        continue
                    grid = (rlat, rlon)
                    glat = lats[rlat]
                    glon = lons[rlon]
                    acc = np.zeros((max(len(members), 1), 24, len(rlat), len(rlon)),
                                   np.float32)
                else:
                    rlat, rlon = grid
                    if not (np.allclose(lats[rlat], glat) and
                            np.allclose(lons[rlon], glon)):
                        continue          # a different grid: skip this record
                # --- units: accumulation (m) or rate (m s-1)
                units = str(_g(gid, "units", "") or "")
                if "s**-1" in units or "s-1" in units or "/s" in units:
                    val = v * float(st * 3600)
                else:
                    val = v
                rlat, rlon = grid
                if acc.shape[0] <= ii or acc.shape[1] <= mi:
                    newshape = (max(acc.shape[0], ii + 1), max(acc.shape[1], mi + 1),
                                acc.shape[2], acc.shape[3])
                    g = np.zeros(newshape, np.float32)
                    g[:acc.shape[0], :acc.shape[1]] = acc
                    acc = g
                acc[ii, mi] += val[np.ix_(rlat, rlon)].astype(np.float32)
                seen.add(mi)
            except Exception:
                pass
            finally:
                try:
                    eccodes.codes_release(gid)
                except Exception:
                    pass

    if acc is None:
        return [], [], None, None, None
    order = np.argsort([m[0] * 100 + m[1] for m in months])
    months = [months[i] for i in order]
    acc = acc[:, order]
    # drop the members that never received a record
    keep = [i for i in range(acc.shape[0])
            if np.isfinite(acc[i]).any() and np.abs(acc[i]).sum() > 0]
    acc = acc[keep]
    members = [members[i] for i in keep]
    return months, members, acc, glat, glon


def save_npz(path, months, members, acc, lats, lons, meta=None):
    np.savez_compressed(path,
                        months=np.array(["%04d-%02d" % m for m in months]),
                        members=np.array(members),
                        acc=acc,
                        lat=lats, lon=lons,
                        meta=np.array(json.dumps(meta or {})))


def load_npz(path):
    d = np.load(path, allow_pickle=True)
    months = [tuple(int(x) for x in str(m).split("-")) for m in d["months"]]
    meta = {}
    try:
        meta = json.loads(str(d["meta"]))
    except Exception:
        pass
    return months, list(d["members"]), d["acc"], d["lat"], d["lon"], meta


def merge_acc(dst, new):
    """Merge two (months, members, acc) sets that may overlap."""
    (m1, mem1, a1) = dst
    (m2, mem2, a2) = new
    allm = sorted(set(m1) | set(mem2))
    allmo = sorted(set(m1.keys()) | set(m2.keys())) if isinstance(m1, dict) else None
    return allm, allmo


# ------------------------------------------------------------------ fetching --

def daily_hours(n):
    """Every 12-hourly lead time over n days (00Z and 12Z).

    The monthly product's snowfall is a MEAN RATE over the calendar month, so
    the sub-daily field has to be integrated the same way: one 12 h step alone
    only covers half a day.  Asking for every 12 h step covers each calendar
    day twice, which is what the monthly totals are made of.
    """
    return [str(12 * (k + 1)) for k in range(2 * n)]


def chunk_list(n_days=N_DAYS_MAX, size=CHUNK):
    """`size` is in 12-hourly steps."""
    hs = daily_hours(n_days)
    return [hs[i:i + size] for i in range(0, len(hs), size)]


def load_state():
    return json.load(open(STATE)) if os.path.exists(STATE) else {"jobs": []}


def save_state(st):
    json.dump(st, open(STATE, "w"), indent=1)


def live_jobs(st):
    return [j for j in st["jobs"]
            if j.get("job") and j.get("status") in ("accepted", "running", "queued")]


def decoded_chunks(st):
    out = {}
    for j in st["jobs"]:
        if j.get("status") == "decoded":
            out.setdefault(j["tag"], set()).add(j.get("chunk", 0))
    return out


def submit(c, only=None):
    from cds_direct import QueueFull, NoData
    st = load_state()
    done = decoded_chunks(st)
    live = live_jobs(st)
    # the stall brake only applies for a while: a queue that is merely slow
    # must not throttle the pool to a single job for hours
    if st.get("stall") and time.time() - st.get("stall_at", 0) > 1800:
        st["stall"] = False
    cap = 1 if st.get("stall") else MAX_INFLIGHT
    live_keys = {(j["tag"], j.get("chunk", 0)) for j in live}
    # a chunk that failed is past the model's own lead time - it can never
    # succeed, and neither can the chunks after it.  Do not keep re-submitting
    # them: that only burns the three queue slots.
    failed_min = {}
    for j in st["jobs"]:
        if j.get("status") in ("failed", "rejected", "dismissed", "gone",
                               "stalled", "download_failed", "decode_failed"):
            note = j.get("note") or ""
            if "Maximum number queued" in note or "queue" in note.lower():
                # the CDS refused it because our own pool was full - that is
                # not "no data", so the chunk is still worth submitting
                continue
            k = j.get("chunk", 0)
            failed_min[j["tag"]] = min(failed_min.get(j["tag"], 10 ** 6), k)
    new = 0
    cands = []
    for tag, centre, sysid, yy, mm, ndays in load_centres():
        if only and tag not in only:
            continue
        for k in range(len(chunk_list(ndays))):
            if k in done.get(tag, ()) or (tag, k) in live_keys:
                continue
            if k >= failed_min.get(tag, 10 ** 6):
                continue        # past the model's own lead time
            cands.append((-len(done.get(tag, ())), tag, centre, sysid, yy, mm, ndays, k))
    cands.sort()
    for _, tag, centre, sysid, yy, mm, ndays, k in cands:
        if len(live) + new >= cap:
            break
        hs = chunk_list(ndays)[k]
        req = {"originating_centre": centre, "system": sysid,
               "variable": "snowfall", "year": str(yy), "month": "%02d" % mm,
               "day": "01", "leadtime_hour": hs, "data_format": "grib"}
        try:
            jid = c.submit(DATASET, req)
        except QueueFull:
            print("!! queue full at %s - retry" % tag, flush=True)
            save_state(st)
            continue
        except NoData as e:
            if "Maximum number queued" in str(e):
                print("   (pool full at %s chunk %d - will retry)" % (tag, k),
                      flush=True)
                continue
            print("!! %s chunk %d REJECTED: %s" % (tag, k, str(e)[:160]), flush=True)
            st["jobs"].append(dict(tag=tag, chunk=k, job=None, status="rejected",
                                   note=str(e)[:300]))
            save_state(st)
            continue
        st["jobs"].append(dict(tag=tag, chunk=k, job=jid, status="accepted",
                               hours=hs, init="%04d-%02d" % (yy, mm),
                               _t0=time.time()))
        save_state(st)
        new += 1
        print("submitted %-16s snow chunk %d (%d steps) job %s"
              % (tag, k, len(hs), jid[:8]), flush=True)
        time.sleep(5)
    print("submitted %d new snow job(s)" % new, flush=True)
    return new


def poll(c):
    st = load_state()
    changed = False
    for j in st["jobs"]:
        if not j.get("job") or j.get("status") in ("decoded", "failed"):
            continue
        s = c.job_status(j["job"])
        if s != j.get("status"):
            j["status"] = s
            changed = True
            print("%-16s snow chunk %d -> %s" % (j["tag"], j["chunk"], s), flush=True)
        if s in ("accepted", "queued"):
            waited = time.time() - j.get("_t0", time.time())
            if waited > WEDGE_S:
                print("%-16s snow chunk %d WEDGED - dismissing" % (j["tag"], j["chunk"]),
                      flush=True)
                try:
                    c._request("DELETE", "/retrieve/v1/jobs/%s" % j["job"])
                except Exception:
                    pass
                j["status"] = "wedged"
                j["_t0"] = time.time()
                changed = True
            continue
        if s != "successful":
            if s in ("failed", "rejected", "dismissed"):
                j["status"] = "failed"
                j["note"] = c._job_detail(j["job"])[:300]
                changed = True
            continue
        tag, k = j["tag"], j["chunk"]
        gpath = os.path.join(MDIR, tag, "snow_daily_c%d.grib" % k)
        os.makedirs(os.path.dirname(gpath), exist_ok=True)
        try:
            c.download_job(j["job"], gpath)
        except Exception as e:
            print("  snow download failed:", str(e)[:180], flush=True)
            j["status"] = "download_failed"
            j["note"] = str(e)[:300]
            save_state(st)
            continue
        print("  downloaded %s snow chunk %d (%.0f MB)"
              % (tag, k, os.path.getsize(gpath) / 1e6), flush=True)
        try:
            months, members, acc, lats, lons = read_snow(gpath)
        except Exception as e:
            print("  snow decode failed:", str(e)[:200], flush=True)
            j["status"] = "decode_failed"
            j["note"] = str(e)[:300]
            save_state(st)
            continue
        finally:
            if os.path.exists(gpath):
                os.remove(gpath)
        npz = os.path.join(MDIR, tag, "snow_daily.npz")
        if os.path.exists(npz):
            om, ome, oacc, olat, olon, ometa = load_npz(npz)
            # merge on (month, member)
            keys = sorted(set(om) | set(months))
            mems = sorted(set(ome) | set(members))
            ki = {k: i for i, k in enumerate(keys)}
            mi = {m: i for i, m in enumerate(mems)}
            A = np.zeros((len(mems), len(keys),) + oacc.shape[2:], np.float32)
            for i, m in enumerate(ome):
                for j, k in enumerate(om):
                    A[mi[m], ki[k]] = oacc[i, j]
            for i, m in enumerate(members):
                for j, k in enumerate(months):
                    A[mi[m], ki[k]] += acc[i, j]
            months, members, acc = keys, mems, A
        save_npz(npz, months, members, acc, lats, lons,
                 meta=dict(tag=tag, init=j.get("init", "")))
        j["status"] = "decoded"
        j["months"] = len(months)
        j["members"] = len(members)
        changed = True
        print("  decoded %s: %d lead months, %d members -> %s"
              % (tag, len(months), len(members), os.path.basename(npz)), flush=True)
        save_state(st)
    if changed:
        save_state(st)
    print("\n--- per-centre daily snowfall status")
    for tag, *_ in load_centres():
        js = [j for j in st["jobs"] if j["tag"] == tag]
        done = sum(1 for j in js if j.get("status") == "decoded")
        pend = sum(1 for j in js if j.get("status") in ("accepted", "running", "queued"))
        bad = sum(1 for j in js if j.get("status") in ("failed", "rejected",
                                                       "download_failed", "decode_failed"))
        npz = os.path.join(MDIR, tag, "snow_daily.npz")
        extra = ""
        if os.path.exists(npz):
            m, me, a, la, lo, meta = load_npz(npz)
            extra = " | %d members x %d months (%s -> %s)" % (
                len(me), len(m), "%04d-%02d" % m[0], "%04d-%02d" % m[-1])
        print("  %-16s chunks %d done, %d pending, %d failed%s"
              % (tag, done, pend, bad, extra))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    from cds_direct import CDSDirect
    c = CDSDirect()
    only = [x for x in args.only.split(",") if x] or None
    if args.auto:
        for i in range(400):
            submit(c, only=only)
            poll(c)
            st = load_state()
            have = {j["tag"] for j in st["jobs"] if j.get("status") == "decoded"}
            missing = [t for t, *_ in load_centres() if t not in have and
                       (not only or t in only)]
            if not missing:
                print("ALL CENTRES HAVE DAILY SNOW", flush=True)
                break
            print(">> still missing:", ", ".join(missing), flush=True)
            time.sleep(40)
        return
    submit(c, only=only)
    poll(c)


if __name__ == "__main__":
    main()
