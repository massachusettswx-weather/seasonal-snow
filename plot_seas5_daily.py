"""Render the SEAS5 10 hPa zonal-mean zonal wind panel from the DAILY
(subdaily) product - the same construction as the published reference chart:
daily member values (so the ensemble spread carries the real daily
variability), the daily ERA5 1991-2020 climatology layer, and ECMWF's
model-climate mean (HCMEAN).

usage: python3 plot_seas5_daily.py [--domain 60|NH] [--init 202611]
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
    """Daily climatology over the full forecast window (01 Oct of the init year
    -> 10 Jun of the next), keyed by calendar day."""
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


def month_starts(y, m, n):
    out, yy, mm = [], y, m
    for _ in range(n):
        out.append(datetime(yy, mm, 1))
        mm += 1
        if mm > 12:
            mm, yy = 1, yy + 1
    return out


def pchip(x, y, xnew):
    """Monotone cubic Hermite interpolation (Fritsch-Carlson), no scipy."""
    x = np.asarray(x, float); y = np.asarray(y, float)
    n = len(x)
    if n == 1:
        return np.full_like(np.asarray(xnew, float), y[0])
    h = np.diff(x); d = np.diff(y) / h
    m = np.zeros(n)
    m[0] = d[0]; m[-1] = d[-1]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0.0
        else:
            w1 = 2 * h[i] + h[i - 1]; w2 = h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    xnew = np.asarray(xnew, float)
    idx = np.clip(np.searchsorted(x, xnew) - 1, 0, n - 2)
    dx = xnew - x[idx]; h0 = h[idx]
    t = dx / h0
    h00 = 2 * t ** 3 - 3 * t ** 2 + 1; h10 = t ** 3 - 2 * t ** 2 + t
    h01 = -2 * t ** 3 + 3 * t ** 2; h11 = t ** 3 - t ** 2
    return h00 * y[idx] + h10 * h0 * m[idx] + h01 * y[idx + 1] + h11 * h0 * m[idx + 1]


def model_climate_curve(init_y, init_m, mc_monthly, m7=None):
    """Daily ECMWF model-climate curve for the whole window.

    The CDS only publishes the model-climate mean as monthly values (HCMEAN,
    lead months 1-6).  The published chart draws it as a smooth daily curve
    whose monthly means are those HCMEAN values, so the monthly anchors are
    placed at mid-month and interpolated with a monotone cubic.  Lead month 7
    is not published at all; it is reconstructed from the model's own hindcast
    runs (see model_climate_m7.py) and spliced in as the daily curve.
    """
    anchors_x, anchors_y = [], []
    for i, v in enumerate(np.asarray(mc_monthly, float)):
        mm = init_m + i
        yy = init_y + (mm - 1) // 12; mm = (mm - 1) % 12 + 1
        anchors_x.append(datetime(yy, mm, 15).toordinal())
        anchors_y.append(v)
    # window: 1st of the init month .. end of lead month 7
    m0 = datetime(init_y, init_m, 1)
    # lead month 7 starts 6 months after the init month
    m7_start = datetime(init_y + (init_m + 5) // 12, (init_m + 5) % 12 + 1, 1)
    m8_start = datetime(init_y + (init_m + 6) // 12, (init_m + 6) % 12 + 1, 1)
    days = (m8_start - m0).days
    t = np.arange(0, days)
    xnew = np.array([m0.toordinal() + k for k in t], float)
    seg = [(m0, m8_start)]
    if m7 is not None:
        m7 = np.asarray(m7, float)
        apr_mean = float(np.nanmean(m7))
        anchors_x.append(datetime(m7_start.year, m7_start.month, 15).toordinal())
        anchors_y.append(apr_mean)
    curve = pchip(anchors_x, anchors_y, xnew)
    if m7 is not None:
        d0 = (m7_start - m0).days
        n = min(len(m7), days - d0)
        curve[d0:d0 + n] = m7[:n]
    times = [datetime.fromordinal(int(o)) for o in xnew]
    return times, curve


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="60", choices=["60", "NH"])
    ap.add_argument("--init", default="202611", help="init tag, e.g. 202611")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    dom, tag = args.domain, args.init
    init_y, init_m = int(tag[:4]), int(tag[4:6])
    dom_label = {"60": "60N", "NH": "NH"}[dom]
    out = args.out or os.path.join(HERE, "output",
                                   "SEAS5_%s_u10hPa_%s.png" % (tag, dom_label))

    d = np.load(os.path.join(DATA, "seas5_%s_daily.npz" % tag))
    mem = d["members60"] if dom == "60" else d["members_nh"]
    steps = d["steps"]
    init_dt = datetime(init_y, init_m, 1)
    times = [init_dt + timedelta(hours=int(s)) for s in steps]

    # ECMWF model-climate mean (monthly HCMEAN) - only lead months 1-6 exist
    mc = None
    cpath = os.path.join(DATA, "seas5_%s_clim.npz" % tag)
    if os.path.exists(cpath):
        c = np.load(cpath)
        mc = c["clim60"] if dom == "60" else c["clim_nh"]
    # lead month 7 of the model climate (reconstructed from the hindcasts)
    m7 = None
    m7path = os.path.join(DATA, "model_clim_m7_month%02d.npz" % init_m)
    if mc is not None and os.path.exists(m7path):
        z = np.load(m7path)
        m7 = z["clim60"] if dom == "60" else z["clim_nh"]

    e = load_era5(dom, init_y)
    fig, ax = plt.subplots(figsize=(13.6, 7.0), dpi=150)
    fig.subplots_adjust(left=0.065, right=0.985, top=0.885, bottom=0.115)

    # ---- ERA5 1991-2020 climatology (daily) -----------------------------
    ax.fill_between(e["t"], e["p10"], e["p90"], color="#9db8e8", alpha=0.16, lw=0, zorder=1)
    ax.fill_between(e["t"], e["p30"], e["p70"], color="#7ea3e0", alpha=0.30, lw=0, zorder=2)
    ax.plot(e["t"], e["mean"], color="#1f3fd6", lw=1.7, zorder=4)
    ax.plot(e["t"], e["rmin"], color="#1f3fd6", lw=1.2, ls="--", zorder=3)
    ax.plot(e["t"], e["rmax"], color="#e01b1b", lw=1.2, ls="--", zorder=3)

    # ---- SEAS5 daily members + daily ensemble mean ------------------------
    for i in range(mem.shape[0]):
        ax.plot(times, mem[i], color="#8a8a8a", lw=0.55, alpha=0.42, zorder=5)
    ens = np.nanmean(mem, axis=0)
    ax.plot(times, ens, color="black", lw=2.1, zorder=7)

    # ---- ECMWF model-climate mean (daily curve from monthly HCMEAN) ------
    if mc is not None and np.isfinite(mc).any():
        mct, mcv = model_climate_curve(init_y, init_m, mc, m7)
        ax.plot(mct, mcv, color="#e01b1b", lw=2.0, zorder=7)

    ax.axhline(0, color="black", lw=1.2, zorder=6)
    ax.grid(True, ls="--", lw=0.7, color="#c9c9c9", alpha=0.75)
    ax.set_ylabel("U (m/s) at 10 hPa, 60°N" if dom == "60"
                   else "U (m/s) at 10 hPa, NH (0-90N)", fontsize=11)
    ax.set_xlabel("Valid Days", fontsize=11)
    ax.set_xlim(datetime(init_y, init_m, 1),
                datetime(init_y + (init_m + 6) // 12, (init_m + 6) % 12 + 1, 1))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%Y"))
    ax.tick_params(labelsize=10)

    handles = [
        Line2D([], [], color="#8a8a8a", lw=0.9, label="ECMWF Members"),
        Line2D([], [], color="black", lw=2.1, label="ECMWF Mean"),
        Line2D([], [], color="#1f3fd6", lw=1.7, label="ERA5 Average"),
        Line2D([], [], color="#1f3fd6", lw=1.2, ls="--", label="ERA5 Record Min"),
        Line2D([], [], color="#e01b1b", lw=1.2, ls="--", label="ERA5 Record Max"),
        Patch(facecolor="#7ea3e0", alpha=0.30, label="ERA5 30-70th Percentile"),
        Patch(facecolor="#9db8e8", alpha=0.16, label="ERA5 10-90th Percentile"),
        Line2D([], [], color="#e01b1b", lw=2.0,
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
    fig.text(0.985, 0.932, "Model Hindcast Climo: ECMWF HCMEAN", fontsize=9,
             ha="right", va="center", fontweight="bold")
    fig.text(0.5, 0.022,
             "SEAS5 daily 51-member means (init 1 %s)  -  ERA5 daily climatology 1991-2020  -  "
             "lead month 7 climate from 2016-2025 hindcasts  -  "
             "Data: ECMWF/Copernicus CDS, ERA5 ARCO  -  Plot by @Massachusettswx" % lbl,
             fontsize=7.2, ha="center", va="center")

    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, facecolor="white")
    print("wrote", out)
    print("daily ensemble mean (first 8):", np.round(ens[:8], 2))
    print("daily ensemble mean (last 5):", np.round(ens[-5:], 2))


if __name__ == "__main__":
    main()
