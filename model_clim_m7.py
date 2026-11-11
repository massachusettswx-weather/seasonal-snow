"""Rebuild the ECMWF lead-month-7 model-climate curve.

The CDS publishes the ECMWF model-climate mean (HCMEAN) only as monthly
values, for lead months 1-6.  Lead month 7 is not published at all, so the
SPV chart's model-climate curve needs it reconstructed from the model's OWN
past runs: for each of the last ten inits, the daily 60N/10 hPa zonal-mean
zonal wind at lead month 7 was pulled from the sub-daily seasonal product
and stored in

    data/m7_<YYYYMM>.npz     with  m60 (60N daily series), mnh (NH series)
                             and   steps (the leadtime_hour of each day)

The model climate for month 7 is then the mean of those ten years, day by
day:

    clim60 = mean over the ten inits of m60
    clim_nh = mean over the ten inits of mnh

and the result is written to

    data/model_clim_m7_month<MM>.npz    with clim60, clim_nh, nyears

This script only rebuilds that curve from the per-init files already on
disk.  It does NOT fetch anything - the pulls are the slow, queue-limited
part and they are done by `fetch_spv_ext.py` / the daily puller.  If a new
init has been pulled, run this again to fold it in.

    python3 model_clim_m7.py            # rebuild every month it can
    python3 model_clim_m7.py --month 11 # just one month
"""
import os
import re
import sys
import glob
import argparse
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def inits_for(month):
    """The per-init files that belong to this init month."""
    out = []
    for p in sorted(glob.glob(os.path.join(DATA, "m7_20*.npz"))):
        m = re.search(r"m7_(\d{4})(\d{2})\.npz$", p)
        if m and int(m.group(2)) == month:
            out.append(p)
    return out


def build(month, out_path=None):
    """-> (clim60, clim_nh, nyears) or None if there is nothing to build."""
    files = inits_for(month)
    if not files:
        return None
    m60, mnh, steps = [], [], None
    for p in files:
        d = np.load(p, allow_pickle=True)
        m60.append(np.asarray(d["m60"], float))
        mnh.append(np.asarray(d["mnh"], float))
        s = np.asarray(d["steps"], int)
        if steps is None:
            steps = s
        elif len(s) != len(steps):
            # the series have to have the same number of days, otherwise the
            # mean is mixing different calendar months
            raise SystemExit("the per-init files have different lengths: %s" % p)
        # The steps themselves DO differ between inits - some inits were on
        # the 1st of the month and some on the 16th, so the same lead month
        # sits at a different leadtime_hour.  The array index is the day
        # within the lead month, which is what has to line up, so the steps
        # are kept for reference but not used to align.
    clim60 = np.mean(np.array(m60), axis=0)
    clim_nh = np.mean(np.array(mnh), axis=0)
    if out_path is None:
        out_path = os.path.join(DATA, "model_clim_m7_month%02d.npz" % month)
    np.savez_compressed(out_path, clim60=clim60, clim_nh=clim_nh,
                        nyears=len(files))
    print("   month %02d: %d init(s) -> %s (clim60 mean %.3f m/s)"
          % (month, len(files), os.path.basename(out_path), float(clim60.mean())))
    return clim60, clim_nh, len(files)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", type=int, default=None,
                    help="only this init month (1-12)")
    a = ap.parse_args()

    months = [a.month] if a.month else list(range(1, 13))
    built = 0
    for m in months:
        r = build(m)
        if r is not None:
            built += 1
    if not built:
        print("   nothing to build - no data/m7_<YYYYMM>.npz files found")
        return
    print("   %d month(s) rebuilt" % built)


if __name__ == "__main__":
    main()
