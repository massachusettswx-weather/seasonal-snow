# Seasonal forecast graphics

Snowfall and 10 hPa zonal-mean zonal wind (SPV) panels from the ECMWF SEAS5
and the C3S seasonal prediction systems, for the November 2026 / October 2026
inits.

## What is here

```
docs/            the static site (GitHub Pages publishes this directory)
  index.html     home: pick a seasonal model
  model.html     that model's variables: snowfall / 10 hPa zonal wind
  snow.html      snowfall: total for the run, per-lead-month totals, and the
                 monthly anomalies with a drag bar
  spv.html       10 hPa zonal-mean zonal wind, 60N and NH, per model
  assets/maps/   the rendered snow panels
  assets/spv/    the rendered SPV charts
  data/          the model registry the pages read
```

## Models on the site

| model | init | members | snowfall | 10 hPa wind |
|---|---|---|---|---|
| ECMWF SEAS5 | 2026-11 | 51 | yes | yes (daily) |
| UKMO GloSeas6-GC5.1 | 2026-11 | 60 | yes | yes (daily, monthly fallback) |
| Meteo-France System 9 | 2026-11 | 51 | yes | yes (monthly) |
| ECCC CanESM5.1p1bc | 2026-10 | 20 | yes | yes (monthly) |
| ECCC GEM5.2-NEMO | 2026-10 | 20 | yes | yes (monthly) |
| CMCC SPS4 | 2026-11 | 50 | yes | yes (daily, monthly fallback) |
| DWD GCFS2.2 | 2026-11 | 50 | yes | yes (monthly) |
| JMA JRA3-25 | 2026-11 | - | yes | yes (daily) |
| BOM ACCESS-S2 | 2026-11 | - | yes | yes (daily) |
| NOAA SFSv1 | 2026-11 | 31 | yes (12 lead months) | no - NOAA publishes no 10 hPa winds |
| NOAA CFSv2 | 2026-10 | 40 | yes | no - CPC publishes no 10 hPa winds |
| C3S Multi-Model Mean | - | - | yes | - |

**Why the different inits.** C3S releases ECMWF on the 6th of the month and
every other centre on the 10th, at 12 UTC, and each centre is staged
separately, so a centre can lag by days. Each model is therefore shown from
its own most recent released init, and every figure is labelled with it.

**The lead months past the sixth.** The C3S *monthly statistics* dataset stops
at lead month 6, but the systems themselves run further - the ECMWF to 215
days (eight lead months), the UKMO and the ECCC to 214/215 days (seven). The
extra months only exist in the **original (sub-daily)** product, where every
step carries its own accumulation, so `fetch_snow_ext.py` pulls the tail of
each run and the renderer merges those months into the totals.

**The NOAA systems come from NOAA, not from C3S.** C3S's NCEP entry serves no
recent data at all, so both NOAA systems are read from NOAA itself:

* `fetch_sfs.py` reads the SFSv1 monthly forecast and reforecast from
  `s3://noaa-oar-sfsdev-pds` (public, anonymous HTTP + zarr). `beta3` carries
  the 1 Nov 2026 init and a **12-month run** (1 Nov 2026 - 31 Oct 2027) - the
  longest on the site.
* `fetch_cfsv2.py` reads the monthly means CPC publishes for the 1 Nov 2026
  init (`www.cpc.ncep.noaa.gov/products/CFSv2`). Those files hold the anomaly
  of the 40-member ensemble mean against the 1991-2020 CFSv2 hindcast
  climatology, so the absolute snowfall is ERA5's climatology plus that
  anomaly - an approximation, and the figure says so.

Neither NOAA source publishes a 10 hPa wind, so those two models have snowfall
panels only.

## Refreshing after the C3S release (expected 10 Nov 2026)

The fetch script does not hard-code an init - it probes each system backwards
and takes the freshest init that actually returns data. So when the November
runs appear:

```bash
python3 fetch_models.py      # re-fetch; picks up the November inits
python3 plot_snow_models.py  # re-render the snow panels
python3 build_spv_panels.py  # re-render the SPV charts
python3 build_registry.py    # collect the panels into the registry
python3 build_site.py        # rebuild the site
```

## Daily 10 hPa winds for every centre

The monthly product gives one value per lead month, which makes a very coarse
SPV chart. The C3S **original (subdaily)** product carries every ensemble
member at 12-hourly resolution, so the same daily chart as the ECMWF panel can
be drawn for every centre.

The daily wind is pulled by the same pool as everything else - see
**The queue** below. Each centre lands in `data/models/<tag>/u10_daily.npz` as a
`members x days` matrix for 60N and the NH. `build_spv_panels.py` uses it
automatically when it is present and falls back to the monthly GRIB otherwise.

The daily series is pulled in **72-day chunks** and merged. A 72-day chunk
completes; 143 days and up are refused, so one request for the whole run does
not work. One centre is finished before the next one is started, because a
half-pulled centre cannot be published.

Three things bite when doing this:

* **The queue gate.** The CDS refuses a request when too many of ours are
  already waiting ("Maximum number queued requests for this dataset"), and the
  limit is on what *this account* holds - it applies across datasets. See
  **The queue** below for the measured behaviour.
* **Stale jobs count.** Jobs left behind by an earlier probe storm keep the
  account blocked for hours. `python3 dismiss_jobs.py` clears them
  (`DELETE /retrieve/v1/jobs/{jobID}`). It only touches rejected/failed jobs,
  never the live ones.
* **An accepted job is not a lost job.** The job list returns only the most
  recent requests, so an old job that is still queued can look as if it were
  purged - it is not. Always check a job by its full UUID (`GET
  /retrieve/v1/jobs/{jobID}`) before assuming it is gone, and keep a watcher
  on it.
* **Disk.** A 72-day chunk is ~700 MB, so each download is decoded to a small
  `.npz` and the raw GRIB is deleted straight away.

## The queue

Everything that goes into the seasonal archive goes through **one** submitter,
`run_nov_queue.py`. Two submitters would simply fight over the same slots.
The behaviour below was measured on 11 November 2026, not read off a
manual.

* **A request is admitted, then judged.** Submission returns HTTP 201 and the
  verdict arrives 20-45 s later. A refusal is therefore *not* a bad payload -
  a bad payload is a 400 at submission time. The refusal message is
  "Maximum number queued requests for this dataset has been reached".
* **The limit is on what this account holds**, and it applies across
  datasets: with two requests held, a third is refused whether it targets the
  same dataset or a different one. The ceiling drifts with the archive's
  global queue depth, so a third does slip in now and then.
* **A refusal is free** - the slot comes straight back. The pool keeps asking
  rather than giving up, so a refusal is never a reason to stop.
* **The init month matters more than anything else.** The same centre, the
  same shape and the same dataset serves in 12 s for the October init and is
  refused in 24 s for the November one. That is a property of the archive.
  October is used as a fast probe of *payload validity* only - never as a
  substitute for the November init.
* **Pack each request with everything the dataset allows.** One request
  carries a centre's snowfall *and* its sea-surface temperature
  (`variable` as a list), which halves the slots a centre costs.
* **Never dismiss a queued request** to make room for another. Two of ours
  have sat queued for hours and both completed.

The pool's work list, in priority order, is the monthly snowfall and SST of
the centres that are missing from the site or off the November init; their
hindcast climate (without it their anomaly panels cannot be drawn); the
extension past the sixth lead month (it is what carries the multi-model mean
out to the end of the C3S range); and then the daily 10 hPa wind in 72-day
chunks.


`u10_daily.py` is the shared decoder. It groups records by *valid date*
rather than by lead time, because UKMO perturbs the member start dates, and
it was validated to reproduce the existing ECMWF daily series bit for bit.

## Lead-month labelling (the rule that catches everyone)

A `monthly_mean` GRIB field is **valid at the end of the averaging period**.
A field with `step = 720 h` from a 1 October init is valid 1 November and
therefore describes **October**. The lead month is the month of
*(valid date − 1 day)* - the same convention for every product.

| init | lead 1 | lead 6 |
|---|---|---|
| ECMWF SEAS5, 1 Nov 2026 | November 2026 | April 2027 |
| CMCC / DWD / ECCC / UKMO, 1 Oct 2026 | October 2026 | March 2027 |

The snowfall panels and the SPV charts must use the same rule, otherwise the
lead-month tables compare the model against the wrong ERA5 calendar month.

Checked against ERA5: the ECMWF 10 hPa seasonal cycle over the Great Lakes
correlates **r = 0.96** with the ERA5 calendar climatology at zero offset, so
lead *k* really is calendar month *k*.

## Pushing to GitHub

```bash
./push_to_github.sh <github_token> [repo_name]
```

Creates `massachusettswx-weather/seasonal-snow`, pushes `main`, enables Pages
(source: main /docs) and prints the live URL. See `GITHUB_TOKEN.md` for how
to mint the token.

## The pipeline

| script | what it does |
|---|---|
| `cds_direct.py` | a small direct CDS client (the stock one retries for hours) |
| **`run_nov_queue.py`** | **the single CDS submitter** - the monthly fields, the hindcast climate, the lead-month-7 extension and the daily 10 hPa wind, in priority order |
| `run_nov_pool.sh` | the supervisor that restarts `run_nov_queue.py` if it exits |
| `fetch_models.py` | downloads snowfall (forecast + the model's own hindcast climate) and 10 hPa u for every released system, at its own init |
| `fetch_new_centre.py` | a one-off entry point for a single centre: any of snow / sst / clim / u10, or `--watch <job-id>` for a job already queued |
| `fetch_models_daily.py` | the chunked daily 10 hPa puller, now driven by `run_nov_queue.py` |
| `fetch_snow_daily.py` | the chunked daily snowfall puller (the decoder it shares) |
| `fetch_snow_ext.py` | the lead months past the sixth, from the sub-daily product |
| `fetch_enso.py` | the SST for the ENSO plumes, and the plume indices |
| `fetch_ersst.py`, `fetch_oni.py`, `fetch_era5_enso.py` | the observed analysis and the ERA5 basin climatology the plumes are drawn against |
| `fetch_sfs.py`, `fetch_cfsv2.py` | the two NOAA systems, read from NOAA itself |
| `model_clim_m7.py` | rebuilds the ECMWF lead-month-7 model climate from the model's own past runs |
| `plot_snow_models.py` | renders the accumulation totals, the per-lead-month totals and the monthly anomalies for every model |
| `plot_snow_multi.py` | the C3S multi-model mean snowfall |
| `build_spv_panels.py` | renders the 10 hPa SPV chart and the lead-month table for every model |
| `plot_enso.py` | renders the ENSO plumes for every centre |
| `build_registry.py` | collects the rendered panels into `docs/data/models.json` |
| `build_site.py` | builds the pages and the stylesheet |
| `verify_site.py` | checks the published pages: status, broken images, console errors |

`plot_snow_ref.py` and `plot_snow_totals.py` hold the shared map drawing and
the colour scale; `u10_daily.py` and `enso_common.py` are the shared decoders.
The ECMWF's lead month 7 model climate is a build artefact,
`data/model_clim_m7_month<MM>.npz`, reconstructed from the model's own past
runs by `model_clim_m7.py` and spliced into the daily climate curve by
`plot_spv.py`.

## House style

* **Snowfall** is shown in **inches of snow depth** (standard 10:1 snow-to-water
  ratio) on a fixed 0-300 in colour bar, because that is the unit the bar is
  built for: a 6-month total of 26.7 in w.e. is 267 in of snow, which lands at
  89% of the bar, whereas the water equivalent itself sits in the bottom 9%
  and reads as "far too little snow".  There is **no liquid-equivalent option**
  on the site any more; `plot_snow_models.py --unit snow` makes the panels.
* **Accumulation totals** use the snow-depth colour bar, sampled into
  `data/snow_depth_scale.json`.
* **Single-month panels** use the same fixed 0-300 in ladder as the total, so
  the months add up to the total panel in the same colours.
* **No snowfall is white**: the bottom of the ramp is white and everything
  under the first level is masked, so "no snow" reads as no snow.
* **Every model's snowfall season ends 01 July 2027** whatever the model
  itself runs to, so the panels are comparable; the title carries the actual
  init and end dates and the descriptor line the grid resolution.
* **Anomalies** use the brown -> white -> teal palette with a signed-log band
  ladder, and each model is measured against **its own** hindcast climate
  (ECMWF's `hindcast_climate_mean`), not a borrowed baseline.
* The field stops exactly at the US/Canada border; Canada is left plain white
  with a faint hint of its provincial boundaries.
* **Flat white basemap.** The hillshade was removed so that a white area means
  "no snow" rather than "terrain shading". Mexico is unshaded, and the Great
  Lakes (Natural Earth lake outlines) are excluded from the field, so Michigan
  reads as a mitten beside a lake instead of one solid blob.
* Flat CONUS projection (125W-65W, 24.5-50N), 10 degree labelled graticule,
  black state borders and a heavy black national outline.
* **SPV** charts show every ensemble member, the ensemble mean, the ERA5
  1991-2020 daily climatology with 10-90th and 30-70th percentile bands and
  the 1959-2020 record bounds, plus the model's own climate mean where one
  could be built.
* Every figure is credited `@Massachusettswx`.

## Data

* Seasonal forecasts: Copernicus CDS (`seasonal-monthly-single-levels`,
  `seasonal-monthly-pressure-levels`, `seasonal-original-pressure-levels`).
* NOAA SFSv1: `s3://noaa-oar-sfsdev-pds` (zarr). NOAA CFSv2: NCEP CPC monthly
  means (netCDF).
* ERA5 climatology 1991-2020 and the 1959-2020 record bounds: the local ERA5
  daily archive, rebuilt from the public reanalysis store.
* Orography for the shaded relief: ERA5 orography.

`.cdsapirc` holds the CDS key and is **never** committed.
