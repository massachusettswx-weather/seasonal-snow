"""Render the SEAS5 (init 1 Nov 2026) 10 hPa zonal-mean zonal wind panel.

SEAS5 is a MONTHLY product: one value per member per lead month, plotted at
mid-month. The daily curves are the ERA5 1991-2020 climatology layer
(mean, record min/max, percentile bands).

usage: python3 plot_seas5.py [--domain 60|NH] [--init 202611]
"""
import os, json, argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ERA5 = os.path.join(HERE, "era5_clim_10hpa.json")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def load_era5(domain, y0):
    """Daily climatology over the forecast window (01 Oct of the init year ->
    10 Jun of the next), keyed by calendar day."""
    d = json.load(open(ERA5))
    clim = d["60N" if domain == "60" else "NH"]
    out = {k: [] for k in ("t", "mean", "rmin", "rmax", "p30", "p70", "p10", "p90")}
    cur = datetime(y0, 10, 1)
    while cur <= datetime(y0 + 1, 6, 10):
        md = cur.strftime("%m-%d")
        if md in clim:
            c = clim[md]
            out["t"].append(cur); out["mean"].append(c["mean"]); out["rmin"].append(c["rmin"])
            out["rmax"].append(c["rmax"]); out["p30"].append(c["p30"]); out["p70"].append(c["p70"])
            out["p10"].append(c["p10"]); out["p90"].append(c["p90"])
        cur += timedelta(days=1)
    return out


def month_centers(y, m, n):
    """Start-of-month stamps for the n lead months (lead 1 = the init month).

    The reference plot carries its member traces edge to edge, so a monthly
    mean is drawn at the first of the month it represents.
    """
    out, yy, mm = [], y, m
    for _ in range(n):
        out.append(datetime(yy, mm, 1))
        mm += 1
        if mm > 12:
            mm, yy = 1, yy + 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="60", choices=["60", "NH"])
    ap.add_argument("--init", default="202611", help="init tag, e.g. 202611")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    dom, tag = args.domain, args.init
    init_y, init_m = int(tag[:4]), int(tag[4:6])
    out = args.out or os.path.join(HERE, "output",
                                   "SEAS5_%s_u10hPa_%sN.png" % (tag, dom))

    run = np.load(os.path.join(DATA, "seas5_%s_u10.npz" % tag))
    mem = run["members60"] if dom == "60" else run["members_nh"]
    clim = np.load(os.path.join(DATA, "seas5_%s_clim.npz" % tag))
    mc = clim["clim60"] if dom == "60" else clim["clim_nh"]
    ens_cds = clim["ens60"] if dom == "60" else clim["ens_nh"]

    nlead = mem.shape[1]
    centers = month_centers(init_y, init_m, nlead)
    e = load_era5(dom, init_y)

    fig, ax = plt.subplots(figsize=(13.6, 7.0), dpi=150)
    fig.subplots_adjust(left=0.065, right=0.985, top=0.885, bottom=0.115)

    # ---- ERA5 1991-2020 climatology (the daily layer) --------------------
    ax.fill_between(e["t"], e["p10"], e["p90"], color="#9db8e8", alpha=0.16, lw=0, zorder=1)
    ax.fill_between(e["t"], e["p30"], e["p70"], color="#7ea3e0", alpha=0.30, lw=0, zorder=2)
    ax.plot(e["t"], e["mean"], color="#1f3fd6", lw=1.7, zorder=4)
    ax.plot(e["t"], e["rmin"], color="#1f3fd6", lw=1.2, ls="--", zorder=3)
    ax.plot(e["t"], e["rmax"], color="#e01b1b", lw=1.2, ls="--", zorder=3)

    # ---- SEAS5 members (monthly means) + ensemble mean --------------------
    for i in range(mem.shape[0]):
        ax.plot(centers, mem[i], color="#8a8a8a", lw=0.55, alpha=0.42, zorder=5)
    ens = np.nanmean(mem, axis=0)
    ax.plot(centers, ens, color="black", lw=2.1, marker="o", ms=3.4, zorder=7)

    # ---- ECMWF model-climate mean (HCMEAN), also monthly -----------------
    ax.plot(centers, np.asarray(mc, dtype=float), color="#e01b1b", lw=2.0,
            marker="s", ms=3.0, zorder=7)

    # ---- furniture --------------------------------------------------------
    ax.axhline(0, color="black", lw=1.2, zorder=6)
    ax.grid(True, ls="--", lw=0.7, color="#c9c9c9", alpha=0.75)
    ax.set_ylabel("U (m/s) at 10 hPa, 60°N" if dom == "60"
                   else "U (m/s) at 10 hPa, NH (0-90N)", fontsize=11)
    ax.set_xlabel("Valid Days", fontsize=11)
    ax.set_xlim(datetime(init_y, init_m, 1),
                datetime(centers[-1].year + (centers[-1].month // 12),
                         centers[-1].month % 12 + 1, 1))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%Y"))
    ax.tick_params(labelsize=10)

    # legend in the reference's order
    handles = [
        Line2D([], [], color="#8a8a8a", lw=0.9, label="ECMWF Members"),
        Line2D([], [], color="black", lw=2.1, marker="o", ms=3.4, label="ECMWF Mean"),
        Line2D([], [], color="#1f3fd6", lw=1.7, label="ERA5 Average"),
        Line2D([], [], color="#1f3fd6", lw=1.2, ls="--", label="ERA5 Record Min"),
        Line2D([], [], color="#e01b1b", lw=1.2, ls="--", label="ERA5 Record Max"),
        Patch(facecolor="#7ea3e0", alpha=0.30, label="ERA5 30-70th Percentile"),
        Patch(facecolor="#9db8e8", alpha=0.16, label="ERA5 10-90th Percentile"),
        Line2D([], [], color="#e01b1b", lw=2.0, marker="s", ms=3.0,
               label="Model-Climate Mean (Init: %s)" % MONTHS[init_m - 1]),
    ]
    leg = ax.legend(handles=handles, loc="upper left", fontsize=9.2, framealpha=0.92,
                    borderpad=0.6, labelspacing=0.35)
    leg.get_frame().set_edgecolor("#888888")

    lbl = "%s %d" % (MONTHS[init_m - 1], init_y)
    ttl = ("ECMWF Seasonal 10-hPa 60°N Zonal Mean Zonal Wind (m/s) - Run Init: %s" % lbl
           if dom == "60" else
           "ECMWF Seasonal 10-hPa NH (0-90N) Zonal Mean Zonal Wind (m/s) - Run Init: %s" % lbl)
    fig.text(0.065, 0.955, ttl, fontsize=14.5, va="center")
    fig.text(0.985, 0.965, "ERA5 Climatology: 1991-2020", fontsize=9,
             ha="right", va="center", fontweight="bold")
    fig.text(0.985, 0.932, "Model Hindcast Clim: ECMWF HCMEAN", fontsize=9,
             ha="right", va="center", fontweight="bold")
    fig.text(0.5, 0.018,
             "SEAS5 monthly means (51 members, init 1 %s) - ERA5 daily climatology 1991-2020 - "
             "Data: ECMWF/Copernicus CDS, ERA5 ARCO - Plot by @Massachusettswx" % lbl,
             fontsize=8.5, ha="center", va="center")

    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, facecolor="white")
    print("wrote", out)
    print("ensemble mean (from members):", np.round(ens, 2))
    print("ensemble mean (from CDS file) :", np.round(np.asarray(ens_cds, float), 2))
    print("model-climate mean            :", np.round(np.asarray(mc, float), 2))


if __name__ == "__main__":
    main()
