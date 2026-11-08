"""Decode a seasonal *subdaily* (original-grid) u10 GRIB into per-member
zonal-mean series at 60N and over the Northern Hemisphere.

This is the shared decoder for every centre.  The layout of the C3S subdaily
product differs from centre to centre, so the reader is deliberately generic:

  * the member id comes from `perturbationNumber` when the centre numbers its
    perturbations, otherwise from `number` (the GRIB ensemble member);
  * the valid time is `dataDate + step`, NOT the step alone - UKMO perturbs the
    member start dates, so the same lead time maps to different valid dates for
    different members;
  * records are grouped by valid date so the true member count per day is
    recovered rather than assumed.

Everything is reduced on the way in, so a 2 GB download becomes a few hundred
kB of .npz.
"""
import os, json
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import eccodes


def _g(gid, key, default=None):
    try:
        return eccodes.codes_get(gid, key)
    except Exception:
        return default


def zonal_mean(v, lats):
    """Area-weighted zonal mean over the Northern Hemisphere only.

    Same convention as the reference ECMWF pipeline: average each latitude
    circle over longitude first, then weight those by cos(latitude).
    """
    lats = np.asarray(lats, float)
    m = lats >= -0.001
    ll = lats[m]
    zonal = v[m, :].mean(axis=1)
    w = np.cos(np.deg2rad(ll))
    return float((zonal * w).sum() / w.sum())


def point_mean(v, lats, lat0=60.0):
    """Mean over the latitude band containing lat0 (two rows on a 1 deg grid)."""
    m = np.abs(lats - lat0) <= 0.5
    return float(v[m, :].mean()) if m.any() else np.nan


def read_daily_u10(path):
    """-> (records, members)

    records: list of dicts with valid (datetime.date), member (int), s60, sNH
    members: sorted list of member ids seen
    """
    recs = []
    members = set()
    raw = []
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
                lats = np.unique(la)[::-1]
                lons = np.unique(lo)
                if v.size != lats.size * lons.size:
                    continue
                v = v.reshape(len(lats), len(lons))

                dd = _g(gid, "dataDate")
                if dd is None:
                    continue
                dd = int(dd)
                st = int(_g(gid, "step", 0) or 0)
                valid = date(dd // 10000, (dd // 100) % 100, dd % 100) + timedelta(hours=st)

                pn = _g(gid, "perturbationNumber")
                num = _g(gid, "number")
                pn = int(pn) if pn is not None else 0
                num = int(num) if num is not None else 0

                recs.append(dict(valid=valid, member=0, pn=pn, num=num,
                                 s60=point_mean(v, lats, 60.0),
                                 sNH=zonal_mean(v, lats)))
                raw.append((pn, num))
            except Exception:
                pass
            finally:
                eccodes.codes_release(gid)

    # `number` (the GRIB ensemble member) and `perturbationNumber` are identical
    # for every C3S seasonal centre we have seen.  Prefer `number`; fall back to
    # the perturbation number for centres that leave `number` at zero.
    use_num = len({n for _, n in raw}) > 1
    key = "num" if use_num else "pn"
    for r in recs:
        r["member"] = r[key]
    members = sorted({r["member"] for r in recs})
    return recs, members


def build_matrix(recs, members):
    """-> (dates, m60[members, dates], mnh[members, dates])"""
    by_date = defaultdict(dict)
    for r in recs:
        # a member may contribute several records to one valid date (different
        # steps that land on the same day); average them.
        by_date[r["valid"]].setdefault(r["member"], []).append(r)
    dates = sorted(by_date)
    idx = {m: i for i, m in enumerate(members)}
    m60 = np.full((len(members), len(dates)), np.nan)
    mnh = np.full((len(members), len(dates)), np.nan)
    for j, d in enumerate(dates):
        for m, rows in by_date[d].items():
            i = idx.get(m)
            if i is None:
                continue
            m60[i, j] = float(np.nanmean([r["s60"] for r in rows]))
            mnh[i, j] = float(np.nanmean([r["sNH"] for r in rows]))
    return dates, m60, mnh


def save_npz(path, dates, m60, mnh, members, meta=None):
    import json
    np.savez_compressed(
        path,
        dates=np.array([d.isoformat() for d in dates]),
        members60=m60,
        members_nh=mnh,
        member_numbers=np.array(members),
        meta=np.array(json.dumps(meta or {})),
    )


def load_npz(path):
    d = np.load(path, allow_pickle=True)
    dates = [date.fromisoformat(str(x)) for x in d["dates"]]
    meta = {}
    try:
        meta = json.loads(str(d["meta"]))
    except Exception:
        pass
    return dates, d["members60"], d["members_nh"], list(d["member_numbers"]), meta
