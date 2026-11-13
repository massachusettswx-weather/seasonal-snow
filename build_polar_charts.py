"""Rebuild every polar-cap time-height section that has data behind it.

The publisher calls this after the data changes.  The systems are not listed
here: they are whatever is in data/polar_model_z.json (the seasonal runs and
the sub-seasonal guidance) plus the EC46 in data/polar_ec46_z.json.  A system
with no series is not drawn - plot_polar_cap.py removes the chart it would
have drawn rather than leave one with no data behind it.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# the display name of every system, the same wording the registry uses
LABELS = {
    "ecmwf-seas5": "ECMWF SEAS5",
    "ec46": "ECMWF EC46",
    "gefsv12": "NOAA GEFSv12",
    "ukmo-gloseas6": "UKMO GloSeas6-GC5.1",
    "meteo-france-s9": "METFR System 9",
    "cmcc-sps4": "CMCC SPS4",
    "dwd-gcfs2": "DWD GCFS2.2",
    "eccc-cansips": "ECCC canSIPS",
    "eccc-canesm5": "ECCC CanESM5",
    "eccc-gem5": "ECCC GEM5.2",
    "jma-jra3": "JMA CPS4",
    "bom-access-s2": "BOM ACCESS-S2",
}


def tags():
    out = []
    p = os.path.join(HERE, "data", "polar_model_z.json")
    if os.path.exists(p):
        try:
            for k in json.load(open(p)):
                if k not in out:
                    out.append(k)
        except Exception as e:
            print("   the polar series file could not be read: %s" % str(e)[:90])
    # the EC46 is kept in its own file
    if os.path.exists(os.path.join(HERE, "data", "polar_ec46_z.json")):
        if "ec46" not in out:
            out.append("ec46")
    return out


def main():
    for t in tags():
        label = LABELS.get(t, t.replace("-", " ").title())
        r = subprocess.run([sys.executable, "-u", "plot_polar_cap.py", t, label],
                           cwd=HERE, capture_output=True, text=True)
        out = (r.stdout or "").strip().splitlines()
        for line in out[-3:]:
            print("   %s" % line)
        if r.returncode != 0:
            print("   the %s section failed: %s"
                  % (t, (r.stderr or "").strip().splitlines()[-1][:160]))
        # the same section split into the North Pacific and the North
        # Atlantic, when the sector means are on disk
        r2 = subprocess.run([sys.executable, "-u", "plot_polar_sectors.py",
                             t, label], cwd=HERE, capture_output=True,
                            text=True)
        out2 = (r2.stdout or "").strip().splitlines()
        for line in out2[-2:]:
            print("   %s" % line)


if __name__ == "__main__":
    main()
