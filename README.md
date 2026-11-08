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
| UKMO GloSeas6-GC5.1 | 2026-10 | 60 | yes | yes (monthly) |
| ECCC CanESM5.1p1bc | 2026-10 | 20 | yes | yes (monthly) |
| ECCC GEM5.2-NEMO | 2026-10 | 20 | yes | yes (monthly) |
| CMCC SPS4 | 2026-10 | 50 | yes | yes (monthly) |
| DWD GCFS2.2 | 2026-10 | 50 | yes | yes (monthly) |

**Why the different inits.** The non-ECMWF C3S contributions are date
restricted: as of 7 Nov 2026 they answer the 1 Nov 2026 init with
*"Restricted access to current C3S seasonal forecast non-ECMWF contribution"*,
i.e. the November runs are not released yet. Each model is therefore shown from
its own most recent released init, and every figure is labelled with it.

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

```bash
python3 fetch_models_daily.py --auto   # queue, download and decode (self-healing)
```

Each centre lands in `data/models/<tag>/u10_daily.npz` as a
`members x days` matrix for 60N and the NH. `build_spv_panels.py` uses it
automatically when it is present and falls back to the monthly GRIB otherwise.

Three things bite when doing this:

* **The queue gate.** The CDS rejects a request outright when too many of ours
  are already waiting ("Maximum number queued requests for this dataset"), and
  it applies across datasets. Only about three jobs can sit queued at once, so
  the fetcher keeps a pool of three and refills it as jobs come off. Request
  *size* is irrelevant - even a one-step request is rejected.
* **Stale jobs count.** Jobs left behind by an earlier probe storm keep the
  account blocked for hours. `python3 dismiss_jobs.py` clears them
  (`DELETE /retrieve/v1/jobs/{jobID}`). It only touches rejected/failed jobs,
  never the live ones.
* **Disk.** A 215-day pull is ~2.5 GB, so each download is decoded to a small
  `.npz` and the raw GRIB is deleted straight away.

`u10_daily.py` is the shared decoder. It groups records by *valid date*
rather than by lead time, because UKMO perturbs the member start dates, and
it was validated to reproduce the existing ECMWF daily series bit for bit.

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
| `fetch_models.py` | downloads snowfall (forecast + the model's own hindcast climate) and 10 hPa u for every released system, at its own init |
| `plot_snow_models.py` | renders the accumulation totals, the per-lead-month totals and the monthly anomalies for every model |
| `build_spv_panels.py` | renders the 10 hPa SPV chart and the lead-month table for every model |
| `build_registry.py` | collects the rendered panels into `docs/data/models.json` |
| `build_site.py` | builds the three pages and the stylesheet |
| `cds_direct.py` | a small direct CDS client (the stock one retries for hours) |
| `scan_inits.py` | scans init months to find which are released |

Earlier, ECMWF-only scripts are still here: `fetch_seas5.py`,
`fetch_seas5_daily.py`, `fetch_seas5_snow.py`, `plot_seas5_mwx.py`,
`plot_snow_ref.py`, `plot_snow_totals.py`, `model_clim_m7.py`.

## House style

* **Snowfall** is accumulated water equivalent in inches (1 in = 25.4 mm w.e.),
  labelled "in w.e." - not snow depth, since that needs a fresh-snow ratio we
  do not have.
* **Accumulation totals** use the weathermodels.com snow-total colourbar,
  sampled pixel-exactly from their published bar into
  `data/weathermodels_scale.json`.
* **Anomalies** use the brown -> white -> teal palette with a signed-log band
  ladder, and each model is measured against **its own** hindcast climate
  (ECMWF's `hindcast_climate_mean`), not a borrowed baseline.
* The field stops exactly at the US/Canada border; Canada is left plain white
  with a faint hint of its provincial boundaries.
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
* ERA5 climatology 1991-2020 and the 1959-2020 record bounds: the local ERA5
  daily archive, rebuilt from the public reanalysis store.
* Orography for the shaded relief: ERA5 orography.

`.cdsapirc` holds the CDS key and is **never** committed.
