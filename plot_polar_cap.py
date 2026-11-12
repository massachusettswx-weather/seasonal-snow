"""Draw the polar-cap time-height section for a seasonal model.

The figure is the same shape as the reference: a time-height section of the
polar cap (60-90N) normalised geopotential height anomaly, with the ERA5
analysis on the left of the "forecast starts" line and the model's own
forecast on the right, running to the end of the model's run.

Inputs:
  data/era5_polarcap_profiles.npz  the ERA5 polar-cap series from ARCO
                                   (the zonal mean at every cap latitude)
  data/polar_cap_recent.npz        the ERA5 analysis just before the init
  data/polar_model_z.json          the model's daily polar-cap series
  data/polar_cap_clim.npz          the climatology, if it has been built
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import (CAP_N, CAP_S, LEVELS, build_climatology,  # noqa: E402
                       load_climatology, normalise, plot_section)
from ecmwf_credit import credit_for  # noqa: E402

OUT = os.path.join(HERE, "output", "polar_cap")
PROFILES = os.path.join(DATA, "era5_polarcap_profiles.npz")
RECENT = os.path.join(DATA, "polar_cap_recent.npz")
MODEL_CACHE = os.path.join(DATA, "polar_model_z.json")
CLIM = os.path.join(DATA, "polar_cap_clim.npz")

# how many days of ERA5 analysis to show before the forecast starts.
# Thirty days matches the reference's own analysis window, and it is
# covered by the October and November ERA5 requests on their own.
ANA_DAYS = 30


def cap_mean(profiles, lat, levels):
    """The polar-cap zonal mean from the per-latitude profiles.

    profiles: (n, nlev, nlat) the zonal mean at each cap latitude
    -> (n, nlev)

    The band edge is compared with a tolerance: ARCO stores 60N as
    59.999999999999986, and an exact test drops the bottom row of the cap.
    """
    inside = (lat >= CAP_S - 1e-6) & (lat <= CAP_N + 1e-6)
    w = np.cos(np.deg2rad(lat[inside]))
    p = np.asarray(profiles, float)[:, :, inside]
    return (p * w[None, None, :]).sum(axis=2) / w.sum()


def build_clim():
    """The ERA5 profiles -> the per-calendar-day mean and sigma."""
    d = np.load(PROFILES, allow_pickle=True)
    times = [str(t) for t in d["times"]]
    lat = d["lat"].astype(float)
    # the latitudes are the stored indices; recover their values from the
    # ARCO grid so the weights are right
    import fetch_polar_era5_arco as FA
    full_lat = FA.latitude()
    lat = full_lat[lat.astype(int)]

    vals = cap_mean(d["values"], lat, LEVELS)
    np.savez_compressed(os.path.join(DATA, "era5_polarcap_z.npz"),
                        times=np.array(times), levels=np.array(LEVELS),
                        values=vals)
    return build_climatology(os.path.join(DATA, "era5_polarcap_z.npz"), CLIM)


def load_recent():
    """The ERA5 analysis just before the init -> (times, values).

    The file is checked for signs of being synthetic: the polar-cap mean
    geopotential height is a positive number of a few hundred thousand m2/s2
    at 10 hPa, so a file whose 10 hPa values are near zero, or that holds
    fewer days than the window, is refused rather than drawn.
    """
    if not os.path.exists(RECENT):
        return [], np.zeros((0, len(LEVELS))), {}
    d = np.load(RECENT, allow_pickle=True)
    times = [str(t) for t in d["times"]]
    vals = np.asarray(d["values"], float)
    levels = [int(x) for x in (d["levels"] if "levels" in d else LEVELS)]
    if len(times) < 20:
        raise ValueError("the recent ERA5 file holds only %d days" % len(times))
    i10 = levels.index(10) if 10 in levels else 0
    if not np.all(np.isfinite(vals[:, i10])) or vals[:, i10].max() < 1e5:
        raise ValueError("the recent ERA5 file does not hold real polar-cap "
                         "geopotential heights (the 10 hPa values are %s)"
                         % vals[:, i10][:3])
    return times, vals, {"levels": levels}


def load_series(path, tag):
    """-> (times, values (n, nlev), levels) for one model's daily series.

    The same guard as the ERA5 side: the model's polar-cap mean
    geopotential height is a positive number of a few hundred thousand
    m2/s2 at 10 hPa, so a file of zeros or noise is refused rather than
    drawn.
    """
    if not os.path.exists(path):
        return None, None, []
    d = json.load(open(path))
    rec = d.get(tag)
    if not rec:
        return None, None, []
    times = list(rec["times"])
    vals = np.array(rec["values"], float)
    levels = [int(x) for x in (rec.get("levels") or LEVELS)]
    order = np.argsort(times)
    times = [times[i] for i in order]
    vals = vals[order]
    # keep only the 12Z values: one per calendar day
    keep = [i for i, t in enumerate(times) if t.endswith("12") or len(t) == 10]
    times = [times[i] for i in keep]
    vals = vals[keep]
    if len(times) < 5:
        return None, None, []
    i10 = levels.index(10) if 10 in levels else 0
    if not np.all(np.isfinite(vals[:, i10])) or vals[:, i10].max() < 1e5:
        raise ValueError("the %s series does not hold real polar-cap "
                         "geopotential heights (the 10 hPa values are %s)"
                         % (tag, vals[:, i10][:3]))
    return times, vals, levels


def main(tag="ecmwf-seas5", label="ECMWF SEAS5"):
    # 1. the climatology
    if not os.path.exists(CLIM):
        if not os.path.exists(PROFILES):
            print("   no ERA5 polar-cap profiles yet")
            return
        build_clim()
    clim = load_climatology(CLIM)

    # 2. the ERA5 analysis (the recent past, up to the model's init)
    rt, rv, d_recent = load_recent()

    # 3. the model's own forecast
    mt, mv, ser_levels = load_series(MODEL_CACHE, tag)
    if mt is None:
        print("   no series for %s yet" % tag)
        # a chart left over from an earlier build would be published with
        # no data behind it, so it goes
        stale = os.path.join(OUT, "polar_cap_%s.png" % tag)
        if os.path.exists(stale):
            os.remove(stale)
            print("   the stale chart removed: %s" % stale)
        return None

    # the levels actually present: the seasonal archive carries all twelve
    # of the reference's levels, but a series built from another source may
    # not, and the climatology has to be subset to match
    levs = [l for l in LEVELS if l in list(ser_levels or LEVELS)]
    if not levs or mv.shape[1] != len(levs):
        print("   the %s series carries %d levels, which do not match the "
              "climatology" % (tag, mv.shape[1]))
        return

    # 4. join them on the calendar day
    rday = {t[:10]: i for i, t in enumerate(rt)}
    mday = {t[:10]: i for i, t in enumerate(mt)}

    first = mt[0][:10]
    ana_days = sorted(d for d in rday if d < first)[-ANA_DAYS:]
    fc_days = sorted(mday)
    days = ana_days + fc_days
    parts = []
    if ana_days:
        # the recent file may carry a different level set, so the columns
        # are picked by level rather than by position
        rlevs = [int(x) for x in (d_recent.get("levels") if d_recent else LEVELS)]
        rcols = [rlevs.index(l) for l in levs]
        parts.append(rv[[rday[d] for d in ana_days]][:, rcols])
    parts.append(mv[[mday[d] for d in fc_days]])
    values = np.vstack(parts)
    split = len(ana_days)

    cdays, clevs, cmean, csigma = clim
    keep = [clevs.index(l) for l in levs]
    anom, norm = normalise(days, values, levs,
                           (cdays, levs, cmean[:, keep], csigma[:, keep]))
    init_day = fc_days[0] if fc_days else ""
    end_day = fc_days[-1] if fc_days else ""
    title = "%s: Polar Cap (60-90N) Normalized Geopotential Height Anomaly" % label
    subtitle = ("Data: %s seasonal forecast & ERA5 (1991-2020 Climatology)   "
                "Plot by: @Massachusettswx" % label)
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "polar_cap_%s.png" % tag)
    plot_section(days, norm, levs, p, title, subtitle,
                 split=split if split else None,
                 credit=credit_for(tag),
                 analysis_label="ERA5 ANALYSIS",
                 forecast_label="%s FORECAST (%s)" % (label.upper(), init_day))
    print("   the figure: %s" % p)
    return p


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "ecmwf-seas5"
    label = sys.argv[2] if len(sys.argv) > 2 else "ECMWF SEAS5"
    main(tag, label)
