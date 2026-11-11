"""Split a GRIB that carries more than one variable into one file per
variable.

The CDS accepts a LIST of variables in a single request, which halves the
number of queue slots a centre needs - the snowfall and the sea-surface
temperature of a centre come back in one file.  The rest of the pipeline
expects one file per variable, so the combined file is split here by the
GRIB short name.

    python3 split_grib.py <in.grib> <outdir> <shortname> [<shortname> ...]
"""
import os
import sys

import eccodes

# the C3S seasonal products name their fields like this
ALIASES = {
    # the monthly product carries the snowfall as a rate ("mtsfr"), the
    # sub-daily product as an accumulation ("sf")
    "snowfall": ("mtsfr", "snowfall", "sf", "tp"),
    "sst": ("sst", "sea_surface_temperature"),
}


def short_name(gid):
    try:
        return eccodes.codes_get(gid, "shortName")
    except Exception:
        try:
            return eccodes.codes_get(gid, "paramId")
        except Exception:
            return None


def split(path, outdir, wanted):
    """Write one GRIB per wanted short name.  -> {shortname: path}"""
    os.makedirs(outdir, exist_ok=True)
    outs = {w: os.path.join(outdir, w + ".grib") for w in wanted}
    handles = {w: open(p, "wb") for w, p in outs.items()}
    counts = {w: 0 for w in wanted}
    try:
        with open(path, "rb") as f:
            while True:
                gid = eccodes.codes_grib_new_from_file(f)
                if gid is None:
                    break
                try:
                    sn = short_name(gid)
                    for w in wanted:
                        # the alias list catches the several names the same
                        # physical field can carry
                        if sn in ALIASES.get(w, (w,)):
                            eccodes.codes_write(gid, handles[w])
                            counts[w] += 1
                            break
                finally:
                    eccodes.codes_release(gid)
    finally:
        for h in handles.values():
            h.close()
    for w in list(outs):
        p = outs[w]
        if counts[w] == 0 or (os.path.exists(p) and os.path.getsize(p) < 1000):
            if os.path.exists(p):
                os.remove(p)
            del outs[w]
    return outs, counts


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 1
    src, outdir = sys.argv[1], sys.argv[2]
    wanted = sys.argv[3:]
    outs, counts = split(src, outdir, wanted)
    for w, p in outs.items():
        print("  %s: %d messages -> %s (%.1f MB)"
              % (w, counts[w], p, os.path.getsize(p) / 1e6))
    for w in wanted:
        if w not in outs:
            print("  %s: nothing found in %s" % (w, os.path.basename(src)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
