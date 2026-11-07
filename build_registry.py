"""Assemble site/data/models.json + models_public.json from the rendered assets.

Walks output/ for the rendered snowfall panels (accumulation totals, monthly
totals, monthly anomalies) and output/ for the 10 hPa SPV charts, copies them
into site/assets/, and writes the registry the site reads.

Run after any re-render:  python3 build_registry.py
"""
import os, re, json, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
SITE = os.path.join(HERE, "site")
ASSETS = os.path.join(SITE, "assets")
MAPDIR = os.path.join(ASSETS, "maps")
SPVDIR = os.path.join(ASSETS, "spv")
DATA = os.path.join(SITE, "data")

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
FULL = ["January", "February", "March", "April", "May", "June", "July",
        "August", "September", "October", "November", "December"]
FULLM = {"Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April",
         "May": "May", "Jun": "June", "Jul": "July", "Aug": "August",
         "Sep": "September", "Oct": "October", "Nov": "November",
         "Dec": "December"}

# model id -> (display name, note)
MODELS = {
    "ecmwf-seas5": ("ECMWF SEAS5",
                    "System 51 \u00b7 51-member ensemble \u00b7 1\u00b0 global grid "
                    "\u00b7 7 lead months"),
}

SNOW_RE = re.compile(r"^snow_(?P<tag>[a-z0-9\-]+)_total_run_in\.png$")
MONTH_RE = re.compile(r"^snow_(?P<tag>[a-z0-9\-]+)_month(?P<m>\d{2})_in\.png$")
ANOM_RE = re.compile(
    r"^SEAS5_(?P<init>\d{6})_snow_anomaly_(?P<mon>Nov|Dec|Jan|Feb|Mar|Apr)(?P<yr>\d{4})_in\.png$")
ANOM3_RE = re.compile(
    r"^SEAS5_(?P<init>\d{6})_snow_anomaly_3mo_(?P<win>NDJ|DJF|JFM|FMA)_in\.png$")
SPV_RE = re.compile(r"^SPV_(?P<tag>[a-z0-9\-]+)_(?P<dom>60N|NH)\.png$")
TBL_RE = re.compile(r"^SPV_(?P<tag>[a-z0-9\-]+)_(?P<dom>60N|NH)_table\.json$")


def copy(src, dst):
    shutil.copyfile(src, dst)
    return os.path.relpath(dst, SITE)


def main():
    os.makedirs(MAPDIR, exist_ok=True)
    os.makedirs(SPVDIR, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)

    reg = {"models": []}
    # ---------------- snowfall ----------------
    snow_tags = {}
    for fn in sorted(os.listdir(OUT)):
        m = SNOW_RE.match(fn)
        if m:
            snow_tags.setdefault(m.group("tag"), {})["total"] = fn
        m = MONTH_RE.match(fn)
        if m:
            snow_tags.setdefault(m.group("tag"), {}).setdefault("months", []).append(
                (int(m.group("m")), fn))
        m = ANOM_RE.match(fn)
        if m:
            snow_tags.setdefault("ecmwf-seas5", {}).setdefault("anom", []).append(
                (m.group("mon"), int(m.group("yr")), fn))
        m = ANOM3_RE.match(fn)
        if m:
            snow_tags.setdefault("ecmwf-seas5", {}).setdefault("anom3", []).append(
                (m.group("win"), fn))

    # ---------------- spv ----------------
    spv_tags = {}
    for fn in sorted(os.listdir(OUT)):
        m = SPV_RE.match(fn)
        if m:
            spv_tags.setdefault(m.group("tag"), {}).setdefault(m.group("dom"), {})["img"] = fn
        m = TBL_RE.match(fn)
        if m:
            spv_tags.setdefault(m.group("tag"), {}).setdefault(m.group("dom"), {})["tbl"] = fn

    for tag, d in sorted(snow_tags.items()):
        name, note = MODELS.get(tag, (tag.replace("-", " ").title(), ""))
        entry = {"id": tag, "name": name, "note": note, "members": 51, "init": "2026-11"}
        total = d.get("total")
        if total:
            entry["total"] = {
                "file": copy(os.path.join(OUT, total), os.path.join(MAPDIR, total)),
                "caption": "Total accumulation from the 1 November 2026 init to the end "
                           "of the run (6 lead months)."}
        if d.get("months"):
            ms = []
            for k, fn in sorted(d["months"]):
                cm = (9 + k) % 12           # lead 1 = November 2026
                yr = 2026 + (9 + k) // 12
                ms.append({"label": "%s %d" % (FULL[cm], yr),
                           "file": copy(os.path.join(OUT, fn), os.path.join(MAPDIR, fn)),
                           "caption": "Lead month %d" % k})
            entry["months"] = ms
        frames = []
        if d.get("anom"):
            order = ["Nov", "Dec", "Jan", "Feb", "Mar", "Apr"]
            amap = {a[0]: a for a in d["anom"]}
            for i, mon in enumerate(order):
                if mon in amap:
                    _, yr, fn = amap[mon]
                    frames.append({
                        "label": "%s %d" % (FULLM[mon], yr),
                        "file": copy(os.path.join(OUT, fn), os.path.join(MAPDIR, fn)),
                        "caption": "Lead month %d anomaly vs the ECMWF hindcast climate."
                                   % (i + 1)})
        if d.get("anom3"):
            wmap = dict(d["anom3"])
            for win in ("NDJ", "DJF", "JFM", "FMA"):
                fn = wmap.get(win)
                if not fn:
                    continue
                frames.append({
                    "label": "%s (3-month mean)" % win,
                    "file": copy(os.path.join(OUT, fn), os.path.join(MAPDIR, fn)),
                    "caption": "Three-month mean anomaly vs the ECMWF hindcast climate."})
        if frames:
            entry["frames"] = frames
        if entry.get("total") or entry.get("frames"):
            reg["models"].append(entry)

    # ---------------- spv attach ----------------
    for entry in reg["models"]:
        tag = entry["id"]
        sd = spv_tags.get(tag)
        if not sd:
            continue
        entry["spv"] = {}
        for dom in ("60N", "NH"):
            d = sd.get(dom)
            if not d or "img" not in d:
                continue
            info = {"file": copy(os.path.join(OUT, d["img"]),
                                 os.path.join(SPVDIR, d["img"])),
                    "caption": "%s \u00b7 10 hPa zonal-mean zonal wind (%s)"
                               % (entry["name"], "60\u00b0N" if dom == "60N"
                                  else "Northern Hemisphere")}
            if "tbl" in d:
                t = json.load(open(os.path.join(OUT, d["tbl"])))
                info["table"] = t
            entry["spv"]["60" if dom == "60N" else "NH"] = info

    json.dump(reg, open(os.path.join(DATA, "models.json"), "w"), indent=1)

    # the public copy strips anything the browser does not need
    pub = {"models": []}
    for m in reg["models"]:
        p = dict(m)
        p.pop("members", None)
        pub["models"].append(p)
    json.dump(pub, open(os.path.join(DATA, "models_public.json"), "w"), indent=1)

    print("registry: %d model(s)" % len(reg["models"]))
    for m in reg["models"]:
        print("  %-14s frames=%d months=%d total=%s spv=%s"
              % (m["id"], len(m.get("frames", [])), len(m.get("months", [])),
                 bool(m.get("total")), sorted(m.get("spv", {}).keys())))


if __name__ == "__main__":
    main()
