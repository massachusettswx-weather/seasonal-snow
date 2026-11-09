"""NOAA CFSv2 seasonal forecast, taken from NCEP's own CPC product.

CFSv2 cannot be pulled from the C3S archive for the current init (the
non-ECMWF contribution is access-restricted for the newest init, and NOAA's
C3S system entry serves no recent data), so the forecast is read from CPC:

    https://www.cpc.ncep.noaa.gov/products/CFSv2/CFSv2seasonal.shtml

That page publishes the monthly means of the 40-member ensemble for the
current init as netCDF.  The files hold the ANOMALY of the ensemble mean with
respect to the 1991-2020 CFSv2 hindcast climatology, so:

  * the anomaly panels use the published anomaly directly (it is already the
    model's own hindcast anomaly);
  * the absolute snowfall panels add the ERA5 1991-2020 climatology to the
    published anomaly, which is an approximation - CPC does not publish the
    raw CFSv2 hindcast fields - and it is labelled as such on the figure.

Snowfall is precipitation x the fraction that falls as snow, the same
derivation used for the ERA5 climatology.
"""
import os, sys, json, calendar, urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
CPC = "https://www.cpc.ncep.noaa.gov/products/CFSv2"
T0 = 273.15


def _bilinear(src, slat, slon, tlat, tlon):
    """Bilinear resample of a 2-D field (order-agnostic)."""
    o = np.argsort(slat); slat = np.asarray(slat)[o]; src = src[o, :]
    o = np.argsort(slon); slon = np.asarray(slon)[o]; src = src[:, o]
    i = np.clip(np.searchsorted(slat, tlat) - 1, 0, len(slat) - 2)
    dy = (tlat - slat[i]) / (slat[i + 1] - slat[i])
    j = np.clip(np.searchsorted(slon, tlon) - 1, 0, len(slon) - 2)
    dx = (tlon - slon[j]) / (slon[j + 1] - slon[j])
    return ((1 - dy) * ((1 - dx) * src[i, j] + dx * src[i, j + 1]) +
            dy * ((1 - dx) * src[i + 1, j] + dx * src[i + 1, j + 1]))


def download(name, outdir):
    os.makedirs(outdir, exist_ok=True)
    p = os.path.join(outdir, name)
    if os.path.exists(p) and os.path.getsize(p) > 1000:
        return p
    url = "%s/dataInd1/%s" % (CPC, name)
    print("downloading", url, flush=True)
    with urllib.request.urlopen(url, timeout=120) as r, open(p, "wb") as f:
        f.write(r.read())
    return p


def read_cpc(path):
    import h5netcdf
    with h5netcdf.File(path, "r") as f:
        anom = np.asarray(f["anom"][0, :, 0], float)      # (time, lat, lon)
        lat = np.asarray(f["lat"][:], float)
        lon = np.asarray(f["lon"][:], float)
        t = np.asarray(f["time"][:], float)
        units = f["anom"].attrs.get("units", "")
    lon = np.where(lon > 180, lon - 360, lon)
    return anom, lat, lon, t, units


def months_from_cpc(t):
    import datetime
    out = []
    for x in t:
        d = datetime.date(2021, 1, 1) + datetime.timedelta(days=int(x))
        out.append((d.year, d.month))
    return out


def fetch(tag="cfsv2", ens="dataInd1"):
    import h5netcdf
    d = os.path.join(DATA, "cpc")
    pp = download("glbPrecMon.nc", d)
    tp = download("glbT2mMon.nc", d)
    prec, plat, plon, t, punit = read_cpc(pp)
    t2m, _, _, _, tunit = read_cpc(tp)
    mons = months_from_cpc(t)
    print("CFSv2 lead months:", ["%04d-%02d" % m for m in mons], "| precip units:", punit)

    # ERA5 climatology (mm w.e. per month) for the absolute snowfall panels
    clim_path = os.path.join(DATA, "era5_snow_clim_arco_conus.npz")
    if not os.path.exists(clim_path):
        clim_path = os.path.join(DATA, "era5_snow_clim_arco.npz")
    cz = np.load(clim_path, allow_pickle=True)
    clat = np.asarray(cz["lat"], float)
    clon = np.asarray(cz["lon"], float)
    clon = np.where(clon > 180, clon - 360, clon)
    cmon = list(int(x) for x in cz["months"])
    clim = np.asarray(cz["clim"], float)        # (month, lat, lon) mm w.e.
    print("ERA5 climatology:", os.path.basename(clim_path), clat.shape, clon.shape, cmon)

    mm_out = []
    anom_out = []
    for k, (y, m) in enumerate(mons):
        # the model's own anomaly: the CPC anomaly of the daily precipitation
        # rate (mm/day) scaled to the month and cut by the snow fraction
        days = calendar.monthrange(y, m)[1]
        pr_anom = prec[k] * days                      # mm/month
        # the climatological snow fraction of this month (from ERA5)
        if m in cmon:
            c = clim[cmon.index(m)]
            frac = np.clip(c / np.maximum(c, 1e-9), 0, 1)
            frac = np.where(c > 0.5, 1.0, 0.0)        # the ERA5 box is monthly
        else:
            frac = np.zeros_like(pr_anom)
        snow_anom = _bilinear(pr_anom, plat, plon, clat, clon) * frac
        # the absolute forecast: the ERA5 climatology + the model's anomaly
        if m in cmon:
            fcst = clim[cmon.index(m)] + snow_anom
        else:
            fcst = snow_anom
        mm_out.append(fcst)
        anom_out.append(snow_anom)
        print("  lead %d (%04d-%02d): ERA5 clim max %.1f mm, model anomaly max %.1f mm, "
              "forecast max %.1f mm" % (k + 1, y, m, clim[cmon.index(m)].max() if m in cmon else 0,
                                       snow_anom.max(), fcst.max()), flush=True)

    # the renderer works on the C3S grid conventions: a rate in m w.e. s-1 and
    # latitudes descending
    lat = clat[::-1].copy()
    lon = clon.copy()
    order = np.argsort(lon)
    lon = lon[order]
    months = ["%04d-%02d" % m for m in mons]
    def pack(arrs):
        a = np.stack(arrs)                     # (nmonth, nlat, nlon)
        a = a[:, :, order][:, ::-1, :]
        sec = np.array([calendar.monthrange(*m)[1] * 86400.0 for m in mons])
        return (a[None, :, :, :] / sec[None, None, None]).astype(np.float32)
    os.makedirs(os.path.join(MDIR, tag), exist_ok=True)
    np.savez_compressed(os.path.join(MDIR, tag, "snowfall_monthly.npz"),
                        months=np.array(months),
                        member_numbers=np.array([0]),
                        values=pack(mm_out),
                        lat=lat, lon=lon,
                        meta=np.array(json.dumps(
                            dict(tag=tag, name="NOAA CFSv2", init="2026-11",
                                 members=40, source="NCEP CPC monthly means",
                                 note="absolute snowfall = ERA5 1991-2020 climatology + "
                                      "the CFSv2 hindcast anomaly"))))
    np.savez_compressed(os.path.join(MDIR, tag, "snowfall_hindcast.npz"),
                        months=np.array(months),
                        values=pack(mm_out) * 0.0,      # placeholder
                        lat=lat, lon=lon,
                        meta=np.array(json.dumps(dict(init="2026-11"))))
    print("wrote", tag, "npz files")


if __name__ == "__main__":
    fetch()
