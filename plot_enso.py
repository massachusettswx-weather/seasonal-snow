"""ENSO plumes: the ONI (absolute) and the RONI (relative) index.

Two plume families are drawn for every model and every basin:

  ONI   the sea surface temperature anomaly in the basin, against the
        1991-2020 climatology of the same basin and month - the index the
        ENSO community calls ONI for Nino 3.4;
  RONI  the same anomaly with the tropical-mean (20S-20N) SST anomaly
        subtracted and then rescaled so its spread matches the ONI - the
        Relative Oceanic Nino Index.  The tropical mean carries the global
        warming signal, so RONI says whether the Pacific is warm or cold
        *relative to the rest of the ocean*.

Both plumes carry the observed analysis in front of the forecast.  The
analysis is NOAA's ERSST v6 - the dataset CPC builds the ONI and the RONI
from - and it is measured against the same 1991-2020 climatology as the
forecast, so the observed line and the plume join without a step.

    python3 plot_enso.py                 # every published model
    python3 plot_enso.py --all           # the staged centres too
"""
import argparse
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "output")
MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
       "Nov", "Dec"]

MEM = "#7fa8d0"          # ensemble members
MEAN = "#0b3d6b"         # ensemble mean
ANALYSIS = "#111111"     # the observed analysis
GRID = "#ececec"
ZERO = "#8a8a8a"

N_OBS = 12               # how many months of analysis to show

# Only these models are published.  The other C3S centres are staged on disk
# but their plumes wait for the November init release.
# Set ENSO_RELEASE=all once the November init is out for every centre.
RELEASE = os.environ.get("ENSO_RELEASE", "ecmwf-seas5,cfsv2,sfsv1")
if RELEASE.strip().lower() == "all":
    RELEASE = []

NAMES = {"ecmwf-seas5": "ECMWF SEAS5", "cmcc-sps4": "CMCC SPS4",
         "dwd-gcfs2": "DWD GCFS2.2", "eccc-canesm5": "ECCC CanESM5.1",
         "eccc-gem5": "ECCC GEM5.2", "ukmo-gloseas6": "UKMO GloSeas6",
         "sfsv1": "NOAA SFSv1", "cfsv2": "NOAA CFSv2"}
NOTES = {"ecmwf-seas5": "C3S seasonal-monthly-single-levels",
         "sfsv1": "NOAA SFSv1 (NODD ocean store)",
         "cfsv2": "NOAA CFSv2 (NCEP CPC)"}
KINDNAME = {"oni": "ONI", "roni": "RONI"}


# ----------------------------------------------------------------------
def load():
    clim = np.load(os.path.join(DATA, "era5_enso_clim.npz"), allow_pickle=True)
    # the analysis: NOAA's ERSST v6 - the dataset CPC builds the ONI and
    # the RONI from.  It is measured against the same 1991-2020 basin
    # climatology as the forecast, so the observed line and the plume join.
    ana = np.load(os.path.join(DATA, "ersst_enso.npz"), allow_pickle=True)
    ana_src = "NOAA ERSST v6"
    models = {}
    d = os.path.join(DATA, "models")
    for tag in sorted(os.listdir(d)):
        q = os.path.join(d, tag, "enso.json")
        if os.path.exists(q):
            models[tag] = json.load(open(q))
    return clim, ana, ana_src, models


def to_celsius(a):
    """The analysis file may be in Kelvin (ERA5) or Celsius (ERSST)."""
    k = 273.15 if float(np.nanmedian(a["basin"])) > 100.0 else 0.0
    return k


def renormalisation(ana):
    """The factor that puts the relative index on the ONI's own scale.

    CPC rescales the relative index so that its interannual spread matches
    the ONI; the same factor is applied to the analysis and to every model.
    With ERSST v6 it comes out at 1.242, and the RONI built this way matches
    CPC's published RONI to 0.01 degC on average.
    """
    a = ana["basin_anom"][:, 0]                    # Nino 3.4
    t = ana["tm_anom"]
    return float(np.std(a) / np.std(a - t))


def model_anomalies(rec, clim, tm_clim):
    """-> ({basin: [per month: [member anomaly]]}, [per month: [member TM anomaly]]).

    The CFSv2 comes from CPC as an anomaly already; the others carry the
    absolute SST in Kelvin and are measured against the ERA5 1991-2020
    climatology.
    """
    months = rec["months"]
    basins = rec["basins"]
    trop = rec.get("tropical") or []
    if rec.get("kind") == "noaa-anom":
        banom = {b: [list(rec["series"][b][i]) for i in range(len(months))]
                 for b in basins}
        tanom = [list(t) for t in trop]
        return banom, tanom
    out = {}
    for bi, b in enumerate(basins):
        rows = []
        for i, m in enumerate(months):
            c = float(clim["sst"][int(m[5:7]) - 1][bi]) - 273.15
            rows.append([float(v) - 273.15 - c for v in rec["series"][b][i]])
        out[b] = rows
    trows = []
    for i, m in enumerate(months):
        c = float(tm_clim[int(m[5:7]) - 1])
        trows.append([float(v) - 273.15 - c
                      for v in (trop[i] if i < len(trop) else [])])
    return out, trows


def label(ym):
    m = int(ym[5:7])
    return MON[m] + ("\n%d" % int(ym[:4]) if m == 1 else "")


def init_label(init):
    y, m = int(init[:4]), int(init[5:7])
    return "%02d/%02d/%04d" % (m, 1, y)


def plot_basin(tag, name, rec, clim, ana, ana_src, basin, kind, k, init):
    months = rec["months"]
    bi = rec["basins"].index(basin)
    kshift = to_celsius(ana)

    # the tropical-mean climatology of the analysis dataset, in Celsius
    tm_clim = np.asarray(ana["tm_clim"], float) - kshift
    banom, tanom = model_anomalies(rec, clim, tm_clim)

    # the forecast
    fc = banom[basin]
    if kind == "roni":
        fc = [[(b - t) * k for b, t in zip(fc[i], tanom[i])]
              for i in range(len(months))]

    # the analysis, measured against the same 1991-2020 climatology as the
    # forecast so the observed line and the plume join without a step
    om = [str(m) for m in ana["months"]]
    oa = np.asarray(ana["basin"], float)[:, bi] - kshift
    for i, m in enumerate(om):
        oa[i] -= float(clim["sst"][int(m[5:7]) - 1][bi]) - 273.15
    ota = np.asarray(ana["tm"], float) - kshift - tm_clim[
        np.array([int(m[5:7]) - 1 for m in om])]
    if kind == "roni":
        oa = (oa - ota) * k
    keep = [i for i in range(len(om)) if om[i] <= months[-1]][-N_OBS:]
    obs_m = [om[i] for i in keep]
    obs_v = [float(oa[i]) for i in keep]

    # one continuous month axis
    axis = sorted(set(obs_m) | set(months))
    pos = {m: i for i, m in enumerate(axis)}
    xs = [pos[m] for m in obs_m]
    xf = [pos[m] for m in months]
    labels = [label(m) for m in axis]

    fig, ax = plt.subplots(figsize=(10.4, 4.5), dpi=130)
    arr = np.array([np.asarray(v, float) for v in fc])
    nmem = arr.shape[1]
    for j in range(nmem):
        ax.plot(xf, arr[:, j], color=MEM, lw=0.6, alpha=0.5, zorder=2,
                label=("members" if (j == 0 and nmem > 1) else None))
    mean = arr.mean(axis=1)
    ax.fill_between(xf, arr.min(axis=1), arr.max(axis=1), color=MEM,
                    alpha=0.13, lw=0, zorder=1)
    ax.plot(xf, mean, color=MEAN, lw=2.6, zorder=3,
            label="ensemble mean" if nmem > 1 else "ensemble mean (CPC)")
    # the analysis on top
    ax.plot(xs, obs_v, color=ANALYSIS, lw=2.4, marker="o", ms=3.4,
            label="analysis (%s)" % ana_src, zorder=4)
    ax.axhline(0, color=ZERO, lw=1.0, ls="--", zorder=1)

    # the init marker
    if init in pos:
        ax.axvline(pos[init], color="#b9b9b9", lw=1.0, zorder=1)
        ax.text(pos[init] + 0.15, 0.02, "init %s" % init_label(init),
                transform=ax.get_xaxis_transform(), fontsize=8,
                color="#777777", va="bottom")

    ax.set_xticks(range(len(axis)))
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("SST anomaly (°C)" if kind == "oni"
                  else "Relative SST anomaly (°C)", fontsize=10.5)
    ax.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    lo = min(min(obs_v), float(arr.min()))
    hi = max(max(obs_v), float(arr.max()))
    pad = max(0.25, 0.08 * (hi - lo))
    ax.set_ylim(lo - pad, hi + pad)

    ax.set_title("%s  %s plume — %s" % (name, KINDNAME[kind], basin),
                 fontsize=15, fontweight="bold", loc="left", pad=18)
    if rec.get("kind") == "noaa-anom":
        mdesc = "40-member ensemble mean"
    else:
        mdesc = "%d members" % nmem
    ax.text(0, 1.02,
            "init %s · %s · SST anomaly vs 1991-2020 · analysis %s to %s" %
            (init_label(init), mdesc, ana_src, obs_m[-1] if obs_m else "-"),
            transform=ax.transAxes, fontsize=8.6, color="#6b6b6b", va="bottom")
    ax.text(0.995, 1.02, "max %+.2f / min %+.2f °C" % (float(mean.max()),
                                                       float(mean.min())),
            transform=ax.transAxes, fontsize=9, color="#555555",
            ha="right", va="bottom")
    leg = ax.legend(loc="upper left", fontsize=8, frameon=False, ncol=3,
                    handlelength=1.8, columnspacing=1.2)
    for t in leg.get_texts():
        t.set_color("#444444")
    fig.text(0.995, 0.02, "@Massachusettswx", ha="right", fontsize=11,
             fontweight="bold")
    fig.text(0.005, 0.02, "Data: %s · analysis %s" %
             (NOTES.get(tag, rec.get("note", "C3S seasonal")), ana_src),
             ha="left", fontsize=7.6, color="#8a8a8a")
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    fn = "ENSO_%s_%s_%s.png" % (tag.upper().replace("-", "_"),
                                basin.replace(" ", "").replace("+", "p"),
                                kind.upper())
    fig.savefig(os.path.join(OUT, fn))
    plt.close(fig)
    print("  %-46s analysis %s..%s  forecast %s..%s  members %d" %
          (fn, obs_m[0] if obs_m else "-", obs_m[-1] if obs_m else "-",
           months[0], months[-1], nmem), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="also render the staged centres")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    clim, ana, ana_src, models = load()
    k = renormalisation(ana)
    print("analysis %s · relative-index rescaling factor k = %.3f" %
          (ana_src, k), flush=True)

    for tag, rec in sorted(models.items()):
        if not args.all and RELEASE and tag not in RELEASE:
            print("== %s: staged, not published yet" % tag, flush=True)
            continue
        name = NAMES.get(tag, tag)
        init = rec.get("init") or "2026-11"
        print("== %s (%s, init %s)" % (tag, name, init), flush=True)
        for basin in rec["basins"]:
            for kind in ("oni", "roni"):
                plot_basin(tag, name, rec, clim, ana, ana_src, basin,
                           kind, k, init)


if __name__ == "__main__":
    main()
