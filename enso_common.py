"""Shared ENSO basin definitions and helpers."""
import numpy as np

# basin: name, lat0, lat1, lon0, lon1  (longitudes 0..360, as the source data)
BASINS = [
    ("Nino 3.4", 5.0, -5.0, 190.0, 240.0),
    ("Nino 3", 5.0, -5.0, 210.0, 270.0),
    ("Nino 4", 5.0, -20.0, 160.0, 210.0),
    ("Nino 1+2", 0.0, -10.0, 270.0, 280.0),
]
BASIN_NAMES = [b[0] for b in BASINS]


def basin_weights(lat, lon, land=None):
    """-> {basin: (weights, indices)} for a lat/lon grid."""
    out = {}
    w2 = np.cos(np.deg2rad(lat))[:, None] * np.ones((1, len(lon)))
    if land is not None:
        w2 = np.where(land > 0.5, 0.0, w2)
    for name, la0, la1, lo0, lo1 in BASINS:
        m = (lat[:, None] >= min(la0, la1)) & (lat[:, None] <= max(la0, la1)) & \
            (lon[None, :] >= min(lo0, lo1)) & (lon[None, :] <= max(lo0, lo1))
        out[name] = (w2 * m, m)
    return out


def basin_mean(lat, lon, field, land=None):
    """-> {basin: area-weighted mean of a 2-D field}."""
    out = {}
    ok = np.isfinite(field) & (field > -50.0)      # fill values are missing
    for name, (w, m) in basin_weights(lat, lon, land).items():
        ww = np.where(ok, w, 0.0)          # ignore the land fill values
        ff = np.where(ok, field, 0.0)
        t = ww.sum()
        out[name] = float(np.sum(ff * ww) / t) if t > 0 else np.nan
    return out


def basin_means_stack(lat, lon, stack, land=None):
    """-> {basin: [per-member values]} for a stack of 2-D fields."""
    ws = basin_weights(lat, lon, land)
    out = {n: [] for n in ws}
    for f in stack:
        for name, (w, m) in ws.items():
            s = w.sum()
            out[name].append(float(np.sum(f * w) / s) if s > 0 else np.nan)
    return out


def tropical_mean(lat, lon, field, land=None):
    """Area-weighted mean SST over the whole tropics (20S-20N, all longitudes).

    This is the term the relative index (RONI) subtracts from the basin
    anomaly to strip out the global warming signal.
    """
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    w = np.cos(np.deg2rad(lat))[:, None] * np.ones((1, len(lon)))
    # the tropical mean is 20S-20N, every longitude
    band = (lat[:, None] >= -20.0) & (lat[:, None] <= 20.0)
    w = w * band
    ok = np.isfinite(field) & (field > -50.0)      # fill values are missing
    if land is not None:
        w = np.where(land > 0.5, 0.0, w)
    w = np.where(ok, w, 0.0)
    f = np.where(ok, field, 0.0)
    t = w.sum()
    return float(np.sum(f * w) / t) if t > 0 else np.nan


def month_label(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
            "Oct", "Nov", "Dec"][m] + " %d" % y


_LAND = None


def land_mask_on(lat, lon):
    """The ERA5 land-sea mask (1 = land) resampled onto any lat/lon grid.

    The model SST fields are filled with a garbage value over land, and the
    Nino 1+2 box straddles the South American coast, so every basin mean has
    to exclude land.
    """
    global _LAND
    import os
    import numpy as np
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                     "era5_enso_landmask.npz")
    if _LAND is None:
        z = np.load(p)
        _LAND = (z["land"], z["lat"], z["lon"])
    land, alat, alon = _LAND
    # nearest neighbour on the 0..360 longitude circle
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    lat_i = np.clip(np.abs(alat[:, None] - lat[None, :]).argmin(axis=0),
                    0, len(alat) - 1)
    lon_i = np.clip(np.abs(alon[:, None] - lon[None, :]).argmin(axis=0),
                    0, len(alon) - 1)
    return land[lon_i][:, lat_i].T          # land is (lon, lat) -> (lat, lon)
