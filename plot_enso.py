"""ENSO plumes: the ONI (absolute) and the RONI (relative) index.

Two plume families are drawn for every model and every basin:

  ONI   the sea surface temperature anomaly in the basin, against the
        1991-2020 climatology of the same basin and month - the index the
        ENSO community calls ONI for Nino 3.4;
  RONI  the same anomaly with the tropical-mean (20S-20N) SST anomaly
        subtracted and then rescaled so its spread matches the ONI - the
        Relative Oceanic Nino Index.

The observed analysis is in front of the forecast: NOAA's ERSST v6 - the
dataset CPC builds the ONI and the RONI from - measured against the same
1991-2020 climatology as the model, so the two join.

The forecast is the model's own anomaly (against the model's own hindcast
climate where it is available, so the model's mean SST drift is out of it),
re-levelled so the plume starts at the analysis: without that the plume
starts a whole degree above where the observation ended, which is a level
difference between two climatologies and not a forecast signal.

    python3 plot_enso.py                 # every published model
    python3 plot_enso.py --all           # the staged centres too
"""
import argparse
import calendar
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)
from ecmwf_credit import credit_for  # noqa: E402
import init_info                                # noqa: E402
OUT = os.path.join(HERE, "output")
MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
       "Nov", "Dec"]

MEM = "#f2a3a3"          # ensemble members
MEAN = "#c0272d"         # ensemble mean
FILL = "#e57373"         # the member spread
ANALYSIS = "#111111"     # the observed analysis
GRID = "#ececec"
ZERO = "#8a8a8a"

N_OBS = 12               # how many months of analysis to show

# Every centre that has a plume is published.  ENSO_RELEASE can still restrict
# the list (a comma separated list of tags) if a centre's data is not ready.
RELEASE = os.environ.get("ENSO_RELEASE", "all")
if RELEASE.strip().lower() in ("all", ""):
    RELEASE = []

NAMES = {"ecmwf-seas5": "ECMWF SEAS5", "cmcc-sps4": "CMCC SPS4",
         "dwd-gcfs2": "DWD GCFS2.2", "eccc-cansips": "ECCC canSIPS",
         "ukmo-gloseas6": "UKMO GloSeas6",
         "sfsv1": "NOAA SFSv1", "cfsv2": "NOAA CFSv2",
         "ecmwf-s4s": "ECMWF Subseasonal",
         "jma-jra3": "JMA CPS4", "bom-access-s2": "BOM ACCESS-S2"}
# The two ECCC systems are shown on the site as the official canSIPS
# multi-model ensemble, so they are not plotted on their own.
POOLED_INTO = {"eccc-canesm5": "eccc-cansips", "eccc-gem5": "eccc-cansips"}
NOTES = {"ecmwf-seas5": "C3S seasonal-monthly-single-levels",
         "sfsv1": "NOAA SFSv1 (NODD ocean store)",
         "cfsv2": "NOAA CFSv2 (NCEP CPC)",
         "ecmwf-s4s": "ECMWF Subseasonal (ECMWF Data Store)"}
KINDNAME = {"oni": "ONI", "roni": "RONI"}


# ----------------------------------------------------------------------
# The observed line is the ERSST up to the last complete month and the OI
# SST for the current one.  NOAA's two products do not agree: during the
# current rapid El Nino the OI SST runs up to 0.65 C warmer in the
# eastern equatorial Pacific than the ERSST, and that gap moves from month
# to month.  The OI SST value for the current month is therefore put on
# the ERSST's scale with the mean difference over the last few complete
# months, so the observed line stays continuous, every value on the chart
# still lines up with the published Nino index, and no plume value moves.
LOCAL_BIAS_MONTHS = 3


def load_analysis():
    """The observed line for the plumes.

    The complete months come from NOAA ERSST v6 - the dataset NOAA builds
    the published Nino indices from, so the chart stays on the official
    scale.  The current, still-running month comes from NOAA OI SST v2.1,
    which is produced daily with a one-day latency and is therefore the
    only one of the two that can reach today; it is put on the ERSST's
    scale with the recent difference between the two.  The ERSST tropical
    climatology is kept for the relative index so that nothing about the
    plume moves.
    """
    ers = np.load(os.path.join(DATA, "ersst_enso.npz"), allow_pickle=True)
    op = os.path.join(DATA, "oisst_enso.npz")
    d = {k: ers[k] for k in ers.files}          # the months, tm_clim, k
    d["source"] = "NOAA ERSST v6"
    d["tail_source"] = None
    d["partial"] = None
    if not os.path.exists(op):
        return d
    o = np.load(op, allow_pickle=True)
    if not int(np.asarray(o.get("bias_applied", 0)).ravel()[0]):
        return d
    nd = np.asarray(o["ndays"]) if "ndays" in o.files else None
    last = np.asarray(o["last_day"]) if "last_day" in o.files else None
    if nd is None or last is None or not len(nd):
        return d

    em = [str(m) for m in ers["months"]]
    om = [str(m) for m in o["months"]]
    eb = np.asarray(ers["basin"], float)        # the absolute SST, Celsius
    et = np.asarray(ers["tm"], float)
    ob = np.asarray(o["basin_bc"], float)       # the bias-corrected SST
    ot = np.asarray(o["tm_bc"], float)
    # the months the two products share, aligned at the end: the OI SST
    # carries the ERSST's months plus the current one
    n_over = min(len(em), len(om) - 1)
    if n_over < LOCAL_BIAS_MONTHS:
        return d
    e_sel = np.arange(len(em) - n_over, len(em))
    o_sel = np.arange(len(om) - 1 - n_over, len(om) - 1)
    tail = np.arange(-LOCAL_BIAS_MONTHS, 0)
    d_b = np.mean(ob[o_sel[tail]] - eb[e_sel[tail]], axis=0)
    d_t = float(np.mean(ot[o_sel[tail]] - et[e_sel[tail]]))

    # the observed series: the ERSST's months, then the current month
    d["basin"] = np.vstack([eb, (ob[-1] - d_b)[None, :]])
    d["tm"] = np.append(et, ot[-1] - d_t)
    d["months"] = np.array(em + [om[-1]])
    d["source"] = "NOAA ERSST v6"
    d["tail_source"] = "NOAA OI SST v2.1"
    d["local_bias_basin"] = d_b
    d["local_bias_tm"] = d_t
    # the current month is incomplete: how many days it stands on
    d["partial"] = (str(om[-1]), int(nd[-1]), str(last[-1]))
    return d


def load():
    clim = np.load(os.path.join(DATA, "era5_enso_clim.npz"), allow_pickle=True)
    ana = load_analysis()
    models = {}
    d = os.path.join(DATA, "models")
    for tag in sorted(os.listdir(d)):
        q = os.path.join(d, tag, "enso.json")
        if os.path.exists(q):
            rec = json.load(open(q))
            if rec.get("kind") == "s4s" and "weeks" in rec:
                # the sub-seasonal system runs in weeks, not months
                rec["months"] = list(rec["weeks"])
            # the extra lead months (the monthly product stops at 6)
            ext = os.path.join(d, tag, "sst_extended.npz")
            if os.path.exists(ext):
                z = np.load(ext, allow_pickle=True)
                em = [str(m) for m in z["months"]]
                eb = z["basin"]
                et = z["tropical"]
                have = set(rec["months"])
                for i, m in enumerate(em):
                    if m in have:
                        continue
                    rec["months"].append(m)
                    for j, b in enumerate(rec["basins"]):
                        rec["series"][b].append([float(v) for v in eb[i][j]])
                    rec.setdefault("tropical", []).append(
                        [float(v) for v in et[i]])
                rec["extended"] = em
            # the model's own hindcast climate (the drift correction)
            hc = os.path.join(d, tag, "sst_hindcast.npz")
            if os.path.exists(hc):
                z = np.load(hc, allow_pickle=True)
                rec["hindcast"] = {"months": [str(m) for m in z["months"]],
                                   "basin": z["basin"], "tropical": z["tropical"]}
            models[tag] = rec
    return clim, ana, models


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


def model_series(rec, clim, tm_clim):
    """-> ({basin: [per month: [member anomaly]]}, [per month: [member TM anomaly]]).

    The anomaly is against the model's OWN hindcast climate when it is
    available (that removes the model's mean SST drift); otherwise against
    the ERA5 1991-2020 climatology.  The CFSv2 comes from CPC as an anomaly
    already.
    """
    months = rec["months"]
    basins = rec["basins"]
    trop = rec.get("tropical") or []
    if rec.get("kind") == "noaa-anom":
        out = {b: [list(rec["series"][b][i]) for i in range(len(months))]
               for b in basins}
        return out, [list(t) for t in trop]
    hc = rec.get("hindcast")
    hcm = {m: i for i, m in enumerate(hc["months"])} if hc else {}
    out = {}
    for bi, b in enumerate(basins):
        rows = []
        for i, m in enumerate(months):
            if m in hcm:
                c = float(hc["basin"][hcm[m]][bi]) - 273.15
            else:
                c = float(clim["sst"][int(m[5:7]) - 1][bi]) - 273.15
            rows.append([float(v) - 273.15 - c for v in rec["series"][b][i]])
        out[b] = rows
    trows = []
    for i, m in enumerate(months):
        if hc and m in hcm:
            c = float(hc["tropical"][hcm[m]]) - 273.15
        else:
            c = float(tm_clim[int(m[5:7]) - 1])
        trows.append([float(v) - 273.15 - c
                      for v in (trop[i] if i < len(trop) else [])])
    return out, trows


def label(ym):
    m = int(ym[5:7])
    return MON[m] + ("\n%d" % int(ym[:4]) if m == 1 else "")


def init_label(init):
    y, m = int(init[:4]), int(init[5:7])
    d = int(init[8:10]) if len(init) > 7 else 1
    return "%02d/%02d/%04d" % (m, d, y)


def _ord(dstr):
    """A date string -> its day number (for the weekly axis)."""
    import datetime as _dt
    return _dt.date.fromisoformat(dstr).toordinal()


def plot_basin(tag, name, rec, clim, ana, basin, kind, k, init):
    months = rec["months"]
    bi = rec["basins"].index(basin)
    ana_src = ana.get("source", "NOAA ERSST v6")
    tail_src = ana.get("tail_source")

    # the analysis file may be in Kelvin (ERA5) or Celsius (ERSST)
    kshift = 273.15 if float(np.nanmedian(ana["basin"])) > 100.0 else 0.0
    # the tropical-mean climatology of the analysis dataset, in Celsius
    tm_clim = np.asarray(ana["tm_clim"], float) - kshift
    banom, tanom = model_series(rec, clim, tm_clim)

    # the forecast
    fc = banom[basin]
    if kind == "roni":
        fc = [[(b - t) * k for b, t in zip(fc[i], tanom[i])]
              for i in range(len(months))]

    # the analysis, measured against the same 1991-2020 climatology as the
    # model so the observed line and the plume join
    om = [str(m) for m in ana["months"]]
    oa = np.asarray(ana["basin"], float)[:, bi] - kshift
    for i, m in enumerate(om):
        oa[i] -= float(clim["sst"][int(m[5:7]) - 1][bi]) - 273.15
    ota = np.asarray(ana["tm"], float) - kshift - tm_clim[
        np.array([int(m[5:7]) - 1 for m in om])]
    if kind == "roni":
        oa = (oa - ota) * k
    nobs = 6 if rec.get("kind") == "s4s" else N_OBS
    keep = [i for i in range(len(om)) if om[i] <= months[-1]][-nobs:]
    obs_m = [om[i] for i in keep]
    obs_v = [float(oa[i]) for i in keep]

    arr = np.array([np.asarray(v, float) for v in fc])
    # re-level the plume so it starts where the analysis ended: without this
    # the forecast sits a whole degree above the observation, which is the
    # difference between two climatologies and not a forecast signal
    offset = float(arr[0].mean()) - obs_v[-1]
    arr = arr - offset

    weekly = rec.get("kind") == "s4s"
    if weekly:
        # the sub-seasonal system: the analysis is monthly, the forecast is
        # weekly, so the axis is a real date axis
        xs = [_ord(m + "-01") for m in obs_m]
        xf = [_ord(w) for w in months]
        ticks = [(x, label(m)) for x, m in zip(xs, obs_m)]
        for w, x in zip(months, xf):
            d = int(w[8:10])
            ticks.append((x, "%d\n%s" % (d, MON[int(w[5:7])])))
        ticks.sort()
        tpos = [t[0] for t in ticks]
        labels = [t[1] for t in ticks]
        pos = {w: x for w, x in zip(months, xf)}
    else:
        # one continuous month axis
        axis = sorted(set(obs_m) | set(months))
        pos = {m: i for i, m in enumerate(axis)}
        xs = [pos[m] for m in obs_m]
        xf = [pos[m] for m in months]
        labels = [label(m) for m in axis]
        tpos = list(range(len(axis)))

    fig, ax = plt.subplots(figsize=(10.4, 4.5), dpi=130)
    nmem = arr.shape[1]
    for j in range(nmem):
        ax.plot(xf, arr[:, j], color=MEM, lw=0.7, alpha=0.75, zorder=2,
                label=("members" if (j == 0 and nmem > 1) else None))
    mean = arr.mean(axis=1)
    ax.fill_between(xf, arr.min(axis=1), arr.max(axis=1), color=FILL,
                    alpha=0.16, lw=0, zorder=1)
    ax.plot(xf, mean, color=MEAN, lw=2.6, zorder=3,
            label="ensemble mean" if nmem > 1 else "ensemble mean (CPC)")
    # the analysis on top
    #
    # The current month is incomplete - the observation is a running mean
    # over the days published so far - so it is drawn as an open marker of
    # its own rather than pretending to be a whole month.
    part = ana.get("partial")
    ipart = None
    if part and part[0] == obs_m[-1]:
        ipart = len(obs_m) - 1
    if ipart is None:
        ax.plot(xs, obs_v, color=ANALYSIS, lw=2.4, marker="o", ms=3.4,
                label="analysis (%s)" % ana_src, zorder=4)
    else:
        ax.plot(xs[:ipart], obs_v[:ipart], color=ANALYSIS, lw=2.4,
                marker="o", ms=3.4, label="analysis (%s)" % ana_src, zorder=4)
        ax.plot(xs[ipart], obs_v[ipart], color=ANALYSIS, lw=0, marker="o",
                ms=5.6, mfc="white", mec=ANALYSIS, mew=1.8, zorder=5,
                label=("the current month, %s, a running mean" % tail_src
                       if tail_src else "the current month, a running mean"))
    ax.axhline(0, color=ZERO, lw=1.0, ls="--", zorder=1)

    # the init marker
    if weekly:
        if len(init) > 7:
            xi = _ord(init)
            ax.axvline(xi, color="#b9b9b9", lw=1.0, zorder=1)
            ax.text(xi + 1.5, 0.02, "init %s" % init_label(init),
                    transform=ax.get_xaxis_transform(), fontsize=8,
                    color="#777777", va="bottom")
    elif init in pos:
        ax.axvline(pos[init], color="#b9b9b9", lw=1.0, zorder=1)
        ax.text(pos[init] + 0.15, 0.02, "init %s" % init_label(init),
                transform=ax.get_xaxis_transform(), fontsize=8,
                color="#777777", va="bottom")

    ax.set_xticks(tpos)
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
    elif rec.get("kind") == "s4s":
        mdesc = "%d members \u00b7 weekly means" % nmem
    else:
        mdesc = "%d members" % nmem
    if part and part[0] == obs_m[-1]:
        _d = part[2]
        endtxt = "%s %s (%d-day mean)" % (int(_d[8:10]), MON[int(_d[5:7])],
                                          part[1])
        # the line runs the ERSST up to the last complete month and the OI
        # SST for the current one, so both are named
        _p = obs_m[-2] if len(obs_m) > 1 else obs_m[-1]
        _py, _pm = int(_p[:4]), int(_p[5:7])
        _ptxt = "%s %d" % (MON[_pm], calendar.monthrange(_py, _pm)[1])
        ana_txt = ("analysis %s to %s, %s to %s" % (ana_src, _ptxt,
                                                   tail_src or ana_src,
                                                   endtxt))
    else:
        endtxt = obs_m[-1] if obs_m else "-"
        ana_txt = "analysis %s to %s" % (ana_src, endtxt)
    desc_t = ax.text(0, 1.02,
                     "init %s · %s · SST anomaly vs 1991-2020 · %s" %
                     (init_label(init), mdesc, ana_txt),
                     transform=ax.transAxes, fontsize=8.6, color="#6b6b6b",
                     va="bottom")
    stamp_t = ax.text(0.995, 1.02, "max %+.2f / min %+.2f °C" % (float(mean.max()),
                                                                 float(mean.min())),
                      transform=ax.transAxes, fontsize=9, color="#555555",
                      ha="right", va="bottom")
    # the descriptor and the max/min stamp must never collide: the
    # descriptor is measured and shrunk until it clears the stamp
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    for _ in range(12):
        db = desc_t.get_window_extent(rend)
        sb = stamp_t.get_window_extent(rend)
        if db.x1 <= sb.x0 + 4.0:
            break
        fs = desc_t.get_fontsize()
        if fs <= 6.0:
            break
        desc_t.set_fontsize(fs - 0.35)
        fig.canvas.draw()
    leg = ax.legend(loc="upper left", fontsize=8, frameon=False, ncol=3,
                    handlelength=1.8, columnspacing=1.2)
    for t in leg.get_texts():
        t.set_color("#444444")
    fig.text(0.995, 0.075, "@Massachusettswx", ha="right", va="bottom",
             fontsize=11, fontweight="bold")
    credit = credit_for(tag)
    if credit:
        # the ECMWF's own attribution, on the bottom right inside the graphic
        # 6.5 pt so it clears the data-source line on the left
        fig.text(0.995, 0.014, credit, ha="right", va="bottom",
                 fontsize=6.5, color="#8a8a8a")
    # the analysis source is named in the descriptor above, so the footer
    # keeps only the data source and the note about the anchoring
    fig.text(0.005, 0.014, "Data: %s · forecast anchored to the analysis"
             % (NOTES.get(tag, rec.get("note", "C3S seasonal"))),
             ha="left", va="bottom", fontsize=7.6, color="#8a8a8a")
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    fn = "ENSO_%s_%s_%s.png" % (tag.upper().replace("-", "_"),
                                basin.replace(" ", "").replace("+", "p"),
                                kind.upper())
    fig.savefig(os.path.join(OUT, fn))
    plt.close(fig)
    print("  %-46s analysis %s..%s  forecast %s..%s  members %d  "
          "anchor %+.2f" % (fn, obs_m[0] if obs_m else "-",
                            obs_m[-1] if obs_m else "-", months[0], months[-1],
                            nmem, -offset), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="also render the staged centres")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    clim, ana, models = load()
    k = renormalisation(ana)
    print("relative-index rescaling factor k = %.3f" % k, flush=True)

    for tag, rec in sorted(models.items()):
        if tag in POOLED_INTO:
            # pooled into the official canSIPS ensemble - its own plume is
            # not published
            continue
        if not args.all and RELEASE and tag not in RELEASE:
            print("== %s: staged, not published yet" % tag, flush=True)
            continue
        name = NAMES.get(tag, tag)
        init = rec.get("init") or init_info.recorded_init(tag)
        print("== %s (%s, init %s, %d months)" %
              (tag, name, init, len(rec["months"])), flush=True)
        for basin in rec["basins"]:
            for kind in ("oni", "roni"):
                plot_basin(tag, name, rec, clim, ana, basin, kind, k, init)


if __name__ == "__main__":
    main()
