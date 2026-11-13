"""The polar-cap section of the Stratosphere page.

The section is a time-height diagram of the polar cap (60-90N) normalised
geopotential height anomaly: the analysis on the left of the "forecast
starts" line, the model's own forecast on the right, running to the end of
that model's run.

It lives on the **Stratosphere** page, next to the 10 hPa zonal-mean zonal
wind, because it is the same part of the atmosphere seen from the other
side: the wind at 10 hPa is the vortex proxy, and this is the vortex
itself, from the stratosphere down to the surface.

Two kinds of chart live on the page:

  * the ERA5 reanalysis of the last 90 days, in front of the model's own
    forecast - what actually happened, and what might happen;
  * the seasonal sections, one per model, built from the C3S sub-daily
    archive, which run to the end of each model's own run.

**No medium-range guidance is used.**  The IFS 15-day chart that used to
sit here has been taken out: a sub-seasonal and a seasonal run are the
products this section is about.

The charts are rendered into output/polar_cap/ and copied into
docs/assets/polar/ by build_registry.py.
"""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "docs")
OUT = os.path.join(HERE, "output")

# the models the section has been rendered for, in the order they are shown
MODELS = [
    ("ecmwf-seas5", "ECMWF SEAS5"),
    ("ukmo-gloseas6", "UKMO GloSeas6"),
    ("meteo-france-s9", "METFR System 9"),
    ("cmcc-sps4", "CMCC SPS4"),
    ("dwd-gcfs2", "DWD GCFS2.2"),
    ("eccc-cansips", "ECCC canSIPS"),
]

def available(reg=None):
    """-> [(id, name)] for the models the registry says have a section."""
    if reg is None:
        p = os.path.join(SITE, "data", "models.json")
        reg = json.load(open(p)) if os.path.exists(p) else {"models": []}
    out = []
    for m in reg.get("models", []):
        if m.get("polar"):
            out.append((m["id"], m["name"]))
    return out


def items(reg=None):
    """Every polar-cap chart the page can show.

    Only the SEASONAL guidance is shown.  The ECMWF IFS 15-day chart is not:
    a medium-range forecast is a different product from a seasonal run, and
    the section is about the latter.
    """
    out = []
    for mid, name in available(reg):
        info = None
        for m in reg.get("models", []):
            if m["id"] == mid:
                info = m.get("polar")
        if not info:
            continue
        out.append({"id": mid, "name": name, "file": info["file"],
                    "caption": info.get("caption", "")})
    return out


def sector_items(reg=None):
    """The same section split into the North Pacific and the North Atlantic."""
    out = []
    for mid, name in available(reg):
        info = None
        for m in reg.get("models", []):
            if m["id"] == mid:
                info = m.get("polar_sectors")
        if not info:
            continue
        out.append({"id": mid, "name": name, "file": info["file"],
                    "caption": info.get("caption", "")})
    return out


def polar_block(reg=None):
    """The HTML for the polar-cap section, or "" when there is nothing."""
    its = items(reg)
    if not its:
        return ""
    secs = {i["id"]: i for i in sector_items(reg)}

    default = its[0]["id"]
    sel = "".join('<option value="%s"%s>%s</option>'
                  % (i["id"], " selected" if i["id"] == default else "",
                     i["name"]) for i in its)
    block = """<div class="card" id="polar">
  <div class="crumb"><a href="index.html">&larr; All models</a> &middot;
    <a href="model.html">Choose a variable</a></div>
  <h2 class="sec">Polar Cap (60&ndash;90&deg;N) Geopotential Height Anomaly</h2>
  <p class="lead">A time-height section of the polar cap: the area-weighted
  mean geopotential height from 60&deg;N to the pole, on a set of pressure
  levels, as an anomaly against ERA5&rsquo;s own 1991&ndash;2020 climate
  &mdash; in metres, so every system on this page can be read on the same
  scale. The pressure axis is logarithmic, so the stratosphere at the top
  has the room it needs, and the section runs down to the surface at the
  bottom.</p>
  <p class="lead">The left of the dashed line is <strong>ERA5
  reanalysis</strong> &mdash; what actually happened, up to the model&rsquo;s
  own run. The right is the <strong>seasonal forecast</strong> &mdash; what
  might happen, running to the end of that model&rsquo;s run. The dotted
  &ldquo;now&rdquo; line marks today, so the model&rsquo;s own days that have
  already passed and the days it is still forecasting are told apart.</p>
  <div class="picker">
    <label for="polarSel">Model</label>
    <select id="polarSel" class="ctrl">%s</select>
    <label for="polarView">View</label>
    <select id="polarView" class="ctrl">
      <option value="cap">Whole polar cap</option>
      <option value="sectors">North Pacific &amp; North Atlantic</option>
    </select>
  </div>
</div>

<div class="card">
  <div class="stage"><img id="polarImg" alt="Polar cap geopotential height anomaly"></div>
  <div class="cap" id="polarCap"></div>
</div>""" % sel

    js = """
<script>
const POLARMODELS=__POLARMODELS__;
const POLARSECTORS=__POLARSECTORS__;
const psel=document.getElementById('polarSel');
const pview=document.getElementById('polarView');
function pq(p){const m=new URLSearchParams(location.search);return m.get(p);}
if(pq('m') && POLARMODELS[pq('m')]) psel.value=pq('m');
function renderPolar(){
  const id=psel.value;
  const m=POLARMODELS[id];
  const s=POLARSECTORS[id];
  const wantSector=pview.value==='sectors' && s;
  const img=document.getElementById('polarImg');
  const cap=document.getElementById('polarCap');
  if(wantSector){
    img.src=s.file; img.alt=s.caption; cap.textContent=s.caption; return;
  }
  if(!m){img.removeAttribute('src');img.alt='';
    cap.textContent='No section for this model.';return;}
  img.src=m.file; img.alt=m.caption; cap.textContent=m.caption;
}
psel.addEventListener('change',renderPolar);
pview.addEventListener('change',renderPolar);
renderPolar();
</script>"""
    return (block
            + js.replace("__POLARMODELS__", json.dumps({i["id"]: i for i in its}))
                   .replace("__POLARSECTORS__",
                            json.dumps({i["id"]: i for i in sector_items(reg)})))


def remove_old_page():
    """The section used to have a page of its own; it does not any more."""
    p = os.path.join(SITE, "polar.html")
    if os.path.exists(p):
        os.remove(p)
        print("   the old polar-cap page removed")


if __name__ == "__main__":
    reg = json.load(open(os.path.join(SITE, "data", "models.json")))
    print(polar_block(reg)[:200])
