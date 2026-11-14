"""The polar-cap climatology, built from ARCO's native ERA5 store.

The chart's field is the geopotential height ANOMALY, so the climate it is
measured against has to be the same product on the same grid as the data.
The CDS's monthly means are the same ERA5 on the same grid, but they came
out about 10 K colder than the store in the stratosphere: the polar-cap
10 hPa mean for November is 279958 m2/s2 in the CDS's monthly means and
292148 m2/s2 in the store, a difference of 1243 m in height.  Every anomaly
drawn against the CDS climate was therefore inflated by about that much,
which is eight standard errors of a thirty-year mean.

The store holds the ERA5 analysis on the native 0.25 degree grid, one hour
per chunk.  One day from the middle of each month of each year is enough
for a monthly mean: thirty samples for the month, spread over thirty
years, which is the same sampling error as the monthly mean itself.

What lands on disk:
    data/polar_cap_clim_native_daily.npz
        times, values (n, nlev) and levels, the monthly climate as a series
"""
import datetime as dt
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import LEVELS  # noqa: E402
from fetch_polar_era5_native import cap_and_sectors, chunk, latitude  # noqa: E402

OUT = os.path.join(DATA, "polar_cap_clim_native_daily.npz")

YEARS = list(range(1991, 2021))
DAY = 15          # the middle of the month


def main(out=OUT):
    lat = latitude()
    from fetch_polar_era5_native import LEV37
    jrows = {lv: LEV37.index(lv) for lv in LEVELS}

    times, rows = [], []
    for yr in YEARS:
        for m in range(1, 13):
            day = dt.date(yr, m, DAY)
            a = chunk(day)
            if a is None:
                print("   %s: the chunk is missing" % day)
                continue
            caps = []
            for lv in LEVELS:
                c, _s = cap_and_sectors(a[jrows[lv]].astype(float), lat)
                caps.append(c)
            times.append("%s 12" % day.isoformat())
            rows.append(caps)
        print("   %d: %d months so far" % (yr, len(rows)))
    if len(rows) < 300:
        print("   only %d samples - nothing written" % len(rows))
        return 1
    np.savez_compressed(out, times=np.array(times),
                        values=np.array(rows, float),
                        levels=np.array(LEVELS))
    print("   wrote %s: %d samples, %d levels" % (out, len(times), len(LEVELS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
