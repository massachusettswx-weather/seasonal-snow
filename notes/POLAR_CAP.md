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

## The scripts
- `polar_cap.py` - the zonal mean, the climatology, the normalisation and
  the drawing routine (shared by every route).
- `fetch_polar_era5_arco.py` - the ERA5 1991-2020 climatology from ARCO.
- `fetch_polar_ifs.py` - the IFS forecast from the open data bucket.
- `fetch_polar_analysis.py` - the IFS analyses (the step-0 field of each
  day's cycle) for the half before the init.
- `fetch_polar_models.py` - the seasonal forecast from the C3S archive.
- `fetch_polar_recent.py` - the ERA5 analysis from the CDS.
- `plot_polar_ifs.py` - the section for the IFS.
- `plot_polar_cap.py` - the section for a seasonal model.
