"""Build the snowfall of the centres that publish precipitation but not snow.

JMA and BoM do not publish the `snowfall` field in the C3S monthly
single-levels product - MARS answers "MarsNoDataError" for it - but they
do publish `total_precipitation` for the same init, and it comes down in
seconds.  So their snowfall is derived the same way the ERA5 CONUS
climatology was derived: the model's own precipitation times the fraction
of the climatological precipitation that falls as snow.

    fraction = climatological snowfall / climatological precipitation

which is the ERA5 1991-2020 ratio for that grid cell and calendar month.
The result is an absolute snowfall field in the same convention as every
other model: a rate in m w.e. s-1, the latitudes descending, on the CONUS
grid the renderer works on.

This is an approximation - a centre's snow does not necessarily fall
where its climatology says it falls - and it is only used where the
direct snowfall is not published.  If the archive later stages the
`snowfall` field for that init, the direct field is used instead.

The file is read as a stream: the members are averaged as they are
decoded and only the CONUS points are kept, because a whole global
ensemble in memory is several gigabytes.
"""
import os
import sys
import calendar
import json

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")


def conus_grid():
    """-> (lat, lon, months) of the CONUS climatology grid."""
    for name in ("era5_snow_clim_arco_conus.npz", "era5_snow_clim_arco.npz"):
        p = os.path.join(DATA, name)
        if not os.path.exists(p):
            continue
        z = np.load(p, allow_pickle=True)
        lat = np.asarray(z["lat"], float)
        lon = np.asarray(z["lon"], float)
        lon = np.where(lon > 180, lon - 360.0, lon)
        return lat, lon, [int(x) for x in z["months"]], z
    return None, None, None, None


def read_precip_conus(path, clat, clon):
    """-> (months, values) with values (nmonth, nlat, nlon) in m s-1.

    The members are averaged as they are decoded and the CONUS points are
    kept, so the whole global ensemble never has to fit in memory.
    """
    import eccodes
    from datetime import datetime as _dt, timedelta as _td
    sums = {}
    counts = {}
    la = lo = None
    keep = None
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                step = int(eccodes.codes_get(gid, "step"))
                dd = int(eccodes.codes_get(gid, "dataDate"))
                d0 = _dt(dd // 10000, (dd // 100) % 100, dd % 100)
                valid = d0 + _td(hours=step)
                month = valid - _td(days=1)     # the month the mean covers
                gla = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                glo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                if la is None:
                    la = np.where(gla > 90, gla - 180.0, gla)
                    lo = np.where(glo > 180, glo - 360.0, glo)
                    # the model's own grid inside the climatology's box.  It
                    # is a regular lat/lon grid, so the points inside the box
                    # form a rectangle and can be put back into a 2-D array -
                    # which is what the bilinear resampler needs.
                    keep = ((la >= clat.min() - 1.0) & (la <= clat.max() + 1.0) &
                            (lo >= clon.min() - 1.0) & (lo <= clon.max() + 1.0))
                    if not keep.any():
                        print("   no model points inside the CONUS box",
                              flush=True)
                        return None, None
                    ulat = np.unique(la[keep])[::-1]      # north to south
                    ulon = np.unique(lo[keep])            # west to east
                    irow = {v: i for i, v in enumerate(ulat)}
                    icol = {v: i for i, v in enumerate(ulon)}
                    shape = (len(ulat), len(ulon))
                    lut = np.full(len(la), -1, int)
                    cuc = np.full(len(la), -1, int)
                    kk = np.nonzero(keep)[0]
                    for q in kk:
                        lut[q] = irow[la[q]]
                        cuc[q] = icol[lo[q]]
                    grid_shape = shape
                v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                v = v.reshape(la.shape)
                # into the 2-D sub-grid
                sub = np.full(grid_shape, np.nan)
                sub[lut, cuc] = v
                key = (month.year, month.month)
                if key in sums:
                    sums[key] = sums[key] + np.nan_to_num(sub)
                else:
                    sums[key] = np.nan_to_num(sub)
                counts[key] = counts.get(key, 0) + 1
            except Exception:
                pass
    if not sums:
        return None, None
    months = sorted(sums)
    out = np.stack([sums[m] / counts[m] for m in months])
    return months, (out, ulat, ulon)


def bilinear(src, slat, slon, tlat, tlon):
    """Bilinear resample of a 2-D field (order-agnostic)."""
    o = np.argsort(slat); slat = np.asarray(slat)[o]; src = src[o, :]
    o = np.argsort(slon); slon = np.asarray(slon)[o]; src = src[:, o]
    i = np.clip(np.searchsorted(slat, tlat) - 1, 0, len(slat) - 2)
    dy = (tlat - slat[i]) / (slat[i + 1] - slat[i])
    j = np.clip(np.searchsorted(slon, tlon) - 1, 0, len(slon) - 2)
    dx = (tlon - slon[j]) / (slon[j + 1] - slon[j])
    ii, jj = i[:, None], j[None, :]
    return ((1 - dy)[:, None] * ((1 - dx)[None, :] * src[ii, jj] +
                                 dx[None, :] * src[ii, jj + 1]) +
            dy[:, None] * ((1 - dx)[None, :] * src[ii + 1, jj] +
                           dx[None, :] * src[ii + 1, jj + 1]))


def build(tag, precip_path):
    """The derived snowfall for one centre -> writes snowfall_monthly.npz."""
    clat, clon, cmon, cz = conus_grid()
    if clat is None:
        print("  %s: no climatology to derive the snow fraction from" % tag,
              flush=True)
        return False
    got = read_precip_conus(precip_path, clat, clon)
    if not got:
        print("  %s: the precipitation file did not decode" % tag, flush=True)
        return False
    months, (prec, plat, plon) = got
    clim = np.asarray(cz["clim"], float)                       # snow, mm
    cprec = np.asarray(cz["clim_precip"], float) \
        if "clim_precip" in cz.files else None
    if cprec is None:
        print("  %s: the climatology has no precipitation to take the snow "
              "fraction from" % tag, flush=True)
        return False
    frac = np.clip(clim / np.maximum(cprec, 1e-6), 0.0, 1.0)

    # The climatology's snow fraction goes onto the model's own grid, the
    # model's precipitation is multiplied by it, and the result goes back
    # onto the CONUS grid the renderer works on.
    rows = []
    for k, (y, m) in enumerate(months):
        if m not in cmon:
            print("  %s: no climatology for month %02d" % (tag, m), flush=True)
            return False
        f = bilinear(frac[cmon.index(m)], clat, clon, plat, plon)
        snow_m = prec[k] * f
        rows.append(bilinear(snow_m, plat, plon, clat, clon))
    snow = np.stack(rows)                       # m s-1 of water equivalent

    sec = np.array([calendar.monthrange(y, m)[1] * 86400.0 for (y, m) in months])
    lat = clat[::-1].copy()                     # the latitudes descending
    lon = clon.copy()
    # snow is already a RATE in m s-1, which is the convention the
    # renderer works in - the months are not reversed and nothing is
    # divided by the length of the month
    vals = snow[:, ::-1, :]
    os.makedirs(os.path.join(MDIR, tag), exist_ok=True)
    np.savez_compressed(
        os.path.join(MDIR, tag, "snowfall_monthly.npz"),
        months=np.array(["%04d-%02d" % m for m in months]),
        member_numbers=np.array([0]),
        values=vals[None, :, :, :].astype(np.float32),
        lat=lat, lon=lon,
        meta=np.array(json.dumps(dict(
            tag=tag, init="%04d-%02d" % months[0], members=1,
            source="total precipitation x the ERA5 1991-2020 snow fraction",
            note="derived - this centre does not publish the snowfall field"))))
    print("  %s: derived snowfall for %d lead months, max %.0f mm/month "
          "(the climatology's mean is %.0f)"
          % (tag, len(months),
             float(np.nanmax(snow[0]) * sec[0] * 1000.0),
             float(clim[cmon.index(months[0][1])].mean())), flush=True)
    return True


if __name__ == "__main__":
    for t in sys.argv[1:]:
        build(t, os.path.join(MDIR, t, "precip_monthly.grib"))
