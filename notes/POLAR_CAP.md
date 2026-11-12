# The polar cap time-height section (the 60-90N geopotential height anomaly)

The reference figure is severe-weather.eu's "ECMWF 11 Nov 12z: Polar Cap
(60-90N) Normalized Geopotential Height Anomaly" by Andrej Flis
(/@Recretos).  The section needs three halves: a climatology, an analysis
before the init, and the model's own forecast.

## What the reference actually is (measured pixel by pixel)
- The pressure axis is **LOGARITHMIC**: `y = 109 + log(p/10)/log(100) * 825`
  fits the tick rows to within 0.7 px.  An evenly spaced level axis is wrong.
- The palette is **NOT RdBu**.  It runs blue -> white -> **YELLOW** -> orange
  -> red.  Seventeen colours, sampled out of the reference's own colour bar:
  `#000e4e #00238c #0045b5 #0c6fd3 #359fe8 #6bbef0 #a8daf5 #daeef8
  #ffffff #fff685 #ffff00 #ffb700 #ff7300 #ff3300 #e20000 #ac0202 #6b0000`
  The breaks are the reference's tick values: -5 -4 -3 -2 -1.5 -1 -0.5 -0.2
  0.2 0.5 1 1.5 2 3 4 5.
- The right-hand axis is **LINEAR in altitude**, independent of the
  log-pressure axis: 0, 8, 16, 24, 32 km, each with the miles.
- The section is filled with smooth contours (`contourf`), not blocky cells.
- The layout: centred bold title, centred subtitle, a blue "<- ECMWF
  ANALYSIS" left of the split and a red "ECMWF 15-DAY FORECAST (11 Nov 12z)
  ->" right of it, a red dashed vertical split line, a dashed grey grid, and
  a horizontal colour bar with pointed ends below the panel.

## The climatology: ARCO, not the CDS
The CDS queue is saturated and the ERA5 pressure-level cost limit caps a
request at one year, so the climatology comes from
`https://storage.googleapis.com/gcp-public-data-arco-era5/ar/1959-2022-1h-240x121_equiangular_with_poles_conservative.zarr`
- The 1-hourly store has **all 37 levels**; the 6-hourly stores have only 13
  (no 10 or 30 hPa).  The 1-hourly 240x121 store is the one to use.
- 1991-2020 gives **10,958 days**; the polar cap is 21 latitude rows.
- **The 60N row is stored as 59.999999999999986** - an exact comparison
  silently drops the bottom row of the cap (500 hPa moves by 104 m2/s2 =
  0.2% = 0.1 sigma, and the change is NOT affine, so it does not cancel in
  the normalised anomaly).  Compare with a 1e-6 tolerance.
- The 240x121 grid is **1.5 degrees**, not 0.25.

## The forecast: the IFS open data is the queue-free route
`https://ecmwf-forecasts.s3.amazonaws.com/` - no queue, no cost limit.
- The plain LIST (the bucket root) answers **503**; the query with an
  explicit `?prefix=` is the one that works.
- **A double slash in the path fails 100%** (BUCKET ends in "/" and the
  format string adds another -> every request 404s, and no retry fixes it).
  This cost hours.
- The bucket keeps each cycle's forecast as one GRIB2 per step, with an
  `.index` file beside it listing every message's **byte offset and length**.
  Fetch only the `param: "z"` (geopotential) messages at the wanted levels
  with HTTP **Range** requests: 11 messages = 10 MB, against 96 MB for the
  whole step file.
- The 503s come in bursts and roughly **30-40% of the requests succeed**, so
  the answer is volume, not patience: many quick retries, and the byte
  ranges fetched with 8 threads.
- **The bucket throttles by DURATION as well as by burst**: after a heavy
  fetch it answers nothing for minutes.  A long pause clears it.  Probing it
  repeatedly while a fetch is running makes the throttle WORSE.
- Steps run 0..360 h at 3-hourly = **15 days**.
- The IFS open data does **NOT** carry 30 hPa (its levels are 10, 50, 100,
  150, 200, 250, 300, 400, 500, 600, 700, 850, 925, 1000), so an IFS
  section uses eleven of the reference's twelve levels.  The C3S seasonal
  archive DOES carry 30 hPa.
- The bucket retains every daily cycle for about a month, so the **analysis
  half is the step-0 field of each day's 12Z cycle** - no ERA5 needed.

## The seasonal route: the C3S sub-daily archive  (PROVEN WORKING)
`seasonal-original-pressure-levels` carries `geopotential` at exactly the
reference's twelve levels, with `leadtime_hour` out to 5159 h = **215 days =
the full run**, plus an `area` widget.  There is **no member-selection
parameter** - all the members always come back (SEAS5 gives 51).
- The runs are initialised at **00Z on the 1st**, so the 12Z value of a day
  is at lead time **12 + 24k** hours, not 24k (a 24k lead lands against the
  wrong calendar day in the climatology).
- The archive caps the response size, so the request is chunked: 15 days at
  twelve levels over the polar cap fits; 30 days does not.
- A three-day request (the leads 36, 60, 84) is enough to get through the
  queue when the archive is congested.

## The GRIB reader: read validityDate, not dataDate
`eccodes.codes_get(gid, "dataDate")` returns a STRING ("20261015"), and
`dataTime` comes back as 0 on a fresh handle.  Reading the reference time
plus the step puts every ERA5 field at 00Z and every seasonal field a whole
day out.  Use **`validityDate`/`validityTime`**, which already carry the
reference time plus the step and work for both conventions:
- ERA5: dataTime 1200, step 0 -> validity 12Z
- the seasonal archive: the 00Z init plus the lead time -> validity 12Z
- `eccodes.codes_grib_new_from_file(f)` returns a HANDLE, not a generator:
  iterating over it raises a TypeError.

## The sandbox limits
- **3 GB of memory.**  A 100 MB byte-range buffer plus Python overhead gets
  the process OOM-killed.  Write the ranges straight to a file.
- Detached background processes are reaped when they sit idle.

## The validation that says the method is right
- The normalised anomaly of the ERA5 October against its own 1991-2020
  climatology, year by year, has a **30-year mean of 0.000**.
- The finished IFS section against the reference figure, sampled over the
  plot box: **the correlation of the anomaly field is 0.848** and the
  **sign agreement is 91.1%** (blue / warm / neutral).

## The design is ours, not the reference's

The reference figure (severe-weather.eu / @Recretos) was **measured** to
understand the physics and the geometry.  **None of its graphic design is
used** - the section is our own.

Kept, because it is physics and not decoration:
- the **logarithmic pressure axis** (10 hPa at the top, 1000 hPa at the
  bottom).  A linear axis crushes the stratosphere into a sliver.
- the separate **linear approximate-height axis** on the right.
- smooth `contourf` fills.

Replaced on purpose:
- the reference's 17-colour palette (blue -> white -> bright YELLOW ->
  orange -> red).  Ours is **navy -> white -> orange**, built from the
  colours the site already uses: `C_MEAN #12263f` and `C_ERA5 #c2410c`.
  Nine blues, one white centre, seven warms.
- the reference's **centred** title and subtitle.  Ours is **left aligned**
  with a plain-text summary on the right, the way the snow maps are done.
- the reference's "◄ ECMWF ANALYSIS / FORECAST ►" wording, its colour-bar
  label and its layout.

### The three-level shading
| part | alpha | meaning |
|---|---|---|
| ERA5 reanalysis | 1.00 | what happened |
| the model's own past days | 0.82 | the model's view of days that have passed |
| the model's future | 0.58 | what might happen |

The colour bar is drawn from a clean `ScalarMappable`, never from the last
`contourf` - otherwise it inherits that segment's alpha and looks washed
out.

## The scripts
- `polar_cap.py` - the zonal mean, the climatology, the normalisation and
  the drawing routine (shared by every route).
- `fetch_polar_era5_arco.py` - the ERA5 1991-2020 climatology from ARCO.
- `fetch_polar_era5_recent.py` - the 90-day ERA5 reanalysis from the CDS.
- `fetch_polar_models.py` - the seasonal forecast from the C3S archive.
- `fetch_polar_ec46.py` - the EC46 run from ECDS (needs the licence).
- `plot_polar_cap.py` - the section for a seasonal model.
- `tools/polar_queue.sh` - the two fetchers, one after the other.

## What is NOT in scope any more
The IFS 15-day chart and the AIFS ensemble spread were built, validated and
then **removed** at the user's direction: the section is for the SEASONAL
guidance and EC46 only.  A medium-range forecast is a different product and
does not belong here.

## The ARCO native store must NOT be used for the stratosphere (12 Nov 2026)

`ar/full_37-1h-0p25deg-chunk-1.zarr-v3` is ARCO's own vertical interpolation of the
ERA5 pressure levels, not the CDS product. It **mutes the stratospheric variability**:

| event | reduced store | ARCO native store | seasonal model / IFS |
|---|---|---|---|
| Jan 2013 SSW, 14 Jan 2013, 10 hPa | **+2.07 σ** | **−0.17 σ** | agrees with the reduced store |
| Dec 2010 SSW, 4 Dec 2010, 10 hPa | +0.53 σ | −0.9 σ | (a vortex split, weak cap-mean signal) |
| Feb 2019 SSW | −0.4 σ | — | (a vortex split) |

The January 2013 event is the clean test: the reduced store shows the textbook
0 → +2 σ rise over two weeks, the native store flattens it to +0.7 σ and sits 2 σ
too cold. So:

* the **reduced** store (`1959-2022-1h-240x121_equiangular_with_poles_conservative.zarr`)
  is faithful, and its climatology is the right one to normalise against — but it
  **ends in 2022**;
* the **CDS** (`reanalysis-era5-pressure-levels`) is the native product the seasonal
  models and the IFS agree with, so it is the route for both the recent 90 days and
  the climatology (`reanalysis-era5-pressure-levels-monthly-means`);
* `data/polar_cap_clim_native.npz` (the ARCO native climatology) is kept only for
  the record and is **not** used.

The rule that follows: *a climatology must be built from the same product and grid
as the data it normalises* — and here, the same product means the same publisher.
