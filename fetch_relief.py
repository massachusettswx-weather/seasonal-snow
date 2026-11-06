"""Build a shaded-relief basemap for the snow-anomaly maps.

Source: ARCO-ERA5 single-level 0.25 deg store -> geopotential_at_surface
         -> orography (m) -> hillshade (classic ESRI-style) + grey relief.

Output: data/relief_025.npz with
    lat (721,), lon (1440,), oro (721,1440), shade (721,1440) in 0..1
"""
import os, urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
BUCKET = "https://storage.googleapis.com/gcp-public-data-arco-era5/"
STORE = "ar/1959-2022-6h-1440x721.zarr"
OUT = os.path.join(DATA, "relief_025.npz")


def _decode(buf):
    import numcodecs
    try:
        out = numcodecs.Blosc().decode(buf)
    except Exception:
        out = buf
    if isinstance(out, (bytes, bytearray)):
        out = np.frombuffer(out, dtype="<f4")
    return np.asarray(out, dtype=np.float32)


def fetch(path):
    buf = urllib.request.urlopen("%s%s/%s" % (BUCKET, STORE, path), timeout=120).read()
    return _decode(buf)


def main():
    if os.path.exists(OUT):
        print("already have", OUT)
        return
    oro = fetch("geopotential_at_surface/0.0").astype(np.float64)   # m2 s-2
    lat = fetch("latitude/0").astype(np.float64)
    lon = fetch("longitude/0").astype(np.float64)
    oro = (oro / 9.80665).reshape(len(lat), len(lon))                # m
    if lat[0] < lat[-1]:
        lat = lat[::-1]
        oro = oro[::-1, :]
    np.savez_compressed(OUT, lat=lat, lon=lon, oro=oro)
    print("orography", oro.shape, "range %.0f..%.0f m" % (oro.min(), oro.max()))


def hillshade(oro, lat, lon, azimuth_deg=315.0, zenith_deg=45.0, z_factor=1.0):
    """Standard hillshade (matplotlib recipe) -> 0..1 shading factor."""
    dy = (lat[1] - lat[0]) * 111320.0        # m per row
    dx = (lon[1] - lon[0]) * 111320.0 * np.cos(np.deg2rad(lat))   # m per col
    dzdx = np.gradient(oro, axis=1) / dx[:, None]
    dzdy = np.gradient(oro, axis=0) / dy
    slope = np.pi / 2.0 - np.arctan(z_factor * np.sqrt(dzdx ** 2 + dzdy ** 2))
    aspect = np.arctan2(-dzdx, dzdy)
    zenith = np.deg2rad(zenith_deg)
    azimuth = np.deg2rad(azimuth_deg)
    hs = (np.sin(zenith) * np.cos(slope) +
          np.cos(zenith) * np.sin(slope) * np.cos(azimuth - aspect))
    return np.clip(hs, 0, 1)


if __name__ == "__main__":
    main()
