"""Build the static site for the seasonal forecast graphics.

Pages
    index.html    home: pick a seasonal model, then pick what to look at
    snow.html     snowfall page: end-of-run total, monthly totals, monthly
                  anomalies (with a drag bar), for every model that does snow
    spv.html      10 hPa zonal-mean zonal wind, one panel per model

Data
    site/data/models.json   the model registry (name, members, init, panels)
    site/data/frames.json   the drag-bar frames for the snowfall page

Run after any re-render:  python3 build_site.py
"""
import os, re, json, shutil, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
SITE = os.path.join(HERE, "site")
ASSETS = os.path.join(SITE, "assets")
MAPDIR = os.path.join(ASSETS, "maps")
SPVDIR = os.path.join(ASSETS, "spv")
DATA = os.path.join(SITE, "data")

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
FULLMONTHS = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]


# --------------------------------------------------------------------------
# model registry
# --------------------------------------------------------------------------
def load_registry():
    """The registry is maintained by hand in site/data/models.json; this reads
    it and validates that every referenced asset exists."""
    p = os.path.join(DATA, "models.json")
    if not os.path.exists(p):
        return {"models": []}
    reg = json.load(open(p))
    for m in reg.get("models", []):
        m["snow_ok"] = False
        m["spv_ok"] = False
        for fr in m.get("frames", []):
            if os.path.exists(os.path.join(SITE, fr["file"])):
                fr["ok"] = True
                m["snow_ok"] = True
        if m.get("spv"):
            for dom, info in m["spv"].items():
                if os.path.exists(os.path.join(SITE, info["file"])):
                    info["ok"] = True
                    m["spv_ok"] = True
    return reg


# --------------------------------------------------------------------------
# css
# --------------------------------------------------------------------------
CSS = """
:root{
  --ink:#12151a; --muted:#5b6472; --line:#e3e7ee; --bg:#f6f7f9;
  --card:#ffffff; --accent:#12263f; --accent2:#c2410c;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  color:var(--ink); background:var(--bg); line-height:1.45;
}
header.top{
  background:var(--accent); color:#fff; padding:18px 26px;
  display:flex; align-items:baseline; gap:16px; flex-wrap:wrap;
}
header.top h1{font-size:20px; margin:0; font-weight:700; letter-spacing:.2px}
header.top .sub{font-size:12.5px; color:#9fb0c6}
header.top .spacer{flex:1}
header.top a{color:#cfe0f5; text-decoration:none; font-size:13px}
header.top a:hover{text-decoration:underline}
nav.tabs{background:#fff; border-bottom:1px solid var(--line); padding:0 26px;
  display:flex; gap:4px}
nav.tabs a{
  display:inline-block; padding:11px 16px; font-size:13.5px; text-decoration:none;
  color:var(--muted); border-bottom:2px solid transparent; font-weight:600;
}
nav.tabs a:hover{color:var(--ink)}
nav.tabs a.active{color:var(--accent); border-bottom-color:var(--accent)}
.wrap{max-width:1280px; margin:0 auto; padding:22px 26px 60px}
.card{background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:18px 20px; margin-bottom:18px}
h2.sec{font-size:16.5px; margin:0 0 4px; letter-spacing:.2px}
p.lead{color:var(--muted); font-size:13.5px; margin:0 0 16px}
.grid{display:grid; gap:16px}
.grid.c2{grid-template-columns:repeat(auto-fit,minmax(380px,1fr))}
.grid.c3{grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.model{
  background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:16px 18px; display:flex; flex-direction:column; gap:8px;
}
.model h3{margin:0; font-size:15.5px}
.model .meta{font-size:12.5px; color:var(--muted)}
.model .tags{display:flex; gap:6px; flex-wrap:wrap; margin-top:2px}
.tag{font-size:11px; padding:2px 8px; border-radius:20px; background:#eef1f6;
  color:#3b4656; border:1px solid #dde3ec}
.tag.ok{background:#e8f3ec; color:#1d6b3c; border-color:#c9e4d3}
.tag.no{background:#f6ecea; color:#8c3b28; border-color:#eccfc7}
.model .acts{display:flex; gap:8px; margin-top:6px; flex-wrap:wrap}
a.btn{display:inline-block; padding:7px 13px; border-radius:7px; font-size:13px;
  font-weight:600; text-decoration:none; background:#eef1f6; color:#22314a;
  border:1px solid #dbe1ea}
a.btn:hover{background:#e4e9f1}
a.btn.primary{background:var(--accent); color:#fff; border-color:var(--accent)}
a.btn.primary:hover{background:#0d1c30}
a.btn[aria-disabled="true"]{opacity:.42; pointer-events:none}
.picker{display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:14px}
.picker label{font-size:13px; color:var(--muted); font-weight:600}
select,button.ctrl{
  font-family:inherit; font-size:13.5px; padding:7px 10px; border-radius:7px;
  border:1px solid #d5dbe5; background:#fff; color:var(--ink)
}
button.ctrl{cursor:pointer; background:var(--accent); color:#fff; border-color:var(--accent);
  font-weight:600}
button.ctrl.ghost{background:#fff; color:var(--accent)}
.stage{background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:14px}
.stage img{width:100%; height:auto; display:block; border-radius:4px}
.cap{font-size:12.5px; color:var(--muted); margin-top:10px}
.slider{display:flex; align-items:center; gap:14px; margin-top:14px; flex-wrap:wrap}
input[type=range]{flex:1; min-width:220px; accent-color:var(--accent); height:22px}
.frameLabel{font-size:13.5px; font-weight:700; min-width:150px}
table{width:100%; border-collapse:collapse; font-size:13px; background:var(--card)}
th,td{padding:7px 10px; border-bottom:1px solid var(--line); text-align:right}
th:first-child,td:first-child{text-align:left}
th{background:#eef1f6; font-size:12px; text-transform:uppercase; letter-spacing:.4px;
  color:#48546a}
tr:last-child td{border-bottom:none}
.note{font-size:12.5px; color:var(--muted); border-left:3px solid var(--line);
  padding-left:11px; margin-top:12px}
footer{border-top:1px solid var(--line); margin-top:26px; padding:16px 0 0;
  color:var(--muted); font-size:12.5px; display:flex; justify-content:space-between}
a{color:#1c4b8a}
"""


def write_css():
    os.makedirs(os.path.join(ASSETS, "css"), exist_ok=True)
    with open(os.path.join(ASSETS, "css", "style.css"), "w") as f:
        f.write(CSS)


# --------------------------------------------------------------------------
# shared chrome
# --------------------------------------------------------------------------
def header(active):
    tabs = [("index.html", "Home"),
            ("snow.html", "Snowfall"),
            ("spv.html", "Zonal Wind (10 hPa)")]
    links = "".join(
        '<a href="%s"%s>%s</a>' % (h, ' class="active"' if h == active else "", t)
        for h, t in tabs)
    return """<header class="top">
  <h1>Seasonal Forecast Graphics</h1>
  <span class="sub">ECMWF SEAS5 &amp; C3S seasonal systems &middot; init 1 Nov 2026</span>
  <span class="spacer"></span>
  <a href="https://github.com/massachusettswx-weather/seasonal-snow" target="_blank"
     rel="noopener">GitHub</a>
</header>
<nav class="tabs">%s</nav>""" % links


def footer():
    return """<footer>
  <span>Data: Copernicus CDS (ECMWF SEAS5 and C3S seasonal systems) &middot;
        ERA5 reanalysis &middot; ERA5 climatology 1991&ndash;2020</span>
  <span><strong>@Massachusettswx</strong></span>
</footer>"""


def public_map():
    """{model_id: model} for the browser."""
    d = json.load(open(os.path.join(DATA, "models_public.json")))
    return {m["id"]: m for m in d.get("models", [])}


def page(title, active, body):
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s &middot; Seasonal Forecast Graphics</title>
<link rel="stylesheet" href="assets/css/style.css">
</head>
<body>
%s
<div class="wrap">
%s
</div>
</body>
</html>""" % (title, header(active), body)


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
def build_home(reg):
    cards = []
    for m in reg.get("models", []):
        tags = []
        tags.append('<span class="tag %s">%s</span>' %
                    ("ok" if m["snow_ok"] else "no",
                     "Snowfall" if m["snow_ok"] else "No snowfall"))
        tags.append('<span class="tag %s">%s</span>' %
                    ("ok" if m["spv_ok"] else "no",
                     "10 hPa wind" if m["spv_ok"] else "No wind"))
        tags.append('<span class="tag">%s members</span>' % m.get("members", "?"))
        tags.append('<span class="tag">init %s</span>' % m.get("init", "?"))
        acts = []
        acts.append('<a class="btn primary" href="snow.html?m=%s">Snowfall</a>' % m["id"]
                    if m["snow_ok"] else
                    '<a class="btn" aria-disabled="true">Snowfall</a>')
        acts.append('<a class="btn" href="spv.html?m=%s">10 hPa zonal wind</a>' % m["id"]
                    if m["spv_ok"] else
                    '<a class="btn" aria-disabled="true">10 hPa zonal wind</a>')
        cards.append("""<div class="model">
  <h3>%s</h3>
  <div class="meta">%s</div>
  <div class="tags">%s</div>
  <div class="acts">%s</div>
</div>""" % (m["name"], m.get("note", ""), "".join(tags), "".join(acts)))

    body = """<div class="card">
  <h2 class="sec">Choose a seasonal model</h2>
  <p class="lead">Every panel below comes from the same init (1 November 2026).
  Pick a model, then pick what you want to look at &mdash; accumulated snowfall
  for the continental United States, or the 10 hPa zonal-mean zonal wind
  (stratospheric polar vortex proxy) with the ERA5 1991&ndash;2020 climatology.</p>
</div>
<div class="grid c3">%s</div>
<div class="card">
  <p class="note">Snowfall is accumulated water equivalent in inches.
  Anomalies are computed against each model's own hindcast climate.
  The 10&nbsp;hPa charts show every ensemble member, the ensemble mean, the
  ERA5 daily climatology with 10&ndash;90th and 30&ndash;70th percentile bands,
  the 1959&ndash;2020 record bounds and the model's own climate mean where
  one could be built.</p>
</div>""" % ("".join(cards) or "<p>No models registered yet.</p>")
    open(os.path.join(SITE, "index.html"), "w").write(page("Home", "index.html", body))


def build_snow(reg):
    models = [m for m in reg.get("models", []) if m["snow_ok"]]
    sel = "".join('<option value="%s">%s</option>' % (m["id"], m["name"])
                  for m in models)
    body = """<div class="card">
  <h2 class="sec">Snowfall</h2>
  <p class="lead">Accumulated snowfall over the continental United States,
  in inches of water equivalent. Anomalies are measured against the model's own
  hindcast climate.</p>
  <div class="picker">
    <label for="modelSel">Model</label>
    <select id="modelSel" class="ctrl">%s</select>
  </div>
</div>

<div class="card" id="tab-total">
  <h2 class="sec">Total accumulation &mdash; init to end of run</h2>
  <p class="lead" id="totalCap"></p>
  <div class="stage"><img id="totalImg" alt="Total accumulated snowfall"></div>
</div>

<div class="card" id="tab-monthly">
  <h2 class="sec">Accumulation by lead month</h2>
  <p class="lead">One panel per lead month of the run.</p>
  <div class="grid c2" id="monthlyGrid"></div>
</div>

<div class="card" id="tab-anom">
  <h2 class="sec">Monthly anomaly</h2>
  <p class="lead">Drag the bar to step through the lead months. Values are
  inches of water equivalent above or below the model's hindcast climate.</p>
  <div class="stage"><img id="anomImg" alt="Monthly snowfall anomaly"></div>
  <div class="slider">
    <span class="frameLabel" id="anomLabel">&mdash;</span>
    <input type="range" id="anomRange" min="0" max="0" value="0" step="1">
    <button class="ctrl ghost" id="anomPrev">&#8592;</button>
    <button class="ctrl ghost" id="anomNext">&#8594;</button>
  </div>
  <div class="cap" id="anomCap"></div>
</div>""" % sel

    js = """
<script>
const MODELS = __MODELS__;

function q(p){const m=new URLSearchParams(location.search);return m.get(p);}
const sel=document.getElementById('modelSel');
if(q('m') && MODELS[q('m')]) sel.value=q('m');

function model(){return MODELS[sel.value];}

function renderTotal(){
  const m=model();
  const t=m.total;
  document.getElementById('totalImg').src=t.file;
  document.getElementById('totalImg').alt=t.caption;
  document.getElementById('totalCap').textContent=t.caption;
}

function renderMonthly(){
  const m=model();
  const g=document.getElementById('monthlyGrid');
  g.innerHTML=m.months.map(x=>
    `<div class="stage"><img src="${x.file}" alt="${x.label}"><div class="cap">${x.label} &mdash; ${x.caption}</div></div>`
  ).join('');
}

function renderAnom(i){
  const m=model();
  const fr=m.frames[i];
  document.getElementById('anomImg').src=fr.file;
  document.getElementById('anomImg').alt=fr.label;
  document.getElementById('anomLabel').textContent=fr.label;
  document.getElementById('anomCap').textContent=fr.caption||'';
}

function setFrame(i){
  const m=model();
  const r=document.getElementById('anomRange');
  i=Math.max(0,Math.min(m.frames.length-1,i));
  r.value=i; renderAnom(i);
}

function renderAll(){
  renderTotal(); renderMonthly();
  const m=model();
  const r=document.getElementById('anomRange');
  r.max=String(m.frames.length-1);
  setFrame(0);
}

sel.addEventListener('change',renderAll);
document.getElementById('anomRange').addEventListener('input',e=>setFrame(+e.target.value));
document.getElementById('anomPrev').addEventListener('click',()=>setFrame(+document.getElementById('anomRange').value-1));
document.getElementById('anomNext').addEventListener('click',()=>setFrame(+document.getElementById('anomRange').value+1));
document.addEventListener('keydown',e=>{
  if(e.key==='ArrowLeft') setFrame(+document.getElementById('anomRange').value-1);
  if(e.key==='ArrowRight') setFrame(+document.getElementById('anomRange').value+1);
});
renderAll();
</script>"""
    body += js.replace("__MODELS__", json.dumps(public_map()))
    open(os.path.join(SITE, "snow.html"), "w").write(page("Snowfall", "snow.html", body))


def build_spv(reg):
    models = [m for m in reg.get("models", []) if m["spv_ok"]]
    sel = "".join('<option value="%s">%s</option>' % (m["id"], m["name"])
                  for m in models)
    body = """<div class="card">
  <h2 class="sec">10 hPa zonal-mean zonal wind</h2>
  <p class="lead">The stratospheric polar vortex proxy at 10&nbsp;hPa, in m/s.
  Each model is shown over its own total lead days, against the
  ERA5 1991&ndash;2020 climatology.</p>
  <div class="picker">
    <label for="modelSel">Model</label>
    <select id="modelSel" class="ctrl">%s</select>
    <label for="domSel">Domain</label>
    <select id="domSel" class="ctrl">
      <option value="60">60&deg;N</option>
      <option value="NH">Northern Hemisphere (0&ndash;90&deg;N)</option>
    </select>
  </div>
</div>

<div class="card">
  <div class="stage"><img id="spvImg" alt="10 hPa zonal-mean zonal wind"></div>
  <div class="cap" id="spvCap"></div>
</div>

<div class="card">
  <h2 class="sec">Lead-month means</h2>
  <div id="tblWrap"></div>
</div>""" % sel

    js = """
<script>
const MODELS=__MODELS__;
function q(p){const m=new URLSearchParams(location.search);return m.get(p);}
const sel=document.getElementById('modelSel');
const dom=document.getElementById('domSel');
if(q('m') && MODELS[q('m')]) sel.value=q('m');
if(q('d')) dom.value=q('d');
function model(){return MODELS[sel.value];}
function render(){
  const m=model();
  const d=dom.value;
  const p=m.spv[d];
  const img=document.getElementById('spvImg');
  img.src=p.file; img.alt=p.caption;
  document.getElementById('spvCap').textContent=p.caption;
  const t=p.table;
  document.getElementById('tblWrap').innerHTML = t ?
    `<table><thead><tr><th>Lead month</th>${t.head.map(h=>`<th>${h}</th>`).join('')}</tr></thead>
     <tbody>${t.rows.map(r=>`<tr><td>${r[0]}</td>${r.slice(1).map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table>`
    : '<p class="note">No table for this model and domain.</p>';
}
sel.addEventListener('change',render); dom.addEventListener('change',render);
render();
</script>"""
    body += js.replace("__MODELS__", json.dumps(public_map()))
    open(os.path.join(SITE, "spv.html"), "w").write(page("Zonal Wind", "spv.html", body))


def main():
    os.makedirs(MAPDIR, exist_ok=True)
    os.makedirs(SPVDIR, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)
    write_css()
    reg = load_registry()
    build_home(reg)
    build_snow(reg)
    build_spv(reg)
    print("site built:", SITE)
    for m in reg.get("models", []):
        print("  %-16s snow=%s spv=%s" % (m["id"], m["snow_ok"], m["spv_ok"]))


if __name__ == "__main__":
    main()
