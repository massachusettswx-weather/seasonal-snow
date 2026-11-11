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

# the model registry: id -> display info
MODELS = {
    "ecmwf-seas5":     ("ECMWF SEAS5",
                        "ECMWF SEAS5 \u00b7 51-member ensemble \u00b7 1\u00b0 global grid \u00b7 init 1 Nov 2026"),
    "ukmo-gloseas6":   ("UKMO GloSeas6-GC5.1",
                        "UK Met Office GloSeas6-GC5.1 \u00b7 ensemble \u00b7 init 1 Oct 2026"),
    "eccc-canesm5":    ("ECCC CanESM5.1p1bc",
                        "Environment Canada CanESM5.1p1bc \u00b7 ensemble \u00b7 init 1 Oct 2026"),
    "eccc-gem5":       ("ECCC GEM5.2-NEMO",
                        "Environment Canada GEM5.2-NEMO \u00b7 ensemble \u00b7 init 1 Oct 2026"),
    "cmcc-sps4":       ("CMCC SPS4",
                        "CMCC SPS4 \u00b7 ensemble \u00b7 init 1 Oct 2026"),
    "dwd-gcfs2":       ("DWD GCFS2.2",
                        "DWD GCFS2.2 \u00b7 ensemble \u00b7 init 1 Oct 2026"),
    "meteo-france-s9": ("METFR System 9",
                        "Meteo-France System 9 \u00b7 ensemble \u00b7 init 1 Oct 2026"),
    "jma-jra3":       ("JMA CPS4",
                        "Japan Meteorological Agency CPS4 seasonal prediction "
                        "system \u00b7 ensemble \u00b7 init 1 Nov 2026"),
    "bom-access-s2":  ("BOM ACCESS-S2",
                        "Australian Bureau of Meteorology ACCESS-S2 \u00b7 "
                        "ensemble \u00b7 init 1 Nov 2026"),
    "c3s-multi":       ("C3S Multi-Model Mean", ""),   # filled in below
    "cfsv2":           ("NOAA CFSv2",
                        "NOAA CFSv2 \u00b7 40-member ensemble \u00b7 init 10 Oct 2026 \u00b7 read "
                        "directly from NCEP CPC. The absolute snowfall is ERA5's "
                        "1991-2020 climatology plus the CFSv2 hindcast anomaly "
                        "(an approximation \u2014 CPC publishes the anomaly only). "
                        "NOAA publishes no 10 hPa winds, so this model has snowfall "
                        "panels only \u2014 no zonal-wind panel."),
    "ecmwf-s4s":       ("ECMWF Subseasonal",
                        "ECMWF Subseasonal Prediction System (S4S) \u00b7 ensemble "
                        "\u00b7 weekly means out to 46 days \u00b7 read from ECMWF's own "
                        "climate store. A sub-seasonal system: its plume covers the "
                        "first six weeks of the run, not whole seasons."),
    "sfsv1":           ("NOAA SFSv1",
                        "Experimental \u00b7 NOAA Seasonal Forecast System v1 \u00b7 31-member "
                        "ensemble \u00b7 0.5\u00b0 grid \u00b7 init 1 Nov 2026 \u00b7 read "
                        "directly from NOAA. SFSv1 is a pre-operational prototype, so its "
                        "panels are marked Experimental. NOAA publishes no 10 hPa winds, "
                        "so this model has snowfall panels only \u2014 no zonal-wind panel."),
}

# the month label for each rendered file, written by plot_snow_models.py
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
        except Exception:
            pass

    for tag in sorted(snow.keys()):
        d = snow[tag]
        name, note = MODELS.get(tag, (tag.replace("-", " ").title(), ""))
        st = fstate.get(tag, {})
        entry = {
            "id": tag,
            "name": name,
            "note": note,
            "members": st.get("members", "?"),
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
        name, note = MODELS.get(tag, (tag.replace("-", " ").title(), ""))
        st = fstate.get(tag, {})
        reg["models"].append({
            "id": tag,
            "name": name,
            "note": note,
            "members": st.get("members", "?"),
            "init": st.get("init", "?"),
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
