"""Build the ECCC canSIPS product - the two ECCC systems pooled.

canSIPS is the Environment Canada seasonal prediction system: CanESM5.1p1bc
and GEM5.2-NEMO are run side by side, twenty members each, and the official
product is the forty-member multi-model ensemble.  Rather than show the two
systems separately, this writes their pooled product into
data/models/eccc-cansips/ in exactly the same file formats the renderers
already read, so nothing downstream has to know it is a merge:

  - the forecast and the hindcast climate are the two GRIB files
    concatenated, so the ensemble mean is over all forty members and the
    climate is the mean of the two systems' own climates;
  - the daily wind series has the two sets of member traces stacked;
  - the ENSO plume has the two sets of member values stacked, so the
    spread it shows is the whole forty-member ensemble.

Both systems run on the same 1 degree grid, the same lead months and the
same valid dates, so nothing has to be interpolated or trimmed.  The script
is idempotent and is run before every render, because the pool keeps
refreshing the two source systems.

Run:  python3 build_cansips.py
"""
import os
import json
import shutil

import numpy as np
import init_info

HERE = os.path.dirname(os.path.abspath(__file__))
MDIR = os.path.join(HERE, "data", "models")
SRC = ["eccc-canesm5", "eccc-gem5"]
DST = "eccc-cansips"
NAME = "ECCC canSIPS"


def log(msg):
    print("   %s" % msg, flush=True)


def concat_grib(dst, paths):
    """Concatenate GRIB files.  Each message is self-delimiting, so the
    result is simply one file holding every member of every system."""
    with open(dst, "wb") as out:
        for p in paths:
            if not os.path.exists(p):
                return False
            with open(p, "rb") as f:
                shutil.copyfileobj(f, out, 1024 * 1024)
    return True


def merge_u10(dst, paths):
    """Stack the member traces of the two systems into one array."""
    ds = [np.load(p, allow_pickle=True) for p in paths]
    dates = ds[0]["dates"]
    for d in ds:
        if len(d["dates"]) != len(dates) or \
           not np.array_equal(d["dates"], dates):
            return False, None
    m60 = np.concatenate([d["members60"] for d in ds], axis=0)
    mnh = np.concatenate([d["members_nh"] for d in ds], axis=0)
    n = m60.shape[0]
    np.savez(dst, dates=dates, members60=m60, members_nh=mnh,
             member_numbers=np.arange(1, n + 1),
             meta=json.dumps({"tag": DST, "centre": "eccc",
                              "system": "cansips", "init": src_init(),
                              "merged_from": SRC}))
    return True, n


def src_init():
    """The init the two pooled systems are on.

    The canSIPS ensemble is whatever the ECCC's own two systems are on,
    so the label follows them and not a constant.
    """
    st = {}
    sp = os.path.join(HERE, "data", "models_fetched.json")
    if os.path.exists(sp):
        try:
            st = json.load(open(sp))
        except Exception:
            st = {}
    inits = [st.get(t, {}).get("init") for t in SRC if st.get(t, {}).get("init")]
    if not inits:
        return init_info.newest_init("ecmwf-seas5")
    return max(inits)


def merge_enso(dst, paths):
    """Stack the member values of the two systems, month by month."""
    es = [json.load(open(p)) for p in paths]
    months = es[0]["months"]
    for e in es:
        if e["months"] != months:
            # only the months both systems carry
            months = [m for m in months if m in e["months"]]
    if not months:
        return False, 0
    out = {"kind": es[0].get("kind", "c3s-sst"), "init": es[0].get("init"),
           "months": months,
           "basins": es[0].get("basins", ["Nino 3.4", "Nino 3", "Nino 4",
                                          "Nino 1+2"])}
    series = {}
    n = 0
    for b in out["basins"]:
        per_month = []
        for m in months:
            vals = []
            for e in es:
                if b not in e.get("series", {}):
                    continue
                k = e["months"].index(m)
                try:
                    vals.extend(list(e["series"][b][k]))
                except Exception:
                    pass
            n = max(n, len(vals))
            per_month.append(vals)
        series[b] = per_month
    out["series"] = series
    trop = []
    for m in months:
        vals = []
        for e in es:
            k = e["months"].index(m)
            try:
                vals.extend(list(e["tropical"][k]))
            except Exception:
                pass
        trop.append(vals)
    out["tropical"] = trop
    json.dump(out, open(dst, "w"))
    return True, n


def merge_ext(dst, paths):
    """Stack the lead-month-seven accumulations of the two systems."""
    ds = [np.load(p, allow_pickle=True) for p in paths]
    months = [str(m) for m in ds[0]["months"]]
    for d in ds:
        if [str(m) for m in d["months"]] != months:
            return False
    acc = np.concatenate([np.asarray(d["acc"], float) for d in ds], axis=0)
    nd = np.asarray(ds[0]["ndays"]) if "ndays" in ds[0].files else None
    kw = {"months": np.array(months), "lat": np.asarray(ds[0]["lat"], float),
          "lon": np.asarray(ds[0]["lon"], float), "acc": acc}
    if nd is not None:
        kw["ndays"] = nd
    np.savez(dst, **kw)
    return True


def main():
    d = os.path.join(MDIR, DST)
    srcs = [os.path.join(MDIR, s) for s in SRC]
    for s in srcs:
        if not os.path.isdir(s):
            print("   the canSIPS sources are not all there - skipped")
            return
    os.makedirs(d, exist_ok=True)

    # the forecast and the climate: one file holding every member
    for name in ("snowfall_monthly", "snowfall_hindcast"):
        ps = [os.path.join(s, name + ".grib") for s in srcs]
        if not all(os.path.exists(p) for p in ps):
            log("%s: not all the source files are there" % name)
            continue
        concat_grib(os.path.join(d, name + ".grib"), ps)
        log("%s: the two systems' members in one file" % name)

    # the lead month past the sixth, when both systems have it
    ps = [os.path.join(s, "snowfall_ext.npz") for s in srcs]
    if all(os.path.exists(p) for p in ps):
        try:
            if merge_ext(os.path.join(d, "snowfall_ext.npz"), ps):
                log("snowfall_ext: the two systems' accumulations pooled")
        except Exception as e:
            log("snowfall_ext: skipped (%s)" % e)

    # the daily wind
    ps = [os.path.join(s, "u10_daily.npz") for s in srcs]
    if all(os.path.exists(p) for p in ps):
        ok, n = merge_u10(os.path.join(d, "u10_daily.npz"), ps)
        if ok:
            log("u10_daily: %d member traces pooled" % n)

    # the ENSO plume
    ps = [os.path.join(s, "enso.json") for s in srcs]
    if all(os.path.exists(p) for p in ps):
        ok, n = merge_enso(os.path.join(d, "enso.json"), ps)
        if ok:
            log("enso: %d members pooled over %d months"
                % (n, len(json.load(open(os.path.join(d, "enso.json")))["months"])))

    # the sea surface temperature the plume is built on
    ps = [os.path.join(s, "sst_monthly.grib") for s in srcs]
    if all(os.path.exists(p) for p in ps):
        concat_grib(os.path.join(d, "sst_monthly.grib"), ps)

    # register it
    sp = os.path.join(HERE, "data", "models_fetched.json")
    st = json.load(open(sp))
    members = 0
    up = os.path.join(d, "u10_daily.npz")
    if os.path.exists(up):
        members = int(np.load(up, allow_pickle=True)["members60"].shape[0])
    ep = os.path.join(d, "enso.json")
    if os.path.exists(ep):
        e = json.load(open(ep))
        members = max(members, len(e["series"]["Nino 3.4"][0]))
    st[DST] = {
        "name": NAME,
        "centre": "eccc",
        "system": "cansips",
        "init": src_init(),
        "members": members,
        "leads": 7,
        "merged_from": SRC,
        "note": "the official canSIPS multi-model ensemble - "
                "CanESM5.1p1bc and GEM5.2-NEMO pooled, twenty members each. "
                "Both systems run on the same grid and the same lead months, "
                "so the mean is taken over all forty members.",
    }
    json.dump(st, open(sp, "w"), indent=1, sort_keys=True)
    log("registered %s with %d members" % (DST, members))


if __name__ == "__main__":
    main()
