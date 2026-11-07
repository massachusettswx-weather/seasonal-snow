import os, json, sys
import numpy as np
HERE=os.path.dirname(os.path.abspath(__file__)); DATA=os.path.join(HERE,"data")
API="https://cds.climate.copernicus.eu/api"; PATH=os.path.join(DATA,"seasonal_systems_probe.json")
MODELS=[("ecmwf","51","ECMWF SEAS5"),("ncep","2","NCEP CFSv2"),("eccc","4","ECCC CanESM5.1p1bc"),
        ("eccc","5","ECCC GEM5.2-NEMO"),("ukmo","610","UKMO GloSea6-GC5.1"),("bom","2","BOM ACCESS-S2"),
        ("cmcc","4","CMCC SPS4"),("dwd","22","DWD GCFS2.2"),("meteo_france","9","Meteo-France System9")]
INITS=[("2026","11"),("2026","10"),("2026","09")]
def client():
    key=[l.split(":",1)[1].strip() for l in open(os.path.join(HERE,".cdsapirc")) if l.strip().startswith("key:")][0]
    import cdsapi; return cdsapi.Client(url=API,key=key,progress=False)
def decode(path):
    import eccodes
    m=set(); ni=nj=0; dx=dy=0.0; f=l=0.0
    with open(path,"rb") as fh:
        while True:
            gid=eccodes.codes_grib_new_from_file(fh)
            if gid is None: break
            try:
                def g(k,d=None):
                    try: return eccodes.codes_get(gid,k)
                    except Exception: return d
                m.add(int(g("perturbationNumber",0))); ni,nj=int(g("Ni")),int(g("Nj"))
                dx=float(g("iDirectionIncrementInDegrees",0)); dy=float(g("jDirectionIncrementInDegrees",0))
                f=float(g("latitudeOfFirstGridPointInDegrees")); l=float(g("latitudeOfLastGridPointInDegrees"))
            finally: eccodes.codes_release(gid)
    return dict(members=len(m),ni=ni,nj=nj,dx=dx,dy=dy,first=f,last=l)
def probe(c,centre,system,dataset,variable,extra=None):
    for yr,mo in INITS:
        t=os.path.join(DATA,"p9.grib")
        req={"originating_centre":centre,"system":system,"variable":variable,"year":yr,"month":mo,
             "day":"01","leadtime_hour":["12"],"data_format":"grib"}
        if extra: req.update(extra)
        try: c.retrieve(dataset,req,t)
        except Exception as e:
            if os.path.exists(t): os.remove(t)
            continue
        try: info=decode(t)
        finally: os.remove(t)
        info["init"]="%s-%s"%(yr,mo); return info
    return None
c=client(); out=json.load(open(PATH)) if os.path.exists(PATH) else {}
for centre,system,name in MODELS:
    key="%s:%s"%(centre,system); rec=out.setdefault(key,{"centre":centre,"system":system,"name":name})
    if "snowfall" not in rec:
        i=probe(c,centre,system,"seasonal-original-single-levels","snowfall")
        if i: rec["snowfall"]=i; print("%-16s %-22s snow members=%2d %dx%d dx=%.2f init=%s"%(name,key,i["members"],i["ni"],i["nj"],i["dx"],i["init"]),flush=True)
        else: print("%-16s %-22s snow NONE"%(name,key),flush=True)
    json.dump(out,open(PATH,"w"),indent=1)
print("snow pass done",flush=True)
