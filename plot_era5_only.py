"""Standalone ERA5 1991-2020 daily climatology panel (10 hPa zonal wind).

usage: python3 plot_era5_only.py [--domain 60|NH] [--year 2026]
"""
import os, json, argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ERA5 = os.path.join(HERE, "era5_clim_10hpa.json")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="60", choices=["60", "NH"])
    ap.add_argument("--year", type=int, default=2026)
    args = ap.parse_args()
    dom = args.domain
    clim = json.load(open(ERA5))["60N" if dom == "60" else "NH"]

    t, mean, rmin, rmax, p10, p90, p30, p70 = [], [], [], [], [], [], [], []
    cur = datetime(args.year, 10, 1)
    while cur <= datetime(args.year + 1, 6, 10):
        md = cur.strftime("%m-%d")
        if md in clim:
            c = clim[md]
            t.append(cur); mean.append(c["mean"]); rmin.append(c["rmin"])
            rmax.append(c["rmax"]); p10.append(c["p10"]); p90.append(c["p90"])
            p30.append(c["p30"]); p70.append(c["p70"])
        cur += timedelta(days=1)

    fig, ax = plt.subplots(figsize=(13.6, 7.0), dpi=150)
    fig.subplots_adjust(left=0.065, right=0.985, top=0.885, bottom=0.115)
    ax.fill_between(t, p10, p90, color="#9db8e8", alpha=0.16, lw=0, zorder=1)
    ax.fill_between(t, p30, p70, color="#7ea3e0", alpha=0.30, lw=0, zorder=2)
    ax.plot(t, mean, color="#1f3fd6", lw=1.7, zorder=4)
    ax.plot(t, rmin, color="#1f3fd6", lw=1.2, ls="--", zorder=3)
    ax.plot(t, rmax, color="#e01b1b", lw=1.2, ls="--", zorder=3)
    ax.axhline(0, color="black", lw=1.2, zorder=6)
    ax.grid(True, ls="--", lw=0.7, color="#c9c9c9", alpha=0.75)
    ax.set_ylabel("U (m/s) at 10 hPa, 60°N" if dom == "60"
                   else "U (m/s) at 10 hPa, NH (0-90N)", fontsize=11)
    ax.set_xlabel("Valid Days", fontsize=11)
    ax.set_xlim(datetime(args.year, 10, 1), datetime(args.year + 1, 6, 1))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%Y"))
    ax.tick_params(labelsize=10)
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    handles = [Line2D([], [], color="#1f3fd6", lw=1.7, label="ERA5 Average"),
               Line2D([], [], color="#1f3fd6", lw=1.2, ls="--", label="ERA5 Record Min"),
               Line2D([], [], color="#e01b1b", lw=1.2, ls="--", label="ERA5 Record Max"),
               Patch(facecolor="#7ea3e0", alpha=0.30, label="ERA5 30-70th Percentile"),
               Patch(facecolor="#9db8e8", alpha=0.16, label="ERA5 10-90th Percentile")]
    leg = ax.legend(handles=handles, loc="upper left", fontsize=9.2, framealpha=0.92)
    leg.get_frame().set_edgecolor("#888888")
    label = "60°N" if dom == "60" else "NH (0-90N)"
    fig.text(0.065, 0.955, "ERA5 10-hPa %s Zonal Mean Zonal Wind (m/s)" % label,
             fontsize=14.5, va="center")
    fig.text(0.985, 0.965, "ERA5 Climatology: 1991-2020", fontsize=9,
             ha="right", va="center", fontweight="bold")
    fig.text(0.5, 0.022,
             "ERA5 daily climatology 1991-2020 (daily 12Z zonal means)  -  "
             "Data: ERA5 ARCO / Copernicus  -  Plot by @Massachusettswx",
             fontsize=7.6, ha="center", va="center")
    out = os.path.join(HERE, "output", "ERA5_clim_1991-2020_u10hPa_%s.png"
                       % ("60N" if dom == "60" else "NH"))
    fig.savefig(out, facecolor="white")
    print("wrote", out)


if __name__ == "__main__":
    main()
