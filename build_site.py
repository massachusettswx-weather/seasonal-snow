"""Build the static site for the seasonal snow maps.

Reads:
    output/SEAS5_*_snow_anomaly_*.png   the rendered panels
    site/data/systems.json              the CDS seasonal datasets that carry snow
Writes:
    site/index.html
    site/assets/css/style.css
    site/assets/maps/*.png
    site/data/maps.json

Run after any re-render:  python3 build_site.py
"""
import os, re, json, shutil, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
SITE = os.path.join(HERE, "site")
ASSETS = os.path.join(SITE, "assets")
MAPDIR = os.path.join(ASSETS, "maps")
DATA = os.path.join(SITE, "data")

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

PANEL_RE = re.compile(
    r"^SEAS5_(?P<init>\d{6})_snow_anomaly_"
    r"(?:3mo_(?P<win>NDJ|DJF|JFM|FMA)|(?P<mon>Nov|Dec|Jan|Feb|Mar|Apr)(?P<yr>\d{4}))"
    r"(?:_(?P<unit>in|mm))?(?:_(?P<base>hc|era5))?\.png$")


TITLES = {
    "seasonal-monthly-single-levels":
        ("ECMWF SEAS5 / C3S monthly means", "1° global, 51-member ensemble"),
    "seasonal-original-single-levels":
        ("C3S seasonal original single levels", "sub-daily (6-hourly) original data"),
    "seasonal-postprocessed-single-levels":
        ("C3S post-processed single levels", "bias-adjusted anomalies + snow depth"),
    "sis-hydrology-europe-seasonal":
        ("C3S SIS hydrology Europe seasonal", "snow depth water equivalent"),
    "sis-hydrology-europe-seasonal-reforecast":
        ("C3S SIS hydrology Europe reforecast", "snow depth water equivalent"),
}


def collect_panels():
    panels = []
    for fn in sorted(os.listdir(OUT)):
        m = PANEL_RE.match(fn)
        if not m:
            continue
        d = m.groupdict()
        win = d["win"]
        mon = d["mon"] or ""
        yr = int(d["yr"]) if d["yr"] else 0
        if win:
            label = "%s %s" % (win, "2026/27" if win in ("NDJ", "DJF") else "2027")
            kind = "3-month mean"
        else:
            label = "%s %d" % (MONTHS.index(mon) + 1 and mon, yr)
            kind = "monthly"
        unit = d["unit"] or "mm"
        base = d["base"] or "hc"
        panels.append(dict(
            file="assets/maps/" + fn,
            init=d["init"], label=label, kind=kind,
            unit="in w.e." if unit == "in" else "mm w.e.",
            baseline=("ECMWF SEAS5 hindcast climatology" if base == "hc"
                      else "ERA5 1991-2020 snow climatology"),
            window=win or "", month=mon, year=yr))
    return panels


CSS = """
:root{
  --ink:#111; --muted:#5a5f66; --line:#e3e5e8; --teal:#1f4c44;
  --brown:#654116; --accent:#0f6f60; --bg:#fff;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:34px 22px 70px}
header{border-bottom:2px solid var(--ink);padding-bottom:16px;margin-bottom:26px}
h1{font-size:30px;margin:0 0 6px;letter-spacing:-.4px}
h2{font-size:19px;margin:38px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.sub{color:var(--muted);font-size:13.5px}
.credit{float:right;font-weight:700;font-size:14px}
a{color:var(--accent)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px}
.card{border:1px solid var(--line);border-radius:6px;overflow:hidden;background:#fff}
.card img{width:100%;display:block;background:#fff}
.card .meta{padding:10px 13px;border-top:1px solid var(--line)}
.card .t{font-weight:700;font-size:14.5px}
.card .d{color:var(--muted);font-size:12.5px;margin-top:2px}
.sys{border:1px solid var(--line);border-radius:6px;padding:14px 16px;margin-bottom:12px}
.sys .h{display:flex;justify-content:space-between;gap:14px;align-items:baseline}
.sys .name{font-weight:700}
.pill{font-size:11.5px;font-weight:700;padding:2px 9px;border-radius:11px;white-space:nowrap}
.pill.on{background:#e2f1ec;color:var(--teal)}
.pill.plan{background:#f1eee6;color:var(--brown)}
.sys .m{color:var(--muted);font-size:12.5px;margin-top:5px}
code{background:#f4f5f6;padding:1px 5px;border-radius:3px;font-size:12.5px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12.5px;text-transform:uppercase;letter-spacing:.4px}
footer{margin-top:46px;border-top:1px solid var(--line);padding-top:16px;color:var(--muted);font-size:12.5px}
.note{background:#f7f8f8;border-left:3px solid var(--teal);padding:12px 16px;margin:16px 0;font-size:13.5px}
.filters{margin:0 0 16px;display:flex;gap:8px;flex-wrap:wrap}
.filters button{font:inherit;font-size:13px;padding:5px 12px;border:1px solid var(--line);
  border-radius:14px;background:#fff;cursor:pointer;color:var(--muted)}
.filters button.on{background:var(--ink);color:#fff;border-color:var(--ink)}
"""


def build():
    os.makedirs(MAPDIR, exist_ok=True)
    os.makedirs(os.path.join(ASSETS, "css"), exist_ok=True)
    os.makedirs(DATA, exist_ok=True)

    panels = collect_panels()
    # copy only the panels we publish (inches, hindcast-climatology baseline)
    pub = [p for p in panels if p["file"].endswith("_in.png")
           and "hindcast" in p["baseline"]]
    for p in pub:
        src = os.path.join(OUT, os.path.basename(p["file"]))
        shutil.copy2(src, os.path.join(MAPDIR, os.path.basename(src)))
    for stale in os.listdir(MAPDIR):
        if stale not in {os.path.basename(p["file"]) for p in pub}:
            os.remove(os.path.join(MAPDIR, stale))

    with open(os.path.join(DATA, "maps.json"), "w") as f:
        json.dump(pub, f, indent=1)

    systems = []
    sp = os.path.join(DATA, "systems.json")
    if os.path.exists(sp):
        systems = json.load(open(sp))

    with open(os.path.join(ASSETS, "css", "style.css"), "w") as f:
        f.write(CSS)

    inits = sorted({p["init"] for p in pub}, reverse=True)
    cards = []
    for p in sorted(pub, key=lambda q: (q["init"], q["month"], q["window"])):
        cards.append(
            '<figure class="card"><img loading="lazy" src="%s" alt="%s snowfall anomaly">'
            '<figcaption class="meta"><div class="t">%s</div>'
            '<div class="d">%s · %s · vs %s</div></figcaption></figure>'
            % (p["file"], p["label"], p["label"], p["kind"], p["unit"], p["baseline"]))

    sys_html = []
    for s in systems:
        title, note = TITLES.get(s["id"], (s["title"], ""))
        live = s["id"] == "seasonal-monthly-single-levels"
        sys_html.append(
            '<div class="sys"><div class="h"><div class="name">%s</div>'
            '<div><span class="pill %s">%s</span></div></div>'
            '<div class="m">%s%s</div></div>'
            % (title, "on" if live else "plan", "published" if live else "planned",
               note + (" · " if note else ""),
               ("snow variables: " + ", ".join("<code>%s</code>" % v for v in s["snow_variables"]))
               if s["snow_variables"] else "no snow variable"))

    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Seasonal Snow Forecasts &middot; Massachusettswx</title>
<meta name="description" content="Monthly and seasonal snowfall anomaly maps from ECMWF SEAS5 and other seasonal prediction systems.">
<link rel="stylesheet" href="assets/css/style.css">
</head>
<body>
<div class="wrap">
<header>
  <div class="credit">@Massachusettswx</div>
  <h1>Seasonal Snowfall Anomaly Maps</h1>
  <div class="sub">Monthly and three-month snowfall anomalies over the continental United States,
  from ECMWF SEAS5 and other seasonal prediction systems that carry a snow variable.</div>
</header>

<h2>Panels</h2>
<div class="note">Anomaly = seasonal-forecast snowfall minus the corresponding climatology.
  Panels are in <strong>inches of water equivalent</strong> (1&nbsp;in = 25.4&nbsp;mm w.e.).
  Brown = below average, teal = above average. The forecast field is clipped at the
  US/Canada border.</div>
<div class="filters">
  <button class="on" data-f="all">All</button>
  <button data-f="monthly">1-month</button>
  <button data-f="3-month mean">3-month mean</button>
</div>
<div class="cards">
%s
</div>

<h2>Seasonal systems with snow</h2>
%s

<h2>Method</h2>
<table>
<tr><th>Forecast</th><td>ECMWF SEAS5 (C3S system&nbsp;51),
  <code>seasonal-monthly-single-levels</code>, variable <code>snowfall</code>,
  51-member ensemble. Provenance: the mean of the 51 <code>monthly_mean</code>
  members reproduces ECMWF's separately served <code>ensemble_mean</code> product
  to 1.4&times;10<sup>-5</sup> relative.</td></tr>
<tr><th>Climatology</th><td>ECMWF's own <code>hindcast_climate_mean</code> for the
  lead month &mdash; the standard seasonal-anomaly definition. The two fields share the
  same 1&deg; SEAS5 grid, so the difference is taken natively before display
  interpolation.</td></tr>
<tr><th>Resolution</th><td>The CDS seasonal product is 1.00&deg;; the maps are drawn on a
  0.05&deg; display grid with a 0.25&deg; ERA5 hillshade basemap.</td></tr>
<tr><th>Map</th><td>Flat equirectangular projection (x compressed by cos&nbsp;37&deg;N),
  domain 125&deg;W&ndash;65&deg;W / 24.5&deg;N&ndash;50&deg;N, 10&deg; labelled graticule.</td></tr>
<tr><th>Built</th><td>%s</td></tr>
</table>

<footer>Source: Copernicus Climate Change Service (C3S) seasonal forecasts.
  Maps and code by @Massachusettswx. Not an official ECMWF/C3S product.</footer>
</div>
<script>
document.querySelectorAll('.filters button').forEach(function(b){
  b.addEventListener('click', function(){
    document.querySelectorAll('.filters button').forEach(function(x){x.classList.remove('on')});
    b.classList.add('on');
    var f=b.dataset.f;
    document.querySelectorAll('.card').forEach(function(c){
      var t=c.querySelector('.d').textContent;
      c.style.display=(f==='all'||t.indexOf(f)>=0)?'':'none';
    });
  });
});
</script>
</body>
</html>
""" % ("\n".join(cards), "\n".join(sys_html),
       datetime.date.today().isoformat())

    with open(os.path.join(SITE, "index.html"), "w") as f:
        f.write(html)
    print("wrote site/index.html with %d panels (%d published)"
          % (len(panels), len(pub)))


if __name__ == "__main__":
    build()
