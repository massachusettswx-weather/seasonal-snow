"""The polar-cap page of the site.

The section is a time-height diagram of the polar cap (60-90N) normalised
geopotential height anomaly: the ERA5 analysis on the left of the
"forecast starts" line, the model's own forecast on the right, running to
the end of that model's run.

Two kinds of chart live on the page:

  * the ECMWF IFS section, built from the open data bucket - the same
    product the reference figure uses - which is always available because
    the open data has no queue;
  * the seasonal sections, one per model, built from the C3S sub-daily
    archive, which run to the end of each model's own run.

The page carries a menu, and the IFS section is the default because it is
the one that is always there.

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

# the IFS section is not a model, so it is carried on its own
IFS_ID = "ecmwf-ifs"
IFS_NAME = "ECMWF IFS (15-day)"
IFS_FILE = "assets/polar/polar_cap_ifs.png"
IFS_CAPTION = ("Polar cap (60-90N) normalised geopotential height anomaly - "
               "the ECMWF IFS 15-day forecast from the 11 Nov 2026 12z run, "
               "with the ECMWF analysis in front of it.")


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


def ifs_item(reg=None):
    """The IFS section, if the chart has been rendered.

    The registry carries it with the cache-busting version query, because
    GitHub Pages serves the PNGs with a long cache lifetime.
    """
    if reg is None:
        p = os.path.join(SITE, "data", "models.json")
        reg = json.load(open(p)) if os.path.exists(p) else {}
    info = reg.get("polar_ifs")
    if not info:
        p = os.path.join(SITE, IFS_FILE)
        if not os.path.exists(p):
            return None
        info = {"file": IFS_FILE, "caption": IFS_CAPTION}
    return {"id": IFS_ID, "name": IFS_NAME, "file": info["file"],
            "caption": info.get("caption", IFS_CAPTION)}


def build_polar_cap(reg):
    """Write the polar-cap page and copy the charts into the assets."""
    import build_site
    items = []
    ifs = ifs_item(reg)
    if ifs:
        items.append(ifs)
    for mid, name in available(reg):
        info = None
        for m in reg.get("models", []):
            if m["id"] == mid:
                info = m.get("polar")
        if not info:
            continue
        items.append({"id": mid, "name": name, "file": info["file"],
                      "caption": info.get("caption", "")})
    if not items:
        print("   no polar-cap charts yet - the page is skipped")
        return

    default = IFS_ID if ifs else items[0]["id"]
    sel = "".join('<option value="%s"%s>%s</option>'
                  % (i["id"], " selected" if i["id"] == default else "",
                     i["name"]) for i in items)
    body = """<div class="card">
  <div class="crumb"><a href="index.html">&larr; All models</a> &middot;
    <a href="model.html">Choose a variable</a></div>
  <h2 class="sec">Polar Cap (60-90N) Geopotential Height Anomaly</h2>
  <p class="lead">A time-height section of the polar cap: the area-weighted
  mean geopotential height from 60&deg;N to the pole, on a set of pressure
  levels, with the anomaly divided by its own 1991&ndash;2020 standard
  deviation. The pressure axis is logarithmic and the section runs from the
  stratosphere at the top to the surface at the bottom. On the left of the
  dashed line is the analysis; on the right is the model&rsquo;s own
  forecast, running to the end of that model&rsquo;s run.</p>
  <div class="picker">
    <label for="modelSel">Model</label>
    <select id="modelSel" class="ctrl">%s</select>
  </div>
</div>

<div class="card">
  <div class="stage"><img id="pcImg" alt="Polar cap geopotential height anomaly"></div>
  <div class="cap" id="pcCap"></div>
</div>""" % sel

    js = """
<script>
const MODELS=__MODELS__;
const sel=document.getElementById('modelSel');
function q(p){const m=new URLSearchParams(location.search);return m.get(p);}
if(q('m') && MODELS[q('m')]) sel.value=q('m');
function render(){
  const m=MODELS[sel.value];
  const img=document.getElementById('pcImg');
  if(!m){img.removeAttribute('src');img.alt='';
    document.getElementById('pcCap').textContent='No section for this model.';return;}
  img.src=m.file; img.alt=m.caption;
  document.getElementById('pcCap').textContent=m.caption;
}
sel.addEventListener('change',render);
render();
</script>"""
    body += js.replace("__MODELS__", json.dumps({i["id"]: i for i in items}))
    open(os.path.join(SITE, "polar.html"), "w").write(
        build_site.page("Polar Cap", "polar.html", body, build_site.VER))
    print("   the polar-cap page: %d charts" % len(items))


if __name__ == "__main__":
    build_polar_cap(json.load(open(os.path.join(SITE, "data", "models.json"))))
