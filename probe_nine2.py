import os, json
import numpy as np
HERE=os.path.dirname(os.path.abspath(__file__)); DATA=os.path.join(HERE,"data")
API="https://cds.climate.copernicus.eu/api"
MODELS=[("ncep","2","NCEP CFSv2"),("eccc","4","ECCC CanESM5.1p1bc"),("eccc","5","ECCC GEM5.2-NEMO"),
        ("ukmo","610","UKMO GloSea6-GC5.1"),("bom","2","BOM ACCESS-S2"),("cmcc","4","CMCC SPS4"),
        ("dwd","22","DWD GCFS2.2"),("meteo_france","9","Meteo-France System9")]
def client():
    key=[l.split(":",1)[1].strip() for l in open(os.path.join(HERE,".cdsapirc")) if l.strip().startswith("key:")][0]
    import cdsapi; return cdsapi.Client(url=API,key=key,progress=False)
def decode(path):
    import eccodes
    m=set(); ni=nj=0; dx=0.0
    with open(path,"rb") as fh:
        while True:
            gid=eccodes.codes_grib_new_from_file(fh)
            if gid is None: break
            try:
                def g(k,d=None):
                    try: return eccodes.codes_get(gid,k)
                    except Exception: return d
                m.add(int(g("perturbationNumber",0))); ni,nj=int(g("Ni")),int(g("Nj"))
                dx=float(g("iDirectionIncrementInDegrees",0))
            finally: eccodes.codes_release(gid)
    return dict(members=len(m),ni=ni,nj=nj,dx=dx)
c=client()
for centre,system,name in MODELS:
    for label,var,extra,dataset in (("snow","snowfall",None,"seasonal-monthly-single-levels"),
                                    ("t2m","2m_temperature",None,"seasonal-monthly-single-levels")):
        ok=False
        for yr,mo in (("2026","11"),("2026","10"),("2026","12"),("2025","11")):
            t=os.path.join(DATA,"p9b.grib")
            req={"originating_centre":centre,"system":system,"variable":var,"product_type":"monthly_mean",
                 "year":yr,"month":mo,"leadtime_month":["1"],"data_format":"grib"}
            try: c.retrieve(dataset,req,t)
            except Exception as e:
                if os.path.exists(t): os.remove(t)
                continue
            info=decode(t); os.remove(t); info["init"]="%s-%s"%(yr,mo)
            print("%-22s %-12s %-4s OK members=%2d %dx%d dx=%.2f init=%s"%(name,centre+":"+system,label,info["members"],info["ni"],info["nj"],info["dx"],info["init"]),flush=True)
            ok=True; break
        if not ok: print("%-22s %-12s %-4s NONE"%(name,centre+":"+system,label),flush=True)
