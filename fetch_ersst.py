"""The analysis segment of the ENSO plumes from NOAA ERSST v6.

ERSST is the dataset NOAA/CPC builds the ONI and the RONI from, so the
observed end of every plume comes from the same source as the official
indices (which are drawn on top of the Nino 3.4 charts as a reference).

For every month it gives
  * the area-weighted mean SST of the four ENSO basins,
  * the tropical-mean (20S-20N, all longitudes) SST,
both as absolute values and as anomalies against the 1991-2020 climatology
of the same calendar month.

    python3 fetch_ersst.py
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SRC = os.path.join(DATA, "oni", "ersst_v6_sst.mnmean.nc")
OUT = os.path.join(DATA, "ersst_enso.npz")
sys.path.insert(0, HERE)
from enso_common import BASINS, BASIN_NAMES  # noqa: E402


def basin_mean(lat, lon, field):
    out = {}
    ok = np.isfinite(field)
    for name, la0, la1, lo0, lo1 in BASINS:
        m = (lat[:, None] >= min(la0, la1)) & (lat[:, None] <= max(la0, la1)) & \
            (lon[None, :] >= min(lo0, lo1)) & (lon[None, :] <= max(lo0, lo1))
        if not m.any():
            out[name] = np.nan
            continue
        w = np.broadcast_to(np.cos(np.deg2rad(lat[:, None])), field.shape)
        ww = w * m * ok
        tot = ww.sum()
        out[name] = float(np.sum(np.where(ok, field, 0.0) * ww) / tot) if tot > 0 else np.nan
    return out


def tropical_mean(lat, lon, field):
    ok = np.isfinite(field)
    band = (lat[:, None] >= -20.0) & (lat[:, None] <= 20.0)
    w = np.broadcast_to(np.cos(np.deg2rad(lat[:, None])), field.shape) * band * ok
    tot = w.sum()
    return float(np.sum(np.where(ok, field, 0.0) * w) / tot) if tot > 0 else np.nan


def main():
    if not os.path.exists(SRC):
        print("missing %s" % SRC, flush=True)
        return
    import h5netcdf
    import datetime
    with h5netcdf.File(SRC, "r") as f:
        sst = np.asarray(f["sst"][:], float)
        lat = np.asarray(f["lat"][:], float)
        lon = np.asarray(f["lon"][:], float)
        t = np.asarray(f["time"][:], float)
    epoch = datetime.date(1800, 1, 1)
    first = epoch + datetime.timedelta(days=int(t[0]))
    # the monthly stamps run from 1850-01
    y, m = first.year, first.month
    months = []
    for i in range(len(t)):
        months.append("%04d-%02d" % (y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    print("ERSST v6: %d months, %s .. %s" % (len(months), months[0], months[-1]),
          flush=True)

    # the land is filled with a huge negative number
    sst = np.where(sst < -50.0, np.nan, sst)

    bas = np.zeros((len(months), len(BASIN_NAMES)))
    tm = np.zeros(len(months))
    for i in range(sst.shape[0]):
        bm = basin_mean(lat, lon, sst[i])
        bas[i] = [bm[n] for n in BASIN_NAMES]
        tm[i] = tropical_mean(lat, lon, sst[i])

    sel = [i for i, mm in enumerate(months) if 1991 <= int(mm[:4]) <= 2020]
    clim_b = np.zeros((12, len(BASIN_NAMES)))
    clim_t = np.zeros(12)
    for mm in range(1, 13):
        idx = [i for i in sel if int(months[i][5:7]) == mm]
        clim_b[mm - 1] = np.mean(bas[idx], axis=0)
        clim_t[mm - 1] = np.mean(tm[idx])
    cal = np.array([int(mm[5:7]) - 1 for mm in months])
    anom_b = bas - clim_b[cal]
    anom_t = tm - clim_t[cal]

    # the relative index: the basin anomaly minus the tropical mean, rescaled
    # so its spread matches the absolute index (CPC's renormalisation)
    rel = anom_b[:, 0] - anom_t
    k = float(np.std(anom_b[:, 0]) / np.std(rel))

    np.savez_compressed(OUT, months=np.array(months), basin=bas, tm=tm,
                        basin_anom=anom_b, tm_anom=anom_t,
                        basin_clim=clim_b, tm_clim=clim_t,
                        basins=np.array(BASIN_NAMES), k=k)
    print("saved %s" % os.path.relpath(OUT, HERE), flush=True)

    # how close is this to the official NOAA/CPC ONI and RONI?
    p = os.path.join(DATA, "oni", "indices.json")
    if os.path.exists(p):
        cpc = json.load(open(p))
        idx = {m: i for i, m in enumerate(months)}
        for key, series in (("oni_monthly", "oni"), ("roni_monthly", "roni")):
            ref = cpc.get(key, {})
            ours = []
            for m, v in ref.items():
                if m not in idx:
                    continue
                if series == "oni":
                    i = idx[m]
                    if i == 0 or i == len(months) - 1:
                        continue
                    o = float(np.mean(anom_b[i - 1:i + 2, 0]))
                else:
                    o = float(rel[idx[m]] * k)
                ours.append((m, o - float(v)))
            if ours:
                d = np.array([x[1] for x in ours])
                print("  ERSST %s vs CPC %s: mean %+.3f  max|d| %.3f  (n=%d)" %
                      (series, key, d.mean(), np.abs(d).max(), len(d)), flush=True)
                worst = sorted(ours, key=lambda x: -abs(x[1]))[:3]
                print("     largest differences:", ", ".join(
                    "%s %+.2f" % (m, v) for m, v in worst), flush=True)

    print("  rescaling factor k = %.3f" % k, flush=True)
    print("  basin climatology (deg C):", flush=True)
    for i, n in enumerate(BASIN_NAMES):
        print("    %-9s %s" % (n, " ".join("%.2f" % (x - 273.15)
                                         for x in clim_b[:, i])), flush=True)
    print("    tropical  %s" % " ".join("%.3f" % (x - 273.15)
                                        for x in clim_t), flush=True)
    print("  last 8 months (basin anomalies, deg C):", flush=True)
    for i in range(max(0, len(months) - 8), len(months)):
        print("    %s  %s | tropical %+.3f" % (
            months[i], " ".join("%+.2f" % x for x in anom_b[i]), anom_t[i]),
            flush=True)


if __name__ == "__main__":
    main()
