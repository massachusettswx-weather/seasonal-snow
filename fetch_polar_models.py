"""The seasonal models' polar cap geopotential height, daily, through the end
of each model's own run.

This is the forecast side of the polar-cap time-height section: the same
quantity the ERA5 analysis gives (polar cap mean geopotential height on
twelve pressure levels), but for a seasonal model and out to the end of that
model's run rather than 15 days.

The source is the C3S sub-daily pressure-level archive
("seasonal-original-pressure-levels"), which carries `geopotential` on
exactly the twelve levels the reference figure uses and reaches
leadtime_hour = 5160 h = 215 days.

Two things shape the requests:

  * the archive caps the RESPONSE SIZE, not the ensemble size: a request for
    many members over many days comes back with fewer members than asked
    for, silently.  So the run is split into short chunks of days and each
    chunk is checked for how many members it actually carried.
  * the CDS admission gate is account-wide at two queued requests, so this
    puller keeps at most two in flight and never competes with the rest of
    the pipeline for a third.

Every chunk is reduced to the polar cap mean per level on arrival and only
that is kept.
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import LEVELS, read_grib_levels  # noqa: E402

STATE = os.path.join(DATA, "polar_model_jobs.json")
OUT = os.path.join(DATA, "polar_model_z.json")

LV = [str(x) for x in LEVELS]
AREA = [90, -180, 60, 180]

# tag, originating_centre, system
# The order is the order the chunks are queued in, so it is a priority
# list: every other centre gets its first chunk before the SEAS5 section
# is taken out to the end of its run.  Breadth first - a section for a new
# system is worth more than more days on the one we already have.
CENTRES = [
    ("meteo-france-s9", "meteo_france", "9"),
    ("cmcc-sps4", "cmcc", "4"),
    ("dwd-gcfs2", "dwd", "22"),
    ("eccc-canesm5", "eccc", "4"),
    ("eccc-gem5", "eccc", "5"),
    ("ecmwf-seas5", "ecmwf", "51"),
    ("ukmo-gloseas6", "ukmo", "610"),
    ("jma-jra3", "jma", "4"),
    ("bom-access-s2", "bom", "2"),
]

# the days per chunk: the archive caps the RESPONSE SIZE, and the S4S
# ensemble is 51 members over ten levels, so the chunks are short.  A chunk
# of 30 days at twelve levels over the polar cap is about 800 MB before
# compression, which is over what the archive will serve with every member
# in it; 15 days fits.
CHUNK_DAYS = 15

# a chunk that carries fewer members than the model has is a broken answer
MIN_MEMBERS = 10


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"jobs": []}


def save_state(st):
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w"), indent=1)
    os.replace(tmp, STATE)


def load_out():
    if os.path.exists(OUT):
        return json.load(open(OUT))
    return {}


def save_out(o):
    tmp = OUT + ".tmp"
    json.dump(o, open(tmp, "w"))
    os.replace(tmp, OUT)


def init_of(tag):
    """The init (year, month) the model is on, from the pipeline's own state."""
    p = os.path.join(DATA, "models_fetched.json")
    if not os.path.exists(p):
        return 2026, 11
    try:
        d = json.load(open(p))
    except Exception:
        return 2026, 11
    for key in (tag, tag.replace("-", "_")):
        v = d.get(key)
        if v and v.get("init"):
            yy, mm = v["init"].split("-")
            return int(yy), int(mm)
    return 2026, 11


def chunk_list(n_days):
    return [(i, i + CHUNK_DAYS) for i in range(0, n_days, CHUNK_DAYS)]


def build_request(tag, centre, system, year, month, day0, day1):
    """The request for one chunk: the daily 12Z lead times from day0 to day1.

    The C3S seasonal runs are initialised at 00Z on the 1st of the month,
    so the 12Z value of a day sits at a lead time of 12 + 24k hours.  The
    ERA5 half of the section is on the same 12Z clock, and the
    climatology is keyed by calendar day, so the forecast has to be on 12Z
    too - a 24k lead time would be the 00Z value of a different day and
    would land against the wrong calendar day in the climatology.
    """
    hours = [str(12 + 24 * k) for k in range(day0, day1)]
    return {
        "originating_centre": centre,
        "system": system,
        "variable": ["geopotential"],
        "pressure_level": LV,
        "year": [str(year)],
        "month": ["%02d" % month],
        "day": ["01"],
        "leadtime_hour": hours,
        "area": AREA,
        "data_format": "grib",
    }


def account_inflight(cds):
    """How many jobs the ACCOUNT holds right now, on any dataset.

    The CDS admission gate is ACCOUNT-WIDE at two: with two of our requests
    sitting queued, a third is refused whatever dataset it targets.  So the
    count has to come from the account's own job list, not from our own
    state file.

    The list only carries the most recent records, so it can undercount if
    the account holds a lot of old jobs; the count is therefore raised by
    our own jobs that are still in flight.
    """
    n = 0
    try:
        for j in cds.live_jobs():
            if j.get("status") in ("accepted", "running", "queued"):
                n += 1
    except Exception:
        return None
    return n


def members_in(grib_path):
    """How many distinct ensemble members the chunk actually carried."""
    import eccodes
    mems = set()
    with open(grib_path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                for k in ("number", "perturbationNumber"):
                    v = eccodes.codes_get(gid, k)
                    if v is not None:
                        mems.add((k, int(v)))
            except Exception:
                pass
            finally:
                eccodes.codes_release(gid)
    per = {}
    for k, v in mems:
        per.setdefault(k, set()).add(v)
    if not per:
        return 0
    return max(len(s) for s in per.values())


def main():
    import cds_direct
    cds = cds_direct.CDSDirect()
    st = load_state()
    out = load_out()
    MAX_INFLIGHT = 2

    def decoded(tag):
        return {j["chunk"] for j in st["jobs"]
                if j.get("tag") == tag and j.get("status") == "decoded"}

    def live():
        return [j for j in st["jobs"]
                if j.get("status") in ("accepted", "running", "queued")]

    # the number of days each model's run covers: the C3S seasonal systems
    # run to 215 days (leadtime_hour 5160) except the shorter ones.
    RUN_DAYS = {
        "ecmwf-seas5": 215, "ukmo-gloseas6": 215, "meteo-france-s9": 212,
        "cmcc-sps4": 184, "dwd-gcfs2": 181, "eccc-canesm5": 214,
        "eccc-gem5": 214, "jma-jra3": 215, "bom-access-s2": 215,
    }

    while True:
        # 1. harvest
        for j in list(st["jobs"]):
            # a job with no status (or one that is not yet finished) is
            # asked again: the harvest must not skip a job that the
            # archive has in fact completed
            if j.get("status") in ("decoded", "short", "failed", "superseded"):
                continue
            status = cds.job_status(j["job"])
            j["status"] = status
            if status in ("completed", "successful"):
                    path = os.path.join(DATA, "_polz_%s_%d.grib"
                                        % (j["tag"], j["chunk"]))
                    cds.download_job(j["job"], path)
                    nmem = members_in(path)
                    times, vals = read_grib_levels(path)
                    os.remove(path)
                    if nmem < MIN_MEMBERS:
                        print("   the %s chunk %d carries only %d members - "
                              "discarded" % (j["tag"], j["chunk"], nmem), flush=True)
                        j["status"] = "short"
                        continue
                    rec = out.setdefault(j["tag"], {"times": [], "values": [],
                                                    "members": nmem,
                                                    "levels": list(LEVELS)})
                    # the chunks overlap, so a time that is already in the
                    # record is replaced rather than appended: otherwise the
                    # same day is counted three times
                    have = {t: i for i, t in enumerate(rec["times"])}
                    for t, v in vals.items():
                        row = [v.get(l) for l in LEVELS]
                        if not all(x is not None for x in row):
                            continue
                        if t in have:
                            rec["values"][have[t]] = row
                        else:
                            have[t] = len(rec["times"])
                            rec["times"].append(t)
                            rec["values"].append(row)
                    order = sorted(range(len(rec["times"])),
                                   key=lambda i: rec["times"][i])
                    rec["times"] = [rec["times"][i] for i in order]
                    rec["values"] = [rec["values"][i] for i in order]
                    rec["members"] = max(rec.get("members", 0), nmem)
                    save_out(out)
                    j["status"] = "decoded"
                    j["members"] = nmem
                    print("   the %s chunk %d decoded: %d members, %d times"
                          % (j["tag"], j["chunk"], nmem, len(rec["times"])), flush=True)
            elif status in ("failed", "rejected", "dismissed", "gone"):
                    print("   the %s chunk %d is %s" % (j["tag"], j["chunk"], status),
                          flush=True)
                    j["status"] = "failed"
        save_state(st)

        # 1b. the ECCC's two systems are one card on the site - the official
        # canSIPS - so the polar-cap series is pooled the same way: the
        # ensemble mean of the two systems, twenty members each.
        if "eccc-canesm5" in out and "eccc-gem5" in out:
            a, b = out["eccc-canesm5"], out["eccc-gem5"]
            common = sorted(set(a["times"]) & set(b["times"]))
            if len(common) >= 3:
                ia = {t: i for i, t in enumerate(a["times"])}
                ib = {t: i for i, t in enumerate(b["times"])}
                rows = []
                for t in common:
                    ra = a["values"][ia[t]]
                    rb = b["values"][ib[t]]
                    rows.append([(x + y) / 2.0 for x, y in zip(ra, rb)])
                pooled = {"times": common, "values": rows,
                          "members": int(a.get("members", 20))
                                     + int(b.get("members", 20)),
                          "levels": list(LEVELS)}
                if out.get("eccc-cansips") != pooled:
                    out["eccc-cansips"] = pooled
                    save_out(out)
                    print("   the ECCC's two systems pooled into canSIPS: "
                          "%d days, %d members" % (len(common),
                                                  pooled["members"]), flush=True)

        # 2. submit
        n = account_inflight(cds)
        if n is None:
            n = len(live())
        room = MAX_INFLIGHT - n
        for tag, centre, system in CENTRES:
            if room <= 0:
                break
            year, month = init_of(tag)
            have = decoded(tag)
            pending = {j["chunk"] for j in st["jobs"]
                       if j.get("tag") == tag
                       and j.get("status") in ("accepted", "running", "queued")}
            failed = {j["chunk"] for j in st["jobs"]
                      if j.get("tag") == tag and j.get("status") in ("short", "failed")}
            for c0, c1 in chunk_list(RUN_DAYS.get(tag, 215)):
                # the room counter has to be checked INSIDE the chunk loop:
                # the archive's admission gate is account-wide at two, and a
                # submission past it is refused (the refusal is free, but it
                # is still fifteen wasted requests to the archive)
                if room <= 0:
                    break
                if c0 in have or c0 in pending:
                    continue
                if c0 in failed:
                    continue
                try:
                    req = build_request(tag, centre, system, year, month,
                                        1, c1)
                    jid = cds.submit("seasonal-original-pressure-levels", req)
                except Exception as e:
                    print("   the %s chunk %d submission failed: %s"
                          % (tag, c0, str(e)[:120]), flush=True)
                    room -= 1
                    continue
                st["jobs"].append({"tag": tag, "centre": centre, "system": system,
                                   "chunk": c0, "end": c1, "job": jid,
                                   "status": "accepted", "init": "%04d-%02d" % (year, month)})
                print("   the %s chunk %d (%d days) submitted: %s"
                      % (tag, c0, c1, jid), flush=True)
                room -= 1
        save_state(st)

        done = sum(1 for j in st["jobs"] if j.get("status") == "decoded")
        todo = [j for j in st["jobs"]
                if j.get("status") in ("accepted", "running", "queued")]
        if not todo:
            print("   nothing in flight; the decoded chunks are %d" % done, flush=True)
        time.sleep(45)


if __name__ == "__main__":
    main()
