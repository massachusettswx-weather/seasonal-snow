"""Build the static site for the seasonal forecast graphics.

Pages
    index.html      home: pick a seasonal model
    model.html      that model's variables: snowfall / 10 hPa zonal wind
    snow.html       snowfall: end-of-run total, monthly totals, monthly
                    anomalies with a drag bar
    spv.html        10 hPa zonal-mean zonal wind, one panel per model

Data
    docs/data/models.json        the model registry
    docs/data/models_public.json the browser's copy

Run after any re-render:  python3 build_site.py
"""
import os, json

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "docs")
ASSETS = os.path.join(SITE, "assets")
DATA = os.path.join(SITE, "data")

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# --------------------------------------------------------------------------
# model registry
# --------------------------------------------------------------------------
def load_registry():
    """The registry is maintained by build_registry.py; this reads it and
    validates that every referenced asset exists."""
    p = os.path.join(DATA, "models.json")
    if not os.path.exists(p):
        return {"models": []}
    reg = json.load(open(p))
    for m in reg.get("models", []):
        m["snow_ok"] = False
        m["spv_ok"] = False
        for fr in m.get("frames", []):
            if os.path.exists(os.path.join(SITE, fr["file"].split("?")[0])):
                fr["ok"] = True
                m["snow_ok"] = True
        tot = m.get("total")
        if tot and os.path.exists(os.path.join(SITE, tot["file"].split("?")[0])):
            m["snow_ok"] = True
        for dom, info in m.get("spv", {}).items():
            if os.path.exists(os.path.join(SITE, info["file"].split("?")[0])):
                info["ok"] = True
                m["spv_ok"] = True
    return reg


def public_map(reg=None):
    """{model_id: model} for the browser, including the availability flags."""
    if reg is None:
        reg = load_registry()
    out = {}
    for m in reg.get("models", []):
        p = dict(m)
        p["snow_ok"] = m.get("snow_ok", False)
        p["spv_ok"] = m.get("spv_ok", False)
        out[m["id"]] = p
    return out


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
.grid.c3{grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
.grid.c4{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.model{
  background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:16px 18px; display:flex; flex-direction:column; gap:8px;
  transition:border-color .12s, box-shadow .12s;
}
.model:hover{border-color:#c3ccdb; box-shadow:0 2px 10px rgba(18,38,63,.07)}
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
a.btn.wide{display:block; text-align:center; padding:9px 14px}
.picker{display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:14px}
.picker label{font-size:13px; color:var(--muted); font-weight:600}
select,button.ctrl{
  font-family:inherit; font-size:13.5px; padding:7px 10px; border-radius:7px;
  border:1px solid #d5dbe5; background:#fff; color:var(--ink)
}
button.ctrl{cursor:pointer; background:var(--accent); color:#fff; border-color:var(--accent);
  font-weight:600}
button.ctrl.ghost{background:#fff; color:var(--accent)}
.seg{display:inline-flex; gap:6px}
.seg .segbtn{border-radius:16px; padding:7px 14px; font-size:13px}
.seg .segbtn.ghost{background:#fff; color:var(--accent)}
.seg .segbtn.on{background:var(--accent); color:#fff}
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
.crumb{font-size:13px; color:var(--muted); margin-bottom:14px}
.crumb a{text-decoration:none}
.crumb a:hover{text-decoration:underline}
.varlist{display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.var{background:var(--card); border:1px solid var(--line); border-radius:10px;
  overflow:hidden; display:flex; flex-direction:column}
.var .thumb{background:#eef1f6; border-bottom:1px solid var(--line);
  display:flex; align-items:center; justify-content:center; height:170px; overflow:hidden}
.var .thumb img{max-width:100%; max-height:100%; object-fit:contain}
.var .body{padding:14px 16px; display:flex; flex-direction:column; gap:6px; flex:1}
.var h3{margin:0; font-size:15px}
.var p{margin:0; font-size:12.5px; color:var(--muted)}
.var .acts{margin-top:auto; padding-top:10px}
.var.off{opacity:.55}
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
            ("model.html", "Model"),
            ("snow.html", "Snowfall"),
            ("spv.html", "Zonal Wind (10 hPa)"),
            ("enso.html", "ENSO")]
    links = "".join(
        '<a href="%s"%s>%s</a>' % (h, ' class="active"' if h == active else "", t)
        for h, t in tabs)
    return """<header class="top">
  <h1>Seasonal Forecast Graphics</h1>
  <span class="sub">ECMWF SEAS5 &amp; C3S seasonal systems &middot; Nov 2026 &amp; Oct 2026 inits</span>
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


VER = ""


def page(title, active, body, version=""):
    v = ("?v=%s" % version) if version else ""
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s &middot; Seasonal Forecast Graphics</title>
<link rel="stylesheet" href="assets/css/style.css%s">
</head>
<body>
%s
<div class="wrap">
%s
</div>
</body>
</html>""" % (title, v, header(active), body)


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
def build_home(reg):
    """Step 1: choose a model."""
    cards = []
    for m in reg.get("models", []):
        tags = []
        tags.append('<span class="tag %s">Snowfall</span>' %
                    ("ok" if m["snow_ok"] else "no"))
        tags.append('<span class="tag %s">10 hPa wind</span>' %
                    ("ok" if m["spv_ok"] else "no"))
        tags.append('<span class="tag">%s members</span>' % m.get("members", "?"))
        tags.append('<span class="tag">init %s</span>' % m.get("init", "?"))
        cards.append("""<a class="model" href="model.html?m=%s">
  <h3>%s</h3>
  <div class="meta">%s</div>
  <div class="tags">%s</div>
</a>""" % (m["id"], m["name"], m.get("note", ""), "".join(tags)))

    body = """<div class="card">
  <h2 class="sec">Step 1 &mdash; choose a seasonal model</h2>
  <p class="lead">Each model is shown from its own most recent init
  (ECMWF SEAS5 from 1 November 2026, the other centres from 1 October 2026
  &mdash; their November runs are not released yet).
  Pick a model and you will be taken to its list of variables &mdash;
  accumulated snowfall over the continental United States, ENSO temperature
  anomaly plumes for the four ENSO regions, and the 10 hPa zonal-mean zonal
  wind (the stratospheric polar vortex proxy) against the ERA5
  1991&ndash;2020 climatology.</p>
</div>
<div class="grid c3">%s</div>
<div class="card">
  <p class="note">Snowfall is accumulated snow in inches.
  Anomalies are computed against each model's own hindcast climate.
  The 10&nbsp;hPa charts show every ensemble member, the ensemble mean, the
  ERA5 daily climatology with 10&ndash;90th and 30&ndash;70th percentile bands,
  the 1959&ndash;2020 record bounds and the model's own climate mean where
  one could be built.</p>
</div>""" % ("".join(cards) or "<p>No models registered yet.</p>")
    open(os.path.join(SITE, "index.html"), "w").write(page("Home", "index.html", body, VER))


def build_model_page(reg):
    """Step 2: choose a variable for the chosen model."""
    body = """<div class="card">
  <div class="crumb"><a href="index.html">&larr; All models</a></div>
  <div class="picker">
    <label for="modelSel">Model</label>
    <select id="modelSel" class="ctrl">%s</select>
  </div>
  <h2 class="sec" id="mName"></h2>
  <p class="lead" id="mMeta"></p>
</div>

<div class="varlist" id="varlist"></div>

<div class="card">
  <p class="note">Snowfall is accumulated snow in inches.
  Anomalies are measured against the model's own hindcast climate.
  The 10&nbsp;hPa chart shows every ensemble member, the ensemble mean, the
  ERA5 1991&ndash;2020 daily climatology with 10&ndash;90th and 30&ndash;70th
  percentile bands, the 1959&ndash;2020 record bounds and the model's own
  climate mean where one could be built.</p>
</div>"""

    sel = "".join('<option value="%s">%s</option>' % (m["id"], m["name"])
                  for m in reg.get("models", []))
    body = body % sel

    js = """
<script>
const MODELS=__MODELS__;
function q(p){const m=new URLSearchParams(location.search);return m.get(p);}
const sel=document.getElementById('modelSel');
if(q('m') && MODELS[q('m')]) sel.value=q('m');

function render(){
  const m=MODELS[sel.value];
  document.getElementById('mName').textContent=m.name;
  const init=m.init||'';
  document.getElementById('mMeta').innerHTML=(m.note||'')+
    (init?(' &middot; <strong>init '+init+'</strong>'):'');
  const vars=[];
  vars.push({
    title:'Snowfall',
    desc:'Accumulated snowfall over the continental United States &mdash; total for the run, each lead month, and monthly anomalies with a drag bar.',
    href:'snow.html?m='+m.id,
    img:(m.total&&m.total.file)||(m.frames.length&&m.frames[0].file)||'',
    on:!!m.snow_ok
  });
  vars.push({
    title:'10 hPa zonal-mean zonal wind',
    desc:'The stratospheric polar vortex proxy in m/s, all members and the ensemble mean against the ERA5 1991&ndash;2020 climatology.',
    href:'spv.html?m='+m.id,
    img:(m.spv&&m.spv['60']&&m.spv['60'].file)||'',
    on:!!m.spv_ok
  });
  document.getElementById('varlist').innerHTML=vars.map(v=>
    `<div class="var ${v.on?'':'off'}">
       <div class="thumb">${v.img?'<img src="'+v.img+'" alt="">':''}</div>
       <div class="body">
         <h3>${v.title}</h3>
         <p>${v.desc}</p>
         <div class="acts">${v.on
            ?'<a class="btn primary wide" href="'+v.href+'">Open</a>'
            :'<span class="tag no">not available for this model</span>'}</div>
       </div>
     </div>`).join('');
}
sel.addEventListener('change',render);
render();
</script>"""
    body += js.replace("__MODELS__", json.dumps(public_map(reg)))
    open(os.path.join(SITE, "model.html"), "w").write(page("Model", "model.html", body, VER))


def build_snow(reg):
    """Step 3a: the snowfall page."""
    models = [m for m in reg.get("models", []) if m["snow_ok"]]
    sel = "".join('<option value="%s">%s</option>' % (m["id"], m["name"])
                  for m in models)
    body = """<div class="card">
  <div class="crumb"><a href="index.html">&larr; All models</a> &middot;
    <a href="model.html">Choose a variable</a></div>
  <h2 class="sec">Snowfall</h2>
  <p class="lead">Accumulated snowfall over the continental United States, in
  inches, on a 0&ndash;300&nbsp;in colour scale. Every model's season is shown
  over the same window, ending 01 July 2027. Anomalies are measured against
  the model's own hindcast climate.</p>
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
  <p class="lead">One panel per lead month of the run. Every month uses the same
  0&ndash;300&nbsp;in scale as the totals, so the months add up to the total in
  the same colours. No snowfall is white.</p>
  <div class="grid c2" id="monthlyGrid"></div>
</div>

<div class="card" id="tab-anom">
  <h2 class="sec">Monthly anomaly</h2>
  <p class="lead">Drag the bar to step through the lead months. Values are
  the anomaly against the model's own hindcast climate, in the units selected
  above.</p>
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

function pick(o){return o.file||'';}

function renderTotal(){
  const m=model();
  const t=m.total;
  document.getElementById('totalImg').src=pick(t);
  document.getElementById('totalImg').alt=t.caption;
  document.getElementById('totalCap').textContent=(t.caption||'');
}

function renderMonthly(){
  const m=model();
  const g=document.getElementById('monthlyGrid');
  g.innerHTML=m.months.map(x=>
    `<div class="stage"><img src="${pick(x)}" alt="${x.label}"><div class="cap">${x.label} &mdash; ${x.caption}</div></div>`
  ).join('');
}

function renderAnom(i){
  const m=model();
  const card=document.getElementById('tab-anom');
  if(!m.frames.length){
    if(card) card.style.display='none';
    const im=document.getElementById('anomImg');
    if(im) im.src='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
    return;
  }
  if(card) card.style.display='';
  const fr=(m.frames||[])[i];
  if(!fr) return;
  document.getElementById('anomImg').src=pick(fr);
  document.getElementById('anomImg').alt=fr.label;
  document.getElementById('anomLabel').textContent=fr.label;
  document.getElementById('anomCap').textContent=fr.caption||'';
}

function setFrame(i){
  const m=model();
  const r=document.getElementById('anomRange');
  const nf=(m.frames||[]).length;
  i=Math.max(0,Math.min(nf-1,i));
  r.value=i; renderAnom(i);
}

function renderAll(){
  renderTotal(); renderMonthly();
  const m=model();
  const r=document.getElementById('anomRange');
  const nf=(m.frames||[]).length;
  r.max=String(Math.max(0,nf-1));
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
    body += js.replace("__MODELS__", json.dumps(public_map(reg)))
    open(os.path.join(SITE, "snow.html"), "w").write(page("Snowfall", "snow.html", body, VER))


def build_enso(reg):
    """The ENSO plume page: one chart per basin per model."""
    models = [m for m in reg.get("models", []) if m.get("enso_ok")]
    sel = "".join('<option value="%s">%s</option>' % (m["id"], m["name"])
                  for m in models)
    body = """<div class="card">
  <div class="crumb"><a href="index.html">&larr; All models</a></div>
  <h2 class="sec">ENSO</h2>
  <p class="lead">Every ensemble member's temperature anomaly in each of the
  four ENSO regions, against the ERA5 1991&ndash;2020 climatology for the same
  basin and month. The thick line is the ensemble mean, the light lines are the
  members, and the shaded envelope is the member spread.</p>
  <div class="picker">
    <label for="modelSel">Model</label>
    <select id="modelSel" class="ctrl">%s</select>
  </div>
</div>

<div class="card">
  <h2 class="sec">Plume charts</h2>
  <div class="grid c1" id="ensoGrid"></div>
</div>""" % sel

    js = """
<script>
const MODELS = __MODELS__;
const sel=document.getElementById('modelSel');
function render(){
  const m=MODELS[sel.value];
  const g=document.getElementById('ensoGrid');
  if(!m||!m.enso){g.innerHTML='<p class="lead">No ENSO plumes for this model.</p>';return;}
  g.innerHTML=m.enso.map(e=>
    '<figure class="panel"><img loading="lazy" src="'+e.file+'" alt="'+e.caption+'">'+
    '<figcaption>'+e.caption+'</figcaption></figure>').join('');
}
sel.addEventListener('change',render);
render();
</script>"""

    body = body + js
    body = body.replace("__MODELS__", json.dumps(
        {m["id"]: {"name": m["name"], "enso": m.get("enso", [])} for m in models}))
    open(os.path.join(SITE, "enso.html"), "w").write(page("ENSO", "enso.html", body, VER))


def build_spv(reg):
    """Step 3b: the zonal wind page."""
    models = [m for m in reg.get("models", []) if m["spv_ok"]]
    sel = "".join('<option value="%s">%s</option>' % (m["id"], m["name"])
                  for m in models)
    body = """<div class="card">
  <div class="crumb"><a href="index.html">&larr; All models</a> &middot;
    <a href="model.html">Choose a variable</a></div>
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
if(q('d') && MODELS[sel.value].spv && MODELS[sel.value].spv[q('d')]) dom.value=q('d');
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
    body += js.replace("__MODELS__", json.dumps(public_map(reg)))
    open(os.path.join(SITE, "spv.html"), "w").write(page("Zonal Wind", "spv.html", body, VER))


def main():
    os.makedirs(os.path.join(ASSETS, "css"), exist_ok=True)
    os.makedirs(DATA, exist_ok=True)
    write_css()
    reg = load_registry()
    global VER
    VER = reg.get("version", "")
    build_home(reg)
    build_model_page(reg)
    build_snow(reg)
    build_enso(reg)
    build_spv(reg)
    print("site built:", SITE)
    for m in reg.get("models", []):
        print("  %-16s snow=%s spv=%s" % (m["id"], m["snow_ok"], m["spv_ok"]))


if __name__ == "__main__":
    main()
