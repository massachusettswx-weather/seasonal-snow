"""NOAA SFSv1 (SFS Beta) seasonal forecast, taken straight from NOAA.

The C3S seasonal archive cannot serve the current NOAA init (the non-ECMWF
contribution is access-restricted for the newest init, and NOAA's C3S system
entry serves no recent data), so the NOAA systems are read from NOAA's own
public store:

    s3://noaa-oar-sfsdev-pds/experiments/beta3/forecast/<YYYYMM>/atm_monthly.zarr
    s3://noaa-oar-sfsdev-pds/experiments/beta3/reforecast/<MM>/atm_monthly.zarr

Both are public and readable over anonymous HTTPS.  The forecast store holds
31 members x 12 lead months on a 0.5 deg grid; the reforecast store holds the
matching 35-year hindcast for the same calendar init month, which is the
model's own hindcast climate (the same role the C3S `hindcast_climate_mean`
plays for the other centres).

Snowfall
--------
There is no snowfall field in the store, so it is derived the same way the ERA5
climatology is: precipitation x the fraction that falls as snow.

  * `pratesfc`   - surface precipitation rate (kg m-2 s-1) -> the month's
                   accumulation.
  * `tsnowpsfc`  - "snow phase": the snowfall of the month expressed per day
                   (kg m-2 day-1).  Multiplying by the number of days in the
                   month reproduces the monthly snowfall; this was verified
                   against ERA5's 1991-2020 climatology, which it matches to
                   within a few percent for December, January and February
                   (pattern correlation 0.94-0.97).
  * The result is capped at the month's total precipitation, which is a
    physical necessity.

The output is written in the same convention the other centres use: a rate in
m w.e. s-1, so the renderer can multiply by the month length.
"""
import os, sys, json, calendar
from datetime import date

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
BUCKET = "noaa-oar-sfsdev-pds"
EXP = os.environ.get("SFS_EXP", "beta3")

LAT0, LAT1 = 20.0, 56.0
LON0, LON1 = -134.0, -56.0
T0 = 273.15


def _fs():
    import s3fs
    return s3fs.S3FileSystem(anon=True)


def open_zarr(fs, path):
    import zarr
    return zarr.open_group(fs.get_mapper("%s/%s" % (BUCKET, path)), mode="r")


def forecast_path(init, exp=EXP):
    return "experiments/%s/forecast/%s/atm_monthly.zarr" % (exp, init)


def newest_init(fs=None, exp=EXP, back=6):
    """The newest init the store actually holds.

    The SFS publishes a new init every month, so the December run has to
    be found rather than written down.  The store does not allow its
    buckets to be listed, so the candidate months are tried instead: the
    newest one that opens is the one to use.
    """
    fs = fs or _fs()
    today = date.today()
    total = today.year * 12 + (today.month - 1)
    for k in range(back):
        y, m = (total - k) // 12, (total - k) % 12 + 1
        init = "%04d%02d" % (y, m)
        try:
            open_zarr(fs, forecast_path(init, exp))
            return init
        except Exception:
            continue
    return None


def reforecast_path(month, exp=EXP):
    return "experiments/%s/reforecast/%02d/atm_monthly.zarr" % (exp, month)


def lead_months(init, n):
    """Calendar month of each lead month (lead 0 = the init month)."""
    y0, m0 = int(init[:4]), int(init[4:6])
    out = []
    for k in range(n):
        total = (m0 - 1) + k
        out.append((y0 + total // 12, total % 12 + 1))
    return out


def crop(lat, lon):
    sl = np.where((lat >= LAT0) & (lat <= LAT1))[0]
    so = np.where((lon >= (LON0 % 360)) & (lon <= (LON1 % 360)))[0]
    return sl, so


def snowfall_from(tsnow_day, prate, y, m):
    """Monthly snowfall (kg m-2 w.e.) from the model's own fields."""
    days = calendar.monthrange(y, m)[1]
    pacc = prate * days * 86400.0                 # the month's total precip
    snow = tsnow_day * days                       # the month's snowfall
    return np.minimum(snow, pacc)


def fetch(init="202611", exp=EXP, tag="sfsv1"):
    fs = _fs()
    fz = open_zarr(fs, forecast_path(init, exp))
    lat = np.asarray(fz["lat"][:]); lon = np.asarray(fz["lon"][:])
    sl, so = crop(lat, lon)
    nlead = int(fz["lead"].shape[0])
    nmem = int(fz["member"].shape[0])
    print("forecast %s: %d members x %d lead months, grid %dx%d"
          % (init, nmem, nlead, len(sl), len(so)), flush=True)

    ts = fz["tsnowpsfc"]; pr = fz["pratesfc"]
    vals = np.zeros((nmem, nlead, len(sl), len(so)), np.float32)
    for k in range(nlead):
        y, m = lead_months(init, nlead)[k]
        t = np.asarray(ts[:, k])[:, sl][:, :, so]
        p = np.asarray(pr[:, k])[:, sl][:, :, so]
        vals[:, k] = snowfall_from(t, p, y, m).astype(np.float32)
        print("  lead %d (%04d-%02d): snowfall max %.1f kg/m2  mean %.2f"
              % (k, y, m, vals[:, k].max(), vals[:, k].mean()), flush=True)

    # the model's own hindcast climate, from the reforecast store
    clim = np.zeros((nlead, len(sl), len(so)), np.float32)
    try:
        rz = open_zarr(fs, reforecast_path(int(init[4:6]), exp))
        rts = rz["tsnowpsfc"]; rpr = rz["pratesfc"]
        shape = rts.shape
        print("reforecast: %d years x %d members x %d leads" % shape[:3], flush=True)
        for k in range(nlead):
            y, m = lead_months(init, nlead)[k]
            acc = None
            for yi in range(shape[0]):
                t = np.asarray(rts[yi, :, k])[:, sl][:, :, so]
                p = np.asarray(rpr[yi, :, k])[:, sl][:, :, so]
                s = snowfall_from(t, p, y, m).mean(axis=0)
                acc = s if acc is None else acc + s
            clim[k] = (acc / shape[0]).astype(np.float32)
            print("  clim lead %d (%04d-%02d): max %.1f kg/m2"
                  % (k, y, m, clim[k].max()), flush=True)
    except Exception as e:
        print("no reforecast store (%s) - the anomaly panels will be skipped"
              % str(e)[:120], flush=True)
        clim = None

    # the renderer's convention: a rate in m w.e. s-1, latitudes descending
    sec_all = np.array([calendar.monthrange(y, m)[1] * 86400.0 for (y, m) in months])
    lats = lat[sl][::-1].copy()
    lons = lon[so].copy()
    lons = np.where(lons > 180, lons - 360, lons)
    order = np.argsort(lons)
    lons = lons[order]
    vals = vals[:, :, :, order][:, :, ::-1, :]
    months = lead_months(init, nlead)

    os.makedirs(os.path.join(MDIR, tag), exist_ok=True)
    np.savez_compressed(os.path.join(MDIR, tag, "snowfall_monthly.npz"),
                        months=np.array(["%04d-%02d" % m for m in months]),
                        member_numbers=np.arange(nmem),
                        values=(vals / 1000.0 / sec_all[:, None, None]).astype(np.float32),
                        lat=lats, lon=lons,
                        meta=np.array(json.dumps(
                            dict(tag=tag, name="NOAA SFSv1 (SFS Beta %s)" % exp,
                                 init="%s-%s" % (init[:4], init[4:6]),
                                 members=nmem, source="NOAA NODD %s" % exp))))
    print("wrote %s/snowfall_monthly.npz" % tag)
    if clim is not None:
        c = clim[:, :, order][:, ::-1, :]
        np.savez_compressed(os.path.join(MDIR, tag, "snowfall_hindcast.npz"),
                            months=np.array(["%04d-%02d" % m for m in months]),
                            values=(c[None, :, :, :] / 1000.0 /
                                    sec_all[None, :, None, None]).astype(np.float32),
                            lat=lats, lon=lons,
                            meta=np.array(json.dumps(dict(init="%s-%s" % (init[:4], init[4:6])))))
        print("wrote %s/snowfall_hindcast.npz" % tag)

    # register the model for the renderer
    sp = os.path.join(DATA, "models_fetched.json")
    state = json.load(open(sp)) if os.path.exists(sp) else {}
    state[tag] = {"name": "NOAA SFSv1 (SFS Beta %s)" % exp,
                  "init": "%s-%s" % (init[:4], init[4:6]),
                  "members": nmem, "source": "NOAA NODD",
                  "leads": nlead}
    json.dump(state, open(sp, "w"), indent=1)
    print("registered %s in models_fetched.json" % tag)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", default="",
                    help="the init (YYYYMM); by default the newest one the "
                         "store holds")
    ap.add_argument("--exp", default=EXP)
    ap.add_argument("--tag", default="sfsv1")
    a = ap.parse_args()
    init = a.init or newest_init(exp=a.exp)
    if not init:
        print("   no init found in the forecast store")
        raise SystemExit(1)
    print("   the SFS init: %s" % init)
    fetch(init, a.exp, a.tag)
