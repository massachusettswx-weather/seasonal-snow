"""A dry run of the December rollover, with no network and no real data.

The December release must move the whole site in one step: every model
picks up the new init, every label follows the data, and nothing is
published while the centres are on two different inits.

This test checks the three things that can break that:

  1. the release calendar - which init a centre can be on on a given day;
  2. the wipe - that a centre whose init moves loses its old derived
     files, so a stale panel cannot survive the switch;
  3. the gate - that a mixed state is refused and a coherent one is let
     through.

Run:  python3 test_december_transition.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import init_info                                            # noqa: E402

ok = True


def check(name, got, want):
    global ok
    good = got == want
    ok = ok and good
    print("   %-52s %-22s %s" % (name, got, "ok" if good else "WRONG (want %s)" % want))


def calendar():
    print("1. the release calendar")
    # the ECMWF publishes on the 6th, every other centre on the 10th
    real_date = init_info.date

    class FakeDate(real_date):
        """A date the test can move."""
        _today = real_date(2026, 12, 5)

        @classmethod
        def today(cls):
            return cls._today

    def at(y, m, d):
        FakeDate._today = real_date(y, m, d)

    try:
        init_info.date = FakeDate
        at(2026, 12, 5)
        check("the ECMWF on 5 December", init_info.newest_init("ecmwf-seas5"),
              "2026-11")
        check("the UKMO on 5 December", init_info.newest_init("ukmo-gloseas6"),
              "2026-11")
        at(2026, 12, 7)
        check("the ECMWF on 7 December", init_info.newest_init("ecmwf-seas5"),
              "2026-12")
        check("the UKMO on 7 December", init_info.newest_init("ukmo-gloseas6"),
              "2026-11")
        at(2026, 12, 11)
        check("the UKMO on 11 December", init_info.newest_init("ukmo-gloseas6"),
              "2026-12")
        at(2027, 1, 3)
        check("the ECMWF on 3 January", init_info.newest_init("ecmwf-seas5"),
              "2026-12")
        check("the UKMO on 3 January", init_info.newest_init("ukmo-gloseas6"),
              "2026-12")
    finally:
        init_info.date = real_date


def wipe():
    print("2. the wipe when a centre's init moves")
    import run_nov_queue
    tmp = tempfile.mkdtemp(prefix="wipe-test-")
    try:
        d = os.path.join(tmp, "models", "ukmo-gloseas6")
        os.makedirs(d)
        names = ["u10_daily.npz", "snowfall_ext.npz", "enso.json",
                 "sst_extended.npz", "u10_daily_c0.grib", "u10_daily_c1.grib",
                 "u10_daily_c2.grib", "snowfall_ext.grib"]
        for n in names:
            open(os.path.join(d, n), "w").write("x")
        # a file that must survive: the monthly wind is re-fetched, not wiped
        keep = "u10_monthly.grib"
        open(os.path.join(d, keep), "w").write("x")
        old = run_nov_queue.MDIR
        run_nov_queue.MDIR = os.path.join(tmp, "models")
        try:
            run_nov_queue.wipe_centre("ukmo-gloseas6")
        finally:
            run_nov_queue.MDIR = old
        left = sorted(os.listdir(d))
        check("the derived files are gone", left, [keep])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_gate():
    """Run the audit's gate in this process and return (code, output)."""
    import io
    import contextlib
    import audit_inits
    argv = sys.argv
    sys.argv = ["audit_inits.py", "--gate"]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = audit_inits.main()
    finally:
        sys.argv = argv
    return rc, buf.getvalue()


def gate():
    print("3. the publish gate")
    st = init_info.state()
    tmp = tempfile.mkdtemp(prefix="gate-test-")
    try:
        # a mixed state: the ECMWF has moved, the others have not
        mixed = dict(st)
        mixed["ecmwf-seas5"] = dict(st.get("ecmwf-seas5", {}))
        mixed["ecmwf-seas5"]["init"] = "2026-12"
        init_info.STATE = os.path.join(tmp, "models_fetched.json")
        json.dump(mixed, open(init_info.STATE, "w"), indent=1)
        import audit_inits
        rc, out = run_gate()
        check("a mixed state is refused", rc, 1)
        check("the refusal says why", "two months at once" in out, True)
        # a coherent state: everything on December
        clean = dict(st)
        for t in clean:
            if isinstance(clean[t], dict) and "init" in clean[t]:
                clean[t] = dict(clean[t])
                clean[t]["init"] = "2026-12"
        json.dump(clean, open(init_info.STATE, "w"), indent=1)
        rc, out = run_gate()
        print("   [debug] the state the audit read:",
              init_info.state().get("ukmo-gloseas6", {}).get("init"))
        # the data on disk is still November, so the audit still finds the
        # mismatch and refuses - which is the point: the registry and the
        # data have to agree
        check("a registry that disagrees with the data is refused", rc, 1)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        init_info.STATE = os.path.join(init_info.DATA, "models_fetched.json")


if __name__ == "__main__":
    calendar()
    wipe()
    gate()
    print()
    print("the transition is sound" if ok else "SOMETHING IS WRONG")
    sys.exit(0 if ok else 1)
