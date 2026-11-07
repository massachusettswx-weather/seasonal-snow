"""Generic 10 hPa zonal-mean zonal wind (SPV) renderer for the seasonal site.

Same house style as plot_seas5_mwx.py but parameterised so every seasonal
system can be drawn the same way:

  * daily ensemble-member traces
  * daily ensemble mean
  * ERA5 1991-2020 daily climatology, percentile bands and record bounds
  * the system's own model-climate mean where it is available

The module exposes render_spv() so build_site.py can call it for each model.
"""
import os, sys, json
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

def unent(s):
    """Matplotlib draws literal text, so decode the HTML entities used in the
    site copy back into real characters."""
    if not isinstance(s, str):
        return s
    for a, b in (("&middot;", "\u00b7"), ("&ndash;", "\u2013"), ("&mdash;", "\u2014"),
                 ("&deg;", "\u00b0"), ("&nbsp;", " "), ("&amp;", "&"),
                 ("&ndash;", "\u2013"), ("&rarr;", "\u2192"), ("&times;", "\u00d7"),
                 ("&plusmn;", "\u00b1"), ("&le;", "\u2264"), ("&ge;", "\u2265")):
        s = s.replace(a, b)
    return s


MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def load_era5(domain, init_year):
    """ERA5 1991-2020 daily climatology layer for the init year."""
    from plot_seas5_daily import load_era5 as _le
    return _le(domain, init_year)


def render_spv(members, times, model_name, out_path, domain="60",
               era5=None, model_clim=None, model_clim_label=None,
               n_members=None, subtitle=None, footer=None, title=None):
    """members: [member, day]; times: list of datetime."""
    label = "60°N" if domain == "60" else "NH (0–90°N)"
    mem = np.asarray(members, dtype=float)
    if mem.ndim == 1:
        mem = mem[None, :]
    if era5 is None:
        era5 = load_era5(domain, times[0].year)
    nmem = n_members if n_members is not None else mem.shape[0]

    fig = plt.figure(figsize=(13.5, 7.2), dpi=150, facecolor="white")
    ax = fig.add_axes([0.062, 0.115, 0.918, 0.715])

    ax.fill_between(era5["t"], era5["p10"], era5["p90"], color=C_BAND_OUT,
                    alpha=0.75, lw=0, zorder=1)
    ax.fill_between(era5["t"], era5["p30"], era5["p70"], color=C_BAND_IN,
                    alpha=0.85, lw=0, zorder=2)
    ax.plot(era5["t"], era5["rmin"], color=C_RMIN, lw=1.0, ls=(0, (1.5, 2)), zorder=3)
    ax.plot(era5["t"], era5["rmax"], color=C_RMAX, lw=1.0, ls=(0, (1.5, 2)), zorder=3)
    ax.plot(era5["t"], era5["mean"], color=C_ERA5, lw=1.7, zorder=4)

    # the model series and the ERA5 layer can have different lengths (daily
    # model vs. a clipped climatology window), so each is plotted on its own
    # axis
    tser = list(times[:mem.shape[1]])
    for i in range(mem.shape[0]):
        ax.plot(tser, mem[i], color=C_MEMBER, lw=0.55, alpha=0.45, zorder=5)
    ens = np.nanmean(mem, axis=0)
    ax.plot(tser, ens, color=C_MEAN, lw=2.4, zorder=7)

    mc_ok = False
    if model_clim is not None:
        try:
            mc_ok = bool(np.isfinite(model_clim[1]).any())
        except Exception:
            mc_ok = False
    if mc_ok:
        mct, mcv = model_clim
        ax.plot(mct, mcv, color=C_CLIM, lw=1.9, zorder=7)

    ax.axhline(0, color="#334155", lw=0.9, ls=(0, (5, 4)), zorder=6)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=C_GRID, lw=0.9)
    ax.xaxis.grid(False)

    ax.set_ylabel("Zonal Wind (m/s) — %s" % label, fontsize=11.5, color=C_TEXT)
    ax.set_xlabel("Valid Days", fontsize=11.5, color=C_TEXT, labelpad=8)
    x0 = min(times[0], era5["t"][0])
    x1 = max(times[-1], era5["t"][-1])
    ax.set_xlim(x0, x1)
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
        Line2D([], [], color=C_MEMBER, lw=0.9, alpha=0.8, label="Members (%d)" % nmem),
        Line2D([], [], color=C_MEAN, lw=2.4, label="Ensemble mean"),
        Line2D([], [], color=C_ERA5, lw=1.7, label="ERA5 daily mean"),
        Line2D([], [], color=C_RMIN, lw=1.0, ls=(0, (1.5, 2)), label="ERA5 record min"),
        Line2D([], [], color=C_RMAX, lw=1.0, ls=(0, (1.5, 2)), label="ERA5 record max"),
        Patch(facecolor=C_BAND_IN, alpha=0.85, label="ERA5 30–70th pct"),
        Patch(facecolor=C_BAND_OUT, alpha=0.75, label="ERA5 10–90th pct"),
    ]
    if mc_ok:
        handles.append(Line2D([], [], color=C_CLIM, lw=1.9,
                              label=unent(model_clim_label or "Model-climate mean")))
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 1.005), ncol=4,
              fontsize=9.6, frameon=False, handlelength=2.6, columnspacing=2.2,
              labelcolor=C_TEXT)

    fig.text(0.062, 0.955,
             unent(title or ("%s  \u00b7  10 hPa  \u00b7  %s Zonal-Mean Zonal Wind (m/s)" % (model_name, label))),
             fontsize=15.5, fontweight="bold", color=C_TEXT, va="center")
    fig.text(0.062, 0.905, unent(subtitle or ""), fontsize=9.8, color="#4b5563", va="center")
    fig.text(0.062, 0.032, unent(footer or ""), fontsize=8.2, color="#6b7280",
             ha="left", va="center")
    fig.text(0.98, 0.032, "@Massachusettswx", fontsize=10.5, fontweight="bold",
             color=C_TEXT, ha="right", va="center")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, facecolor="white")
    plt.close(fig)
    return out_path
