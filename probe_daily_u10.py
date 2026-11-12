"""Probe the C3S sub-daily product for one centre's full ensemble.

The daily 10 hPa wind is only useful if the request comes back with the
whole ensemble.  The pool discards a chunk that arrives with far fewer
members than the centre has, and after three such chunks it gives up on
the centre's daily series.  This probe asks for three days and reports
what the archive actually sent: how many messages, how many distinct
member numbers, how many distinct perturbation numbers, the levels and the
valid times.  It reads the GRIB directly - the decoder is not involved -
so a decoder mistake cannot hide behind it.

    python3 probe_daily_u10.py ukmo-gloseas6
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import eccodes  # noqa: E402
import cds_direct  # noqa: E402

DS_ORIGINAL_PL = "seasonal-original-pressure-levels"

# tag -> (centre, system)
CENTRES = {
    "ecmwf-seas5": ("ecmwf", "51"),
    "ukmo-gloseas6": ("ukmo", "610"),
    "meteo-france-s9": ("meteo-france", "9"),
    "cmcc-sps4": ("cmcc", "4"),
    "dwd-gcfs2": ("dwd", "22"),
    "eccc-canesm5": ("eccc", "4"),
    "eccc-gem5": ("eccc", "5"),
    "jma-jra3": ("jma", "4"),
    "bom-access-s2": ("bom", "2"),
}


def survey(path):
    """-> (n messages, the distinct numbers, the distinct perturbations,
    the levels, the valid times, the member counts per valid time)."""
    nums, pns, levels, valids = set(), set(), set(), set()
    nmsg = 0
    per_valid = {}
    with open(path, "rb") as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            nmsg += 1
            try:
                n = eccodes.codes_get(gid, "number")
                p = eccodes.codes_get(gid, "perturbationNumber")
                lev = eccodes.codes_get(gid, "level")
                vd = eccodes.codes_get(gid, "validityDate")
                vt = eccodes.codes_get(gid, "validityTime")
                step = eccodes.codes_get(gid, "step")
                nums.add(int(n) if n is not None else -1)
                pns.add(int(p) if p is not None else -1)
                levels.add(int(lev) if lev is not None else -1)
                valids.add((int(vd), int(vt), int(step)))
                key = (int(vd), int(vt), int(step))
                per_valid.setdefault(key, set()).add(int(n) if n is not None else -1)
            except Exception as e:
                print("   (a key is missing: %s)" % str(e)[:60])
            finally:
                eccodes.codes_release(gid)
    return nmsg, sorted(nums), sorted(pns), sorted(levels), sorted(valids), per_valid


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "ukmo-gloseas6"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    init = sys.argv[3] if len(sys.argv) > 3 else "2026-11"
    centre, system = CENTRES[tag]
    hours = [str(12 + 24 * k) for k in range(days)]
    req = {"originating_centre": centre, "system": system,
           "variable": "u_component_of_wind", "pressure_level": "10",
           "year": init[:4], "month": init[5:7], "day": "01",
           "leadtime_hour": hours, "data_format": "grib"}
    out = os.path.join(HERE, "data", "probe_%s.grib" % tag)
    c = cds_direct.CDSDirect()
    print("   the request: %s" % req)
    jid = c.submit(DS_ORIGINAL_PL, req)
    print("   the job %s" % jid)
    for _ in range(200):
        s = c.job_status(jid)
        if s == "successful":
            c.download_job(jid, out)
            break
        if s in ("failed", "rejected", "gone", "dismissed"):
            print("   the job %s: %s" % (s, c._job_detail(jid)[:300].replace("\n", " ")))
            return
        time.sleep(20)
    else:
        print("   the job did not finish in time")
        return
    nmsg, nums, pns, levels, valids, per_valid = survey(out)
    print("   the messages: %d" % nmsg)
    print("   the distinct 'number': %d  %s" % (len(nums), nums[:20]))
    print("   the distinct 'perturbationNumber': %d  %s" % (len(pns), pns[:20]))
    print("   the levels: %s" % levels)
    print("   the valid times (date, time, step):")
    for v in valids:
        print("      %s   the members: %d  %s" % (v, len(per_valid[v]),
                                                  sorted(per_valid[v])[:14]))
    print("   the file: %s (%.1f MB)" % (out, os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    main()
