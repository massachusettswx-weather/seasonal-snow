"""Stop the background workers, sparing this script's own ancestry.

A pattern that also appears on the command line kills the shell that runs
it, so the match is done against /proc and the ancestry of this process is
never touched.

    python3 tools/stopall.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATTERNS = ("run_nov_queue.py", "auto_publish.sh", "run_nov_pool.sh",
            "plot_snow_models.py", "plot_snow_multi.py", "plot_enso.py",
            "fetch_models_daily.py", "fetch_snow_daily.py",
            "build_spv_panels.py", "plot_spv.py")


def ancestry():
    """The pids of this process and its parents - never to be killed."""
    out = set()
    pid = os.getpid()
    while pid and pid > 1:
        out.add(pid)
        try:
            with open("/proc/%d/stat" % pid) as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
        except Exception:
            break
        pid = ppid
    return out


def main():
    keep = ancestry()
    me = os.getpid()
    # only the patterns asked for, so the publisher can be left alone
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    pats = [p for p in PATTERNS if not only or any(o in p for o in only)]
    victims = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        pid = int(d)
        if pid == me or pid in keep:
            continue
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                cmd = f.read().decode("utf8", "replace").replace("\0", " ")
        except Exception:
            continue
        if not cmd:
            continue
        for pat in pats:
            if pat in cmd:
                victims.append((pid, pat, cmd[:110]))
                break
    for pid, pat, cmd in victims:
        print("stopping %-7d %s   %s" % (pid, pat, cmd))
        try:
            os.kill(pid, 15)
        except Exception as e:
            print("   could not stop it: %s" % str(e)[:60])
    if not victims:
        print("nothing to stop")


if __name__ == "__main__":
    main()
    sys.exit(0)
