"""Probe which NOAA (and BOM) seasonal systems serve the recent C3S inits.

The C3S seasonal catalogue exposes a per-centre system number, and the
systems the CDS lists for ncep are 1..9 and 12..15.  ncep:2 is known to be
CFSv2; SFSv1 (NOAA's next-generation seasonal system) has to be found.  This
submits a tiny monthly request per candidate system and records whether the
archive has data for the init, so the centre can be added to the site.

usage: python3 probe_noaa.py [year month]
"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cds_direct import CDSDirect, QueueFull, NoData

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DATASET = "seasonal-monthly-single-levels"

CANDIDATES = [
    ("ncep", "1", "NCEP ?"), ("ncep", "2", "NCEP CFSv2"),
    ("ncep", "3", "NCEP ?"), ("ncep", "12", "NCEP ?"),
    ("ncep", "13", "NCEP ?"), ("ncep", "14", "NCEP ?"),
    ("ncep", "15", "NCEP ?"),
    ("bom", "2", "BOM ACCESS-S2"), ("bom", "1", "BOM ?"),
    ("bom", "3", "BOM ?"), ("bom", "4", "BOM ?"),
]
INITS = [("2026", "11"), ("2026", "10"), ("2026", "09")]


def main():
    year = sys.argv[1] if len(sys.argv) > 1 else "2026"
    month = sys.argv[2] if len(sys.argv) > 2 else "11"
    c = CDSDirect()
    out = {}
    for centre, system, label in CANDIDATES:
        key = "%s:%s" % (centre, system)
        req = {"originating_centre": centre, "system": system,
               "variable": "2m_temperature", "product_type": "monthly_mean",
               "year": year, "month": month, "leadtime_month": "1",
               "data_format": "grib"}
        try:
            jid = c.submit(DATASET, req)
        except QueueFull:
            print("%-10s queue full - skipping" % key, flush=True)
            continue
        except NoData as e:
            print("%-10s NO DATA: %s" % (key, str(e)[:120]), flush=True)
            out[key] = {"init": "%s-%s" % (year, month), "result": "nodata"}
            continue
        except Exception as e:
            print("%-10s submit failed: %s" % (key, str(e)[:120]), flush=True)
            continue
        t0 = time.time()
        st = "?"
        while time.time() - t0 < 2400:
            st = c.job_status(jid)
            if st != "accepted":
                break
            time.sleep(30)
        dt = time.time() - t0
        if st == "successful":
            path = os.path.join(DATA, "probe_%s_%s.grib" % (centre, system))
            try:
                c.download_job(jid, path)
                n = os.path.getsize(path)
                import eccodes
                with open(path, "rb") as f:
                    gid = eccodes.codes_grib_new_from_file(f)
                    ni = eccodes.codes_get(gid, "ni")
                    nj = eccodes.codes_get(gid, "nj")
                    nmem = eccodes.codes_get(gid, "number")
                    eccodes.codes_release(gid)
                print("%-10s DATA ok (%.1f s, %.1f MB, %dx%d, member %s)"
                      % (key, dt, n / 1e6, ni, nj, nmem), flush=True)
                out[key] = {"init": "%s-%s" % (year, month), "result": "ok",
                            "bytes": n, "ni": ni, "nj": nj, "member": int(nmem)}
                os.remove(path)
            except Exception as e:
                print("%-10s download/decode failed: %s" % (key, str(e)[:150]), flush=True)
        else:
            print("%-10s %s after %.0f s" % (key, st, dt), flush=True)
            out[key] = {"init": "%s-%s" % (year, month), "result": st,
                        "detail": c._job_detail(jid)[:300]}
        json.dump(out, open(os.path.join(DATA, "probe_noaa.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
