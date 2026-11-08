# Seasonal forecast graphics

Snowfall and 10 hPa zonal-mean zonal wind (SPV) panels from the ECMWF SEAS5
and the C3S seasonal prediction systems, for the November 2026 / October 2026
inits.

## What is here

```
site/            the static site (this is what GitHub Pages serves)
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

## Pushing to GitHub

```bash
./push_to_github.sh <github_token> [repo_name]
```

Creates `massachusettswx-weather/seasonal-snow`, pushes `main`, enables Pages
(source: main / root) and prints the live URL. See `GITHUB_TOKEN.md` for how
to mint the token.

## The pipeline

| script | what it does |
|---|---|
| `fetch_models.py` | downloads snowfall (forecast + the model's own hindcast climate) and 10 hPa u for every released system, at its own init |
| `plot_snow_models.py` | renders the accumulation totals, the per-lead-month totals and the monthly anomalies for every model |
| `build_spv_panels.py` | renders the 10 hPa SPV chart and the lead-month table for every model |
| `build_registry.py` | collects the rendered panels into `site/data/models.json` |
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
