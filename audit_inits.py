"""Which init is every model actually on, in every product?

The site must never show a chart whose label disagrees with its data, and
the December release has to move every model together rather than one at
a time.  This reads the init out of the files themselves - the npz
metadata, the GRIB dates, the plume json - and compares them with the
registry that is published.

Run it with --gate to make it a publish gate: it then exits non-zero
when the state is not coherent enough to publish.

    python3 audit_inits.py            # the report
    python3 audit_inits.py --gate     # the report, and a verdict for publishing
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
DOCS = os.path.join(HERE, "docs")

sys.path.insert(0, HERE)
import init_info                                            # noqa: E402

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def npz_init(path):
    """The init recorded in an npz file's metadata."""
    try:
        import numpy as np
        d = np.load(path, allow_pickle=True)
        meta = d["meta"] if "meta" in d.files else None
        if meta is None:
            return None
        if isinstance(meta, np.ndarray):
            meta = meta.item()
        if isinstance(meta, bytes):
            meta = meta.decode()
        if isinstance(meta, str):
            meta = json.loads(meta)
        return meta.get("init")
    except Exception:
        return None


def grib_init(path):
    """The init a GRIB file belongs to, from its first record.

    Both the monthly wind and the monthly SST are averages over the lead
    month, and the archive stamps them at the end of that month.  The
    lead month 1 of a seasonal run is the init month itself, so the init
    is the month before the first valid date.
    """
    try:
        import eccodes
        from datetime import datetime as _dt, timedelta as _td
        with open(path, "rb") as f:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                return None
            step = int(eccodes.codes_get(gid, "step"))
            dd = int(eccodes.codes_get(gid, "dataDate"))
            d0 = _dt(dd // 10000, (dd // 100) % 100, dd % 100)
            m = (d0 + _td(hours=step)) - _td(days=1)
            return "%04d-%02d" % (m.year, m.month)
    except Exception:
        return None


def json_init(path):
    try:
        return json.load(open(path)).get("init")
    except Exception:
        return None


def products(tag):
    """The init every product of a model is on."""
    d = os.path.join(MDIR, tag)
    out = {}
    if not os.path.isdir(d):
        return out
    p = os.path.join(d, "snowfall_monthly.npz")
    if os.path.exists(p):
        out["snowfall"] = npz_init(p)
    p = os.path.join(d, "snowfall_hindcast.npz")
    if os.path.exists(p):
        out["snowfall clim"] = npz_init(p)
    p = os.path.join(d, "snowfall_ext.npz")
    if os.path.exists(p):
        out["snowfall ext"] = npz_init(p)
    p = os.path.join(d, "sst_monthly.grib")
    if os.path.exists(p):
        out["sst"] = grib_init(p)
    p = os.path.join(d, "u10_monthly.grib")
    if os.path.exists(p):
        out["u10"] = grib_init(p)
    p = os.path.join(d, "u10_daily.npz")
    if os.path.exists(p):
        out["u10 daily"] = npz_init(p)
    p = os.path.join(d, "enso.json")
    if os.path.exists(p):
        out["enso"] = json_init(p)
    return out


def c3s_centres(inits):
    """The centres in the C3S multi-model mean, with their init.

    The list comes from the multi-model's own membership file, so the
    pooled ECCC card (canSIPS) is counted once and the two systems it is
    built from are not counted twice.
    """
    mm = os.path.join(DATA, "multi_members.json")
    if os.path.exists(mm):
        try:
            d = json.load(open(mm))
            for m in d.get("models", []):
                tag = m.get("tag")
                if tag and tag in inits:
                    yield tag, inits[tag]
            return
        except Exception:
            pass
    for tag in init_info.CENTRES:
        if tag in inits:
            yield tag, inits[tag]


def main():
    gate = "--gate" in sys.argv
    allow_mixed = "--allow-mixed" in sys.argv
    st = init_info.state()

    models = {}
    for tag in sorted(os.listdir(MDIR)) if os.path.isdir(MDIR) else []:
        if not os.path.isdir(os.path.join(MDIR, tag)):
            continue
        models[tag] = products(tag)

    # the registry that is published
    reg = {}
    reg_note = {}
    rp = os.path.join(DOCS, "data", "models_public.json")
    if os.path.exists(rp):
        try:
            for m in json.load(open(rp)).get("models", []):
                reg[m.get("id")] = m.get("init")
                reg_note[m.get("id")] = m.get("note") or ""
        except Exception:
            pass

    print("the init each product is on")
    print("%-22s %-14s %-14s %-14s %s" % ("model", "state", "registry", "products",
                                          "verdict"))
    problems = []
    for tag, prods in models.items():
        pub = reg.get(tag)
        vals = [v for v in prods.values() if v]
        uniq = sorted(set(vals))
        own = st.get(tag, {}).get("init")
        verdict = "ok"
        if uniq and len(uniq) > 1:
            verdict = "MIXED PRODUCTS %s" % uniq
            problems.append("%s: its own products are on different inits %s"
                            % (tag, uniq))
        if pub and uniq and pub not in uniq:
            verdict = "MISLABELLED (the registry says %s, the data says %s)" % (
                pub, ",".join(uniq))
            problems.append("%s: the registry says %s but the data is on %s"
                            % (tag, pub, ",".join(uniq)))
        if pub and own and pub != own:
            verdict = "THE STATE AND THE REGISTRY DISAGREE (%s vs %s)" % (
                own, pub)
            problems.append("%s: the state says %s but the registry says %s"
                            % (tag, own, pub))
        if not pub:
            verdict = "not published"
        else:
            # the date written in the card has to be the model's own init:
            # the notes used to carry the init that was current when they
            # were written, so a card could claim an October init months
            # after the model had moved on
            m = re.search(r"init (\d{1,2}) ([A-Z][a-z]{2,8}) (\d{4})",
                          reg_note.get(tag, ""))
            if m and own:
                mm = MONTHS.get(m.group(2)[:3].lower())
                if not mm:
                    continue
                said = "%s-%02d" % (m.group(3), mm)
                if said != own:
                    verdict = "THE CARD SAYS %s (the model is on %s)" % (said, own)
                    problems.append("%s: the card says the %s init but the "
                                    "model is on the %s init"
                                    % (tag, said, own))
        print("%-22s %-14s %-14s %-14s %s"
              % (tag, own or "-", pub or "-", ",".join(uniq) or "-", verdict))

    # the C3S centres that go into the multi-model mean
    c3s = list(c3s_centres({t: st.get(t, {}).get("init")
                            for t in set(list(init_info.CENTRES) +
                                         list(st)) if st.get(t, {}).get("init")}))
    print()
    print("the C3S centres in the multi-model mean")
    for tag, init in c3s:
        print("   %-20s %s" % (tag, init))
    inits = sorted({i for _, i in c3s})
    if len(inits) > 1:
        msg = ("the C3S centres are on different inits %s - the site would show "
               "two months at once" % inits)
        print("   " + msg)
        if not allow_mixed:
            problems.append(msg)
    elif inits:
        print("   all on %s" % inits[0])

    print()
    # A chart must not run past its own model's end.  The ERA5 climatology
    # layer is a whole year long, so without the cap a chart carries a
    # month of climatology past the end of the run and the reader sees the
    # run still going when it has stopped.  The record is written by
    # plot_spv.py while it draws.
    axp = os.path.join(DATA, "spv_axis_ends.json")
    if os.path.exists(axp):
        try:
            ax = json.load(open(axp))
        except Exception:
            ax = {}
        bad = [(k, v) for k, v in sorted(ax.items())
               if float(v.get("over_days") or 0) > 1.5]
        if bad:
            print("the charts that run past their own model's end")
            for k, v in bad:
                msg = ("%s: the axis ends %s but the model's own last day is %s"
                       % (k, v.get("axis_end"), v.get("model_end")))
                print("   " + msg)
                problems.append(msg)
        else:
            print("every chart ends with its own model's run")

    print()
    if problems:
        print("NOT COHERENT")
        for p in problems:
            print("   - " + p)
        if gate:
            print("   the publish is blocked")
            return 1
    else:
        print("COHERENT")
    if gate and allow_mixed and problems:
        print("   (a mixed state was allowed on purpose)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
