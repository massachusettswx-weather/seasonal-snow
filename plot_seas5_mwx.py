"""SEAS5 10 hPa zonal-mean zonal wind - house style variant (MWX).

Same construction as the reference chart (daily 51-member SEAS5 traces, daily
ERA5 1991-2020 climatology layer, ECMWF model-climate mean), but with its own
palette, typography and layout so it does not read as a copy of the original
severe.weather.eu panel:

  * palette re-mapped (slate members, navy mean, amber ERA5 mean,
    teal/magenta record bounds, warm-grey percentile bands, green climate)
  * frameless horizontal legend under a bold left-aligned title
  * 14-day date ticks instead of month-start ticks, horizontal grid only
  * @Massachusettswx set in the bottom-right corner

usage: python3 plot_seas5_mwx.py --domain 60 --init 202610
"""
import os, sys, argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from plot_seas5_daily import load_era5, model_climate_curve, MONTHS  # noqa: E402

DATA = os.path.join(HERE, "data")

# house palette
C_MEMBER = "#7c8ca3"
C_MEAN = "#12263f"
C_ERA5 = "#c2410c"
C_RMIN = "#0e7490"
C_RMAX = "#9d174d"
C_BAND_OUT = "#e7e5e4"
C_BAND_IN = "#d6d3d1"
C_CLIM = "#15803d"
C_GRID = "#e5e7eb"
C_TEXT = "#1f2937"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="60", choices=["60", "NH"])
    ap.add_argument("--init", default="202610", help="init tag, e.g. 202610")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    dom, tag = args.domain, args.init
    init_y, init_m = int(tag[:4]), int(tag[4:6])
    label = "60°N" if dom == "60" else "NH (0–90°N)"
    out = args.out or os.path.join(HERE, "output",
                                   "SEAS5_%s_u10hPa_%s_MWX.png" % (tag, "60N" if dom == "60" else "NH"))

    d = np.load(os.path.join(DATA, "seas5_%s_daily.npz" % tag))
    mem = d["members60"] if dom == "60" else d["members_nh"]
    steps = d["steps"]
    init_dt = datetime(init_y, init_m, 1)
    times = [init_dt + timedelta(hours=int(s)) for s in steps]

    mc = None
    cpath = os.path.join(DATA, "seas5_%s_clim.npz" % tag)
    if os.path.exists(cpath):
        c = np.load(cpath)
        mc = c["clim60"] if dom == "60" else c["clim_nh"]
    m7 = None
    m7path = os.path.join(DATA, "model_clim_m7_month%02d.npz" % init_m)
    if mc is not None and os.path.exists(m7path):
        z = np.load(m7path)
        m7 = z["clim60"] if dom == "60" else z["clim_nh"]

    e = load_era5(dom, init_y)

    fig = plt.figure(figsize=(13.5, 7.2), dpi=150, facecolor="white")
    ax = fig.add_axes([0.062, 0.115, 0.918, 0.715])

    # ---- ERA5 1991-2020 daily climatology layer ---------------------------
    ax.fill_between(e["t"], e["p10"], e["p90"], color=C_BAND_OUT, alpha=0.75, lw=0, zorder=1)
    ax.fill_between(e["t"], e["p30"], e["p70"], color=C_BAND_IN, alpha=0.85, lw=0, zorder=2)
    ax.plot(e["t"], e["rmin"], color=C_RMIN, lw=1.0, ls=(0, (1.5, 2)), zorder=3)
    ax.plot(e["t"], e["rmax"], color=C_RMAX, lw=1.0, ls=(0, (1.5, 2)), zorder=3)
    ax.plot(e["t"], e["mean"], color=C_ERA5, lw=1.7, zorder=4)

    # ---- SEAS5 daily members + ensemble mean ------------------------------
    for i in range(mem.shape[0]):
        ax.plot(times, mem[i], color=C_MEMBER, lw=0.55, alpha=0.45, zorder=5)
    ens = np.nanmean(mem, axis=0)
    ax.plot(times, ens, color=C_MEAN, lw=2.4, zorder=7)

    # ---- ECMWF model-climate mean ----------------------------------------
    if mc is not None and np.isfinite(mc).any():
        mct, mcv = model_climate_curve(init_y, init_m, mc, m7)
        ax.plot(mct, mcv, color=C_CLIM, lw=1.9, zorder=7)

    ax.axhline(0, color="#334155", lw=0.9, ls=(0, (5, 4)), zorder=6)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=C_GRID, lw=0.9)
    ax.xaxis.grid(False)

    ax.set_ylabel("Zonal Wind (m/s) — %s" % label, fontsize=11.5, color=C_TEXT)
    ax.set_xlabel("Valid Days", fontsize=11.5, color=C_TEXT, labelpad=8)
    ax.set_xlim(datetime(init_y, init_m, 1),
                datetime(init_y + (init_m + 6) // 12, (init_m + 6) % 12 + 1, 1))
    ax.xaxis.set_major_locator(mdates.DayLocator(bymonthday=range(1, 29, 14)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator())
    ax.tick_params(axis="x", which="major", labelsize=9.5, colors=C_TEXT, length=4)
    ax.tick_params(axis="x", which="minor", length=2, color="#9ca3af")
    ax.tick_params(axis="y", which="major", labelsize=10, colors=C_TEXT, length=4)
    ax.yaxis.set_minor_locator(matplotlib.ticker.MultipleLocator(5))
    ax.tick_params(axis="y", which="minor", length=2, color="#9ca3af")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#9ca3af")
        ax.spines[side].set_linewidth(0.9)

    handles = [
        Line2D([], [], color=C_MEMBER, lw=0.9, alpha=0.8, label="SEAS5 members (51)"),
        Line2D([], [], color=C_MEAN, lw=2.4, label="Ensemble mean"),
        Line2D([], [], color=C_ERA5, lw=1.7, label="ERA5 daily mean"),
        Line2D([], [], color=C_RMIN, lw=1.0, ls=(0, (1.5, 2)), label="ERA5 record min"),
        Line2D([], [], color=C_RMAX, lw=1.0, ls=(0, (1.5, 2)), label="ERA5 record max"),
        Patch(facecolor=C_BAND_IN, alpha=0.85, label="ERA5 30–70th pct"),
        Patch(facecolor=C_BAND_OUT, alpha=0.75, label="ERA5 10–90th pct"),
        Line2D([], [], color=C_CLIM, lw=1.9, label="Model-climate mean (init %s)" % MONTHS[init_m - 1]),
    ]
    leg = ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 1.005), ncol=4,
                    fontsize=9.6, frameon=False, handlelength=2.6, columnspacing=2.2,
                    labelcolor=C_TEXT)
    leg.set_title("")

    lbl = "%s %d" % (MONTHS[init_m - 1], init_y)
    fig.text(0.062, 0.955, "ECMWF SEAS5  ·  10 hPa  ·  %s Zonal-Mean Zonal Wind (m/s)" % label,
             fontsize=15.5, fontweight="bold", color=C_TEXT, va="center")
    fig.text(0.062, 0.905,
             "Run init 01 %s  ·  215 daily 12Z steps (51 members)  ·  lead months 1–7  ·  "
             "ERA5 climatology 1991–2020" % lbl,
             fontsize=9.8, color="#4b5563", va="center")
    fig.text(0.98, 0.955, "Lead month 7 climate: 2016–2025 re-initialised hindcasts",
             fontsize=8.8, color="#6b7280", ha="right", va="center")
    fig.text(0.062, 0.032,
             "Data: ECMWF seasonal forecasts (CDS) · ERA5 ARCO · lead month 7 model climate "
             "reconstructed from the model's own past runs",
             fontsize=8.2, color="#6b7280", ha="left", va="center")
    fig.text(0.98, 0.032, "@Massachusettswx", fontsize=10.5, fontweight="bold",
             color=C_TEXT, ha="right", va="center")

    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, facecolor="white")
    print("wrote", out)
    print("daily ensemble mean (first 5):", np.round(ens[:5], 2),
          "| (last 5):", np.round(ens[-5:], 2))


if __name__ == "__main__":
    main()
