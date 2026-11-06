"""Poll the CDS until the SEAS5 November-2026 run is released, then build the
figure automatically.

ECMWF's seasonal contribution is released on the 6th of each month at 12 UTC;
until then MARS refuses the current init with
"AccessError: Restricted access to current C3S seasonal forecast ECMWF contribution".

usage: python3 wait_and_build.py [--year 2026] [--month 11] [--max-hours 30]
"""
import os, sys, time, subprocess, argparse, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def log(msg):
    print("[%s] %s" % (datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ"), msg), flush=True)


def probe_available(year, month):
    """True if the CDS will serve this init (small request)."""
    import cdsapi
    key = os.environ.get("CDS_KEY", "").strip()
    if not key:
        rc = os.path.join(HERE, ".cdsapirc")
        if os.path.exists(rc):
            for line in open(rc):
                if line.strip().startswith("key:"):
                    key = line.split(":", 1)[1].strip()
    if not key:
        log("no CDS key -> cannot poll")
        return False
    c = cdsapi.Client(url="https://cds.climate.copernicus.eu/api", key=key,
                      quiet=True, progress=False)
    req = {"originating_centre": "ecmwf", "system": 51,
           "variable": "u_component_of_wind", "pressure_level": "10",
           "product_type": "ensemble_mean", "year": str(year),
           "month": "%02d" % month, "leadtime_month": ["1"], "data_format": "grib"}
    try:
        c.retrieve("seasonal-monthly-pressure-levels", req, "/tmp/_poll.grib")
        return True
    except Exception as e:
        msg = str(e)
        if "Restricted access to current" in msg:
            log("still restricted (current contribution not released yet)")
        else:
            brief = [l for l in msg.split("\n") if ("ERROR" in l or "NoData" in l)]
            log("probe error: %s" % (brief[0][:140] if brief else msg[:140]))
        return False


def run(cmd):
    log("run: %s" % " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    out = (p.stdout or "") + (p.stderr or "")
    log(out[-2500:])
    return p.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--month", type=int, default=11)
    ap.add_argument("--max-hours", type=float, default=30)
    args = ap.parse_args()
    deadline = time.time() + args.max_hours * 3600
    tag = "%04d%02d" % (args.year, args.month)

    while time.time() < deadline:
        if probe_available(args.year, args.month):
            log("CDS is serving the %s init -> building" % tag)
            ok = False
            if run([sys.executable, "fetch_seas5.py", "--year", str(args.year),
                    "--month", str(args.month)]) == 0:
                run([sys.executable, "plot_seas5.py", "--domain", "60", "--init", tag])
                run([sys.executable, "plot_seas5.py", "--domain", "NH", "--init", tag])
                log("MONTHLY BUILD COMPLETE")
                ok = True
            if run([sys.executable, "fetch_seas5_daily.py",
                    "--year", str(args.year), "--month", str(args.month)]) == 0:
                run([sys.executable, "plot_seas5_mwx.py", "--domain", "60", "--init", tag])
                run([sys.executable, "plot_seas5_daily.py", "--domain", "60", "--init", tag])
                run([sys.executable, "plot_seas5_daily.py", "--domain", "NH", "--init", tag])
                log("DAILY BUILD COMPLETE")
                ok = True
            if ok:
                log("BUILD COMPLETE")
                return 0
            log("fetch failed, will retry")
        time.sleep(900)
    log("gave up waiting")
    return 1


if __name__ == "__main__":
    sys.exit(main())
