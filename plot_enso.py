"""ENSO plume charts: every ensemble member, the ensemble mean, and the ERA5
1991-2020 climatological range for each basin.

    python3 plot_enso.py
"""
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

MEM = "#7fa8d0"
MEAN = "#0b3d6b"
BAND = "#d9d9d9"
GRID = "#e8e8e8"


# Only these models are published.  The other C3S centres are staged on disk
# but their plumes wait for the November init release.
RELEASE = ["ecmwf-seas5", "cfsv2", "sfsv1"]


def load():
    z = np.load(os.path.join(DATA, "era5_enso_clim.npz"), allow_pickle=True)
    clim = {"sst": z["sst"], "t2m": z["t2m"],
            "sst_min": z["sst_min"], "sst_max": z["sst_max"],
            "sst_std": z["sst_std"], "basins": list(z["basins"])}
    models = {}
    d = os.path.join(DATA, "models")
    for tag in sorted(os.listdir(d)):
        p = os.path.join(d, tag, "enso.json")
        if os.path.exists(p):
            models[tag] = json.load(open(p))
    return clim, models


def anomalies(rec, clim):
    """-> {basin: [per month: [member anomalies]]} plus the field used."""
    kind = rec.get("kind", "")
    basins = rec["basins"]
    months = rec["months"]
    out = {b: [] for b in basins}
    if kind == "noaa-anom":
        # CPC publishes the anomaly already (against a 1991-2020 climatology)
        for i, m in enumerate(months):
            for b in basins:
                out[b].append([float(v) for v in rec["series"][b][i]])
        return out, "2 m air temperature"
    key = "sst" if kind in ("c3s-sst", "noaa-sst") else "t2m"
    ci = basins.index
    for i, m in enumerate(months):
        mm = int(m[5:7])
        for b in basins:
            c = clim[key][mm - 1][ci(b)]
            out[b].append([float(v) - float(c) for v in rec["series"][b][i]])
    return out, ("sea surface temperature" if key == "sst" else "2 m air temperature")


def plot_model(tag, name, rec, clim, note):
    anom, field = anomalies(rec, clim)
    basins = rec["basins"]
    months = rec["months"]
    x = np.arange(len(months))
    labels = [MON[int(m[5:7])] + ("\n%d" % int(m[:4]) if int(m[5:7]) == 1 else "")
              for m in months]
    for b in basins:
        fig, ax = plt.subplots(figsize=(9.6, 5.6), dpi=130)
        series = np.array([np.asarray(v, float) for v in anom[b]])   # (month, member)
        for k in range(series.shape[1]):
            ax.plot(x, series[:, k], color=MEM, lw=0.6, alpha=0.55, zorder=2)
        mean = series.mean(axis=1)
        lo = series.min(axis=1)
        hi = series.max(axis=1)
        ax.fill_between(x, lo, hi, color=MEM, alpha=0.13, lw=0, zorder=1)
        ax.plot(x, mean, color=MEAN, lw=2.6, zorder=3)
        ax.axhline(0, color="#666666", lw=1.0, ls="--", zorder=1)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=9)
        ax.set_ylabel("Temperature anomaly (°C)", fontsize=11)
        ax.grid(True, color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.set_title("%s  ENSO Plume — %s" % (name, b), fontsize=15,
                     fontweight="bold", loc="left", pad=16)
        ax.text(0, 1.015, "%s · %d members · %s · anomaly vs ERA5 1991-2020" %
                (note, series.shape[1], field), transform=ax.transAxes,
                fontsize=9.5, color="#666666", va="bottom")
        fig.text(0.995, 0.02, "@Massachusettswx", ha="right", fontsize=11,
                 fontweight="bold")
        fig.text(0.005, 0.02, "Data: %s · ERA5 1991-2020 climatology" % note,
                 ha="left", fontsize=8, color="#888888")
        fig.tight_layout(rect=[0, 0.05, 1, 1])
        fn = "ENSO_%s_%s.png" % (tag.upper().replace("-", "_"),
                                 b.replace(" ", "").replace("+", "p"))
        fig.savefig(os.path.join(OUT, fn))
        plt.close(fig)
        print("  %s" % fn, flush=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    clim, models = load()
    names = {"ecmwf-seas5": "ECMWF SEAS5", "cmcc-sps4": "CMCC SPS4",
             "dwd-gcfs2": "DWD GCFS2.2", "eccc-canesm5": "ECCC CanESM5",
             "eccc-gem5": "ECCC GEM5.2", "ukmo-gloseas6": "UKMO GloSeas6",
             "sfsv1": "NOAA SFSv1", "cfsv2": "NOAA CFSv2"}
    notes = {"ecmwf-seas5": "C3S seasonal-monthly-single-levels",
             "sfsv1": "NOAA SFSv1 (NODD)", "cfsv2": "NOAA CFSv2 (NCEP CPC)"}
    for tag, rec in models.items():
        if RELEASE and tag not in RELEASE:
            print("== %s: staged, not published yet" % tag, flush=True)
            continue
        note = notes.get(tag, rec.get("note", "C3S seasonal"))
        print("== %s" % tag, flush=True)
        plot_model(tag, names.get(tag, tag), rec, clim, note)


if __name__ == "__main__":
    main()
