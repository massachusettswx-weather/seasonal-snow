"""Assemble docs/data/models.json + models_public.json from the rendered assets.

Walks output/ for the rendered snowfall panels (accumulation totals, monthly
totals, monthly anomalies) and output/ for the 10 hPa SPV charts, copies them
into docs/assets/, and writes the registry the site reads.

Run after any re-render:  python3 build_registry.py
"""
import os, re, json, shutil, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
SITE = os.path.join(HERE, "docs")
ASSETS = os.path.join(SITE, "assets")
MAPDIR = os.path.join(ASSETS, "maps")

ENSODIR = os.path.join(SITE, "assets", "enso")
os.makedirs(ENSODIR, exist_ok=True)
SPVDIR = os.path.join(ASSETS, "spv")
DATA = os.path.join(SITE, "data")

FULLMONTHS = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
MONTH_ABBR = {"Jan": "January", "Feb": "February", "Mar": "March",
              "Apr": "April", "May": "May", "Jun": "June", "Jul": "July",
              "Aug": "August", "Sep": "September", "Oct": "October",
              "Nov": "November", "Dec": "December"}


def init_text(init):
    """'1 Nov 2026' for an init like '2026-11'.

    A seasonal run starts on the first of its month, so that is the date
    the cards quote.
    """
    if not init or len(init) < 7:
        return ""
    try:
        m = int(init[5:7])
    except ValueError:
        return ""
    if not 1 <= m <= 12:
        return ""
    abbr = [k for k, v in MONTH_ABBR.items() if v == FULLMONTHS[m - 1]]
    return "1 %s %s" % (abbr[0] if abbr else FULLMONTHS[m - 1], init[:4])

# the model registry: id -> display info
MODELS = {
    "ecmwf-seas5":     ("ECMWF SEAS5",
                        "ECMWF SEAS5 \u00b7 51-member ensemble \u00b7 1\u00b0 global grid \u00b7 init 1 Nov 2026"),
    "ukmo-gloseas6":   ("UKMO GloSeas6-GC5.1",
                        "UK Met Office GloSeas6-GC5.1 \u00b7 ensemble \u00b7 init 1 Oct 2026"),
    "eccc-cansips":    ("ECCC canSIPS",
                        "Environment Canada canSIPS \u00b7 40-member "
                        "multi-model ensemble \u00b7 init 1 Nov 2026 \u00b7 "
                        "CanESM5.1p1bc and GEM5.2-NEMO pooled, twenty members "
                        "each. Both systems run on the same grid and the same "
                        "lead months, so every panel on this card is the mean "
                        "over all forty members and the wind chart shows the "
                        "whole ensemble."),
    "cmcc-sps4":       ("CMCC SPS4",
                        "CMCC SPS4 \u00b7 ensemble \u00b7 init 1 Oct 2026"),
    "dwd-gcfs2":       ("DWD GCFS2.2",
                        "DWD GCFS2.2 \u00b7 ensemble \u00b7 init 1 Oct 2026"),
    "meteo-france-s9": ("METFR System 9",
                        "Meteo-France System 9 \u00b7 ensemble \u00b7 init 1 Oct 2026"),
    "jma-jra3":       ("JMA CPS4",
                        "Japan Meteorological Agency CPS4 seasonal prediction "
                        "system \u00b7 ensemble \u00b7 init 1 Nov 2026 \u00b7 no "
                        "snowfall \u2014 this centre publishes no snowfall field "
                        "in the seasonal archive. The ENSO plume is published; "
                        "the 10 hPa wind is still queued."),
    "bom-access-s2":  ("BOM ACCESS-S2",
                        "Australian Bureau of Meteorology ACCESS-S2 \u00b7 "
                        "ensemble \u00b7 init 1 Nov 2026 \u00b7 no snowfall \u2014 "
                        "this centre publishes no snowfall field in the seasonal "
                        "archive. The ENSO plume is published; the 10 hPa wind "
                        "is still queued."),
    "c3s-multi":       ("C3S Multi-Model Mean", ""),   # filled in below
    "cfsv2":           ("NOAA CFSv2",
                        "NOAA CFSv2 \u00b7 40-member ensemble \u00b7 init 1 Nov 2026 \u00b7 read "
                        "directly from NCEP CPC. The absolute snowfall is ERA5's "
                        "1991-2020 climatology plus the CFSv2 hindcast anomaly "
                        "(an approximation \u2014 CPC publishes the anomaly only). "
                        "The ENSO plume is built from CPC's own published Nino "
                        "indices, so it carries the member spread. "
                        "NOAA publishes no 10 hPa winds, so this model has snowfall "
                        "panels only \u2014 no zonal-wind panel."),
    "ecmwf-s4s":       ("ECMWF Subseasonal",
                        "ECMWF Subseasonal Prediction System (S4S) \u00b7 ensemble "
                        "\u00b7 weekly means out to 46 days \u00b7 read from ECMWF's own "
                        "climate store. A sub-seasonal system: its plume covers the "
                        "first six weeks of the run, not whole seasons."),
    "gefsv12":         ("NOAA GEFSv12",
                        "NOAA GEFS v12 sub-seasonal ensemble \u00b7 31 members "
                        "\u00b7 16 days \u00b7 the polar cap's geopotential "
                        "height anomaly on the same scale as the reanalysis"),
    "ec46":            ("ECMWF EC46",
                        "ECMWF sub-seasonal ensemble (EC46) \u00b7 51 members \u00b7 a "
                        "46-day run, so this section covers the first six weeks of "
                        "the run rather than whole seasons. The polar-cap "
                        "geopotential height is read from ECMWF's own climate "
                        "store, which carries ten pressure levels rather than "
                        "the twelve the seasonal archive carries."),
    "sfsv1":           ("NOAA SFSv1",
                        "Experimental \u00b7 NOAA Seasonal Forecast System v1 \u00b7 31-member "
                        "ensemble \u00b7 0.5\u00b0 grid \u00b7 init 1 Nov 2026 \u00b7 read "
                        "directly from NOAA. SFSv1 is a pre-operational prototype, so its "
                        "panels are marked Experimental. NOAA publishes no 10 hPa winds, "
                        "so this model has snowfall panels only \u2014 no zonal-wind panel."),
}

# The two ECCC systems are pooled into the official canSIPS ensemble, so
# they are one card on the site, not two.  Their own panels are not
# published and their assets are cleared away.
POOLED_INTO = {"eccc-canesm5": "eccc-cansips", "eccc-gem5": "eccc-cansips"}

# the month label for each rendered file, written by plot_snow_models.py
def count_members(tag):
    """How many ensemble members a centre's snowfall actually has.

    The fetch state records the member count for most centres, but not for
    all of them - Meteo-France came through a different path and was left
    blank on the site.  Counting them from the data is the honest answer.
    """
    d = os.path.join(HERE, "data", "models", tag)
    for fn in ("snowfall_monthly.npz", "snowfall_monthly.grib"):
        p = os.path.join(d, fn)
        if not os.path.exists(p):
            continue
        try:
            if fn.endswith(".npz"):
                import numpy as np
                z = np.load(p, allow_pickle=True)
                if "member_numbers" in z.files:
                    return int(len(z["member_numbers"]))
                return int(z["values"].shape[0])
            import eccodes
            mem = set()
            with open(p, "rb") as f:
                while True:
                    try:
                        gid = eccodes.codes_grib_new_from_file(f)
                    except Exception:
                        break
                    if gid is None:
                        break
                    try:
                        mem.add(int(eccodes.codes_get(gid, "number")))
                    except Exception:
                        pass
            if mem:
                return len(mem)
        except Exception:
            pass
    return "?"


def info_of_file(fn):
    """-> {'label': ..., 'lead': ...} for a rendered file."""
    return MANIFEST.get(fn, {"label": "", "lead": 0})


SNOW_TOTAL_RE = re.compile(r"^snow_(?P<tag>[a-z0-9\-]+)_total_run_in(?P<we>_we)?\.png$")
SNOW_MONTH_RE = re.compile(r"^snow_(?P<tag>[a-z0-9\-]+)_month(?P<m>\d{2})_in(?P<we>_we)?\.png$")
SNOW_ANOM_RE = re.compile(
    r"^SNOW_(?P<tag>[A-Z0-9\-]+?)_(?P<mon>January|February|March|April|May|June|July"
    r"|August|September|October|November|December)(?P<yr>\d{4})_anom_in(?P<we>_we)?\.png$")
ENSO_RE = re.compile(r"^ENSO_(?P<tag>[A-Z0-9_]+?)_(?P<basin>Nino3\.4|Nino3|Nino4|Nino1p2)_(?P<kind>ONI|RONI)\.png$")
SPV_RE = re.compile(r"^SPV_(?P<tag>[a-z0-9\-]+)_(?P<dom>60N|NH)\.png$")
TBL_RE = re.compile(r"^SPV_(?P<tag>[a-z0-9\-]+)_(?P<dom>60N|NH)_table\.json$")


MANIFEST = {}


def copy(src, dst):
    shutil.copyfile(src, dst)
    return os.path.relpath(dst, SITE)


def main():
    mp = os.path.join(HERE, "data", "render_manifest.json")
    if os.path.exists(mp):
        MANIFEST.update(json.load(open(mp)))
    os.makedirs(MAPDIR, exist_ok=True)
    os.makedirs(SPVDIR, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)

    reg = {"models": []}
    snow = {}
    enso = {}
    spv = {}

    for fn in sorted(os.listdir(OUT)):
        m = SNOW_TOTAL_RE.match(fn)
        if m:
            d = snow.setdefault(m.group("tag"), {})
            d["total_we" if m.group("we") else "total"] = fn
            continue
        m = SNOW_MONTH_RE.match(fn)
        if m:
            d = snow.setdefault(m.group("tag"), {})
            lst = d.setdefault("months_we" if m.group("we") else "months", [])
            lst.append((int(m.group("m")), fn))
            continue
        m = SNOW_ANOM_RE.match(fn)
        if m:
            tag = m.group("tag").lower()
            d = snow.setdefault(tag, {})
            lst = d.setdefault("anom_we" if m.group("we") else "anom", [])
            lst.append((m.group("mon"), int(m.group("yr")), fn))
            continue
        m = ENSO_RE.match(fn)
        if m:
            tag = m.group("tag").lower().replace("_", "-")
            basin = m.group("basin").replace("Nino3.4", "Nino 3.4").replace(
                "Nino1p2", "Nino 1+2").replace("Nino3", "Nino 3").replace(
                "Nino4", "Nino 4")
            enso.setdefault(tag, {}).setdefault(basin, {})[
                m.group("kind").lower()] = fn
            continue
        m = SPV_RE.match(fn)
        if m:
            spv.setdefault(m.group("tag"), {}).setdefault(m.group("dom"), {})["img"] = fn
            continue
        m = TBL_RE.match(fn)
        if m:
            spv.setdefault(m.group("tag"), {}).setdefault(m.group("dom"), {})["tbl"] = fn

    # per-model member counts and inits, from the fetch state
    fp = os.path.join(HERE, "data", "models_fetched.json")
    fstate = json.load(open(fp)) if os.path.exists(fp) else {}

    # The multi-model mean's card names the systems that actually went into
    # it, which is not the same as every C3S centre - a centre whose data
    # has not arrived is not in the average.
    MULTI_COUNT = 0
    mp = os.path.join(HERE, "data", "multi_members.json")
    if os.path.exists(mp):
        try:
            mm = json.load(open(mp))
            names = [x["name"] for x in mm.get("models", [])]
            if names:
                MODELS["c3s-multi"] = (
                    "C3S Multi-Model Mean",
                    "Mean of %d seasonal systems (%s) \u00b7 init 1 Nov 2026"
                    % (mm.get("count", len(names)), ", ".join(names)))
                # the member count has to match the note - it used to say
                # "6 members" while the note listed nine systems
                MULTI_COUNT = mm.get("count", len(names))
        except Exception:
            pass

    # A note that says what is still missing has to be checked against what
    # has actually arrived: JMA and BoM carried a "the 10 hPa wind is still
    # queued" line long after their wind came down, and a stale note is a
    # lie told to the reader.
    for tag in list(MODELS):
        note = MODELS[tag][1]
        if "the 10 hPa wind is still queued" not in note:
            continue
        if tag in spv and spv.get(tag):
            MODELS[tag] = (MODELS[tag][0],
                           note.replace(
                               "The ENSO plume is published; the 10 hPa wind "
                               "is still queued.",
                               "The ENSO plume and the 10 hPa wind are "
                               "published."))
        else:
            MODELS[tag] = (MODELS[tag][0],
                           note.replace(
                               "The ENSO plume is published; the 10 hPa wind "
                               "is still queued.",
                               "The ENSO plume is published; the 10 hPa wind "
                               "has not come down yet."))

    # The date in a note has to be the date the model is actually on.  The
    # notes used to carry the init that was current when they were written,
    # so a card could claim an October init months after the model had
    # moved to November.  The date is now taken from the model's own data.
    for tag in list(MODELS):
        init = (fstate.get(tag, {}) or {}).get("init")
        txt = init_text(init)
        if not txt:
            continue
        note = re.sub(r"init \d{1,2} [A-Z][a-z]{2,8} \d{4}",
                      "init " + txt, MODELS[tag][1])
        note = re.sub(r"init \d{4}-\d{2}", "init " + txt, note)
        MODELS[tag] = (MODELS[tag][0], note)

    for tag in sorted(snow.keys()):
        if tag in POOLED_INTO:
            # and its panels are not left behind in the published assets
            for fn in os.listdir(OUT):
                if fn.startswith("snow_%s_" % tag) or \
                   fn.startswith("SNOW_%s_" % tag.upper()) or \
                   fn.startswith("SPV_%s_" % tag) or \
                   fn.startswith("ENSO_%s_" % tag.upper().replace("-", "_")):
                    os.remove(os.path.join(OUT, fn))
            for fn in os.listdir(MAPDIR):
                if fn.startswith("snow_%s_" % tag) or \
                   fn.startswith("SNOW_%s_" % tag.upper()):
                    os.remove(os.path.join(MAPDIR, fn))
            for d, pref in ((SPVDIR, "SPV_%s_" % tag),
                            (ENSODIR, "ENSO_%s_" % tag.upper().replace("-", "_"))):
                if os.path.isdir(d):
                    for fn in os.listdir(d):
                        if fn.startswith(pref):
                            os.remove(os.path.join(d, fn))
            continue
        d = snow[tag]
        name, note = MODELS.get(tag, (tag.replace("-", " ").title(), ""))
        st = fstate.get(tag, {})
        nmem = st.get("members", "?")
        if tag == "c3s-multi" and MULTI_COUNT:
            nmem = MULTI_COUNT
        if nmem == "?":
            # count them from the data rather than leave the card blank
            nmem = count_members(tag)
        entry = {
            "id": tag,
            "name": name,
            "note": note,
            "members": nmem,
            "init": st.get("init", "?"),
        }
        if d.get("total"):
            # the window the panels actually cover (init -> the end of the
            # last lead month)
            init = st.get("init", "")
            idate = ("%02d/01/%s" % (int(init[-2:]), init[:4])) if init else ""
            edate = ""
            mlabels = [info_of_file(fn)["label"]
                       for k, fn in sorted(d.get("months", []))]
            if mlabels:
                lab = mlabels[-1]                      # e.g. "June 2027"
                parts = lab.split()
                if not parts:
                    parts = ["January", "2000"]
                mm = None
                for i, (k, v) in enumerate(MONTH_ABBR.items(), start=1):
                    if v.lower() == parts[0].lower():
                        mm = i
                if mm:
                    nxt = mm + 1
                    yr = parts[-1]
                    if nxt > 12:
                        nxt, yr = 1, str(int(yr) + 1)
                    edate = "%02d/01/%s" % (nxt, yr)
            entry["total"] = {
                "file": copy(os.path.join(OUT, d["total"]),
                             os.path.join(MAPDIR, d["total"])),
                "caption": ("Total accumulation %s to %s, in inches."
                            % (idate, edate))
                           if (idate and edate) else
                           ("Total accumulation from the init to the end of the run, "
                            "in inches.")}
        if d.get("months"):
            ms = []
            for k, fn in sorted(d["months"]):
                info = info_of_file(fn)
                ms.append({"label": info["label"],
                           "file": copy(os.path.join(OUT, fn),
                                        os.path.join(MAPDIR, fn)),
                           "caption": "Lead month %d - inches." % info["lead"]})
            entry["months"] = ms
        frames = []
        if d.get("anom"):
            rev = {v: k for k, v in MONTH_ABBR.items()}   # full -> abbr
            bybase = {}
            for (mon, yr, fn) in sorted(d["anom"],
                                        key=lambda a: (a[1], list(MONTH_ABBR).index(rev[a[0]]))):
                info = info_of_file(fn)
                fr = {
                    "label": info["label"] or ("%s %d" % (mon, yr)),
                    "file": copy(os.path.join(OUT, fn), os.path.join(MAPDIR, fn)),
                    "caption": "Lead month %d - anomaly vs this model's own "
                               "hindcast climate, in inches." % info["lead"]}
                frames.append(fr)
                bybase[fn] = fr
        if frames:
            entry["frames"] = frames
        if entry.get("total") or entry.get("frames"):
            reg["models"].append(entry)

    # a model that has ENSO plumes but no snowfall panels (the ECMWF
    # Subseasonal system) still needs its own entry
    have = {e["id"] for e in reg["models"]}
    for tag in sorted(enso):
        if tag in have:
            continue
        if tag in POOLED_INTO:
            continue           # pooled into the canSIPS card
        name, note = MODELS.get(tag, (tag.replace("-", " ").title(), ""))
        st = fstate.get(tag, {})
        reg["models"].append({
            "id": tag,
            "name": name,
            "note": note,
            "members": st.get("members", "?"),
            "init": st.get("init", "?"),
        })

    # a model whose only published product is the polar-cap section (the
    # ECMWF sub-seasonal ensemble, EC46) still needs its own entry
    have = {e["id"] for e in reg["models"]}
    pdir = os.path.join(OUT, "polar_cap")
    if os.path.isdir(pdir):
        for fn in sorted(os.listdir(pdir)):
            if not fn.startswith("polar_cap_") or not fn.endswith(".png"):
                continue
            tag = fn[len("polar_cap_"):-4]
            if tag in have:
                continue
            name, note = MODELS.get(tag, (tag.replace("-", " ").title(), ""))
            nmem = "?"
            init = "?"
            # the numbers come from the series cache itself, so a card is
            # never published with a member count nobody checked
            for zp in (os.path.join(HERE, "data", "polar_model_z.json"),
                       os.path.join(HERE, "data", "polar_ec46_z.json")):
                if not os.path.exists(zp):
                    continue
                try:
                    z = json.load(open(zp)).get(tag) or {}
                except Exception:
                    continue
                if not z:
                    continue
                nmem = z.get("members", "?")
                init = z.get("run") or init
                t = z.get("times") or []
                if t:
                    init = str(t[0])[:10]
                break
            reg["models"].append({
                "id": tag,
                "name": name,
                "note": note,
                "members": nmem,
                "init": init,
            })

    # attach the ENSO plume charts
    for entry in reg["models"]:
        tag = entry["id"]
        ed = enso.get(tag)
        if not ed:
            continue
        order = ["Nino 3.4", "Nino 3", "Nino 4", "Nino 1+2"]
        lst = []
        for b in order:
            d = ed.get(b)
            if not d:
                continue
            for kind in ("oni", "roni"):
                fn = d.get(kind)
                if not fn:
                    continue
                lst.append({
                    "basin": b,
                    "index": kind,
                    "file": copy(os.path.join(OUT, fn), os.path.join(ENSODIR, fn)),
                    "caption": "%s \u00b7 %s %s plume" %
                               (entry["name"], b, kind.upper())})
        if lst:
            entry["enso"] = lst
            entry["enso_ok"] = True

    # attach the SPV panels
    for entry in reg["models"]:
        tag = entry["id"]
        sd = spv.get(tag)
        if not sd:
            continue
        entry["spv"] = {}
        # only the 60 deg N domain is published - the NH (0-90 deg N) option
        # was dropped from the site
        for dom in ("60N",):
            d = sd.get(dom)
            if not d or "img" not in d:
                continue
            info = {
                "file": copy(os.path.join(OUT, d["img"]), os.path.join(SPVDIR, d["img"])),
                "caption": "%s \u00b7 10 hPa zonal-mean zonal wind (%s)"
                           % (entry["name"], "60\u00b0N" if dom == "60N"
                              else "Northern Hemisphere")}
            if "tbl" in d:
                info["table"] = json.load(open(os.path.join(OUT, d["tbl"])))
            entry["spv"]["60" if dom == "60N" else "NH"] = info

    # the polar-cap time-height sections
    POLARDIR = os.path.join(ASSETS, "polar")
    os.makedirs(POLARDIR, exist_ok=True)
    # The ECMWF IFS 15-day section used to be copied here.  It is gone: the
    # section is for the seasonal guidance, and a medium-range forecast is a
    # different product.
    ifs_stale = os.path.join(POLARDIR, "polar_cap_ifs.png")
    if os.path.exists(ifs_stale):
        os.remove(ifs_stale)
        print("   the medium-range polar-cap chart removed")
    for entry in reg["models"]:
        src = os.path.join(OUT, "polar_cap", "polar_cap_%s.png" % entry["id"])
        if not os.path.exists(src):
            continue
        fn = "polar_cap_%s.png" % entry["id"]
        shutil.copyfile(src, os.path.join(POLARDIR, fn))
        entry["polar"] = {
            "file": "assets/polar/" + fn,
            "caption": "Polar cap (60-90N) geopotential height "
                       "anomaly - %s." % entry["name"],
        }

    # Cache-bust every asset URL.  GitHub Pages serves the PNGs with a long
    # cache lifetime, so without a version query the browser keeps showing the
    # previous build even though the files on the server have changed.
    version = time.strftime("%Y%m%d%H%M%S")
    reg["version"] = version

    def bust(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "file" and isinstance(v, str) and "?" not in v:
                    node[k] = "%s?v=%s" % (v, version)
                else:
                    bust(v)
        elif isinstance(node, list):
            for it in node:
                bust(it)

    bust(reg["models"])

    # the medium-range (ECMWF IFS) polar-cap section used to be carried here
    # as a top-level entry.  It is gone: the section is for the seasonal
    # guidance only.
    if "polar_ifs" in reg:
        del reg["polar_ifs"]

    json.dump(reg, open(os.path.join(DATA, "models.json"), "w"), indent=1)

    pub = {"models": []}
    for m in reg["models"]:
        p = dict(m)
        pub["models"].append(p)
    json.dump(pub, open(os.path.join(DATA, "models_public.json"), "w"), indent=1)

    print("registry: %d model(s)" % len(reg["models"]))
    for m in reg["models"]:
        print("  %-16s init=%-8s frames=%-3d months=%-3d total=%-5s spv=%s"
              % (m["id"], m.get("init"), len(m.get("frames", [])),
                 len(m.get("months", [])), bool(m.get("total")),
                 sorted(m.get("spv", {}).keys())))


if __name__ == "__main__":
    main()
