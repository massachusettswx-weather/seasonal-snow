"""Wait for the queued extended-lead SST job and process it when it lands.

The C3S "seasonal-original-single-levels" queue is deep, so the job that
carries lead month 7 can sit for a long time.  This watcher keeps the job
alive and turns it into data/models/<tag>/sst_extended.npz as soon as the
results are ready.

    python3 watch_ext.py <tag> <job-id> [centre] [system]
"""
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cds_direct                                        # noqa: E402
from enso_common import BASIN_NAMES                      # noqa: E402
from fetch_enso_ext import read_extended                 # noqa: E402

MDIR = os.path.join(HERE, "data", "models")


def main():
    tag = sys.argv[1]
    jid = sys.argv[2]
    centre = sys.argv[3] if len(sys.argv) > 3 else ""
    system = sys.argv[4] if len(sys.argv) > 4 else ""
    out = os.path.join(MDIR, tag, "sst_extended.grib")
    npz = os.path.join(MDIR, tag, "sst_extended.npz")
    if os.path.exists(npz):
        print("already have %s" % npz, flush=True)
        return
    c = cds_direct.CDSDirect()
    for i in range(720):                      # 6 h
        st = c.job_status(jid)
        print("[%s] job %s %s" % (time.strftime("%H:%M:%S"), jid[:12], st),
              flush=True)
        if st == "successful":
            c.download_job(jid, out)
            print("downloaded %.1f MB" % (os.path.getsize(out) / 1e6),
                  flush=True)
            break
        if st in ("failed", "error", "gone", "rejected"):
            print("job %s" % st, flush=True)
            return
        time.sleep(30)
    else:
        print("gave up waiting", flush=True)
        return
    got = read_extended(out)
    if not got:
        print("could not read the GRIB", flush=True)
        return
    months, idx, trop = got
    np.savez_compressed(
        npz,
        months=np.array(["%04d-%02d" % ym for ym in months]),
        basin=np.array([[[mem[n] for mem in idx[ym]] for n in BASIN_NAMES]
                        for ym in months]),
        tropical=np.array([trop[ym] for ym in months]))
    for i, ym in enumerate(months):
        print("  %04d-%02d  Nino3.4 %.2f C (mean of %d members)" %
              (ym[0], ym[1], np.mean([m["Nino 3.4"] for m in idx[ym]]) - 273.15,
               len(idx[ym])), flush=True)
    print("saved %s" % npz, flush=True)
    # rebuild the plumes and the site with the longer range
    for cmd in ("python3 -u plot_enso.py", "python3 build_registry.py",
                "python3 build_site.py"):
        print(">> %s" % cmd, flush=True)
        os.system("cd %s && %s" % (HERE, cmd))


if __name__ == "__main__":
    main()
