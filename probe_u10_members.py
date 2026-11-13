"""Probe how many ensemble members the C3S sub-daily product really serves.

The UKMO, the JMA and the BoM all came back "short": a chunk that should hold
the whole ensemble arrives with a handful of members.  Before asking for a
whole run it is worth knowing whether the archive is truncating the answer or
whether the reader is mis-grouping it, so this asks for the smallest possible
request and counts the members in the RAW GRIB.

    python3 probe_u10_members.py ukmo 610 1
    python3 probe_u10_members.py jma 4 1
"""
import os
import sys
import subprocess
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cds_direct import CDSDirect  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CENTRE = {"ukmo-gloseas6": "ukmo", "jma-jra3": "jma", "bom-access-s2": "bom",
          "cmcc-sps4": "cmcc"}


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "ukmo-gloseas6"
    system = sys.argv[2] if len(sys.argv) > 2 else "610"
    ndays = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    centre = CENTRE.get(tag, tag)

    days = ["%02d" % d for d in range(1, 1 + ndays)]
    if os.environ.get("PROBE_LEAD"):
        days = ["01"]
    lead = os.environ.get("PROBE_LEAD")
    if lead:
        hs = [lead]
    else:
        hs = ["%d" % (12 + 24 * k) for k in range(ndays)]
    req = {"originating_centre": centre, "system": str(system),
           "variable": "u_component_of_wind", "pressure_level": "10",
           "year": "2026", "month": "11", "day": days,
           "leadtime_hour": hs, "data_format": "grib"}
    if os.environ.get("PROBE_AREA"):
        req["area"] = [90, -180, 60, 180]
        print("with the polar-cap area")
    c = CDSDirect()
    jid = c.submit("seasonal-original-pressure-levels", req)
    print("submitted %s system %s (%d day(s)) -> %s" % (centre, system, ndays, jid),
          flush=True)
    out = os.path.join(HERE, "data", "probe_u10_%s.grib" % tag)
    for _ in range(180):
        time.sleep(20)
        st = c.job_status(jid)
        s = st.get("status") if isinstance(st, dict) else str(st)
        if s in ("successful", "completed", "failed", "rejected", "dismissed"):
            break
    print("the job's status:", s, flush=True)
    if s not in ("successful", "completed"):
        return
    c.download_job(jid, out)
    print("downloaded %.1f MB" % (os.path.getsize(out) / 1e6), flush=True)
    # count the members in the raw GRIB, without the pipeline's reader
    msg = subprocess.run(["grib_ls", "-p", "number,perturbationNumber,step"],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if msg.returncode != 0:
        print(msg.stdout.decode()[-500:], flush=True)
    print(msg.stdout.decode()[-1500:], flush=True)


if __name__ == "__main__":
    main()
