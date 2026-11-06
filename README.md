# Seasonal snow forecast maps (and the SEAS5 wind panels)

Everything behind the **seasonal snowfall anomaly site**: the ECMWF SEAS5
fetch, the climatologies, the map renderer, and the static site that publishes
the panels.

* **Site**: `site/` - a static, dependency-free page (plain HTML/CSS/JS) that
  lists the seasonal prediction systems that carry a snow variable and shows
  the rendered anomaly maps.  Rebuild it with `python3 build_site.py`.
* **Maps**: `output/` - the rendered PNGs (monthly + 3-month means, mm and
  inches).
* **Pipeline**: the fetch/render scripts listed below.

```
build_site.py            build site/ from output/ + the CDS catalogue
list_seasonal_systems.py  which CDS seasonal datasets carry a snow variable
fetch_seas5_snow.py       SEAS5 monthly-mean snowfall, 51 members
fetch_seas5_snow_hc.py    ECMWF hindcast climatology + ensemble_mean (provenance check)
fetch_era5_snow_arco.py  ERA5 1991-2020 snow climatology (ARCO-ERA5 derivation)
fetch_era5_snow_cds.py   official ERA5/ERA5-Land monthly-mean snowfall (CDS, queue-dependent)
fetch_relief.py          0.25 deg orography -> hillshade basemap
plot_snow_ref.py         the map renderer (see "Map renderer" below)
```

## Snow maps

`plot_snow_ref.py` renders the panels.  The house style:

* flat equirectangular projection (x compressed by cos 37N), CONUS domain
  125W-65W / 24.5-50N, 10 degree labelled graticule
* shaded relief basemap from 0.25 deg ERA5 orography, drawn over the US and
  Mexico; **Canada left white** with only a faint hint of its provinces
* the anomaly field is clipped at the US/Canada border
* brown -> white -> teal palette (the site's own colourbar), signed-log band
  ladder so small anomalies still read
* plain white canvas, bold far-left title, grey descriptor line, max/min stamp
  top-right, horizontal colourbar under the map, `@Massachusettswx` bottom-right

```
python3 plot_snow_ref.py --init 202611 --baseline hc  --unit in --window 1
python3 plot_snow_ref.py --init 202611 --baseline hc  --unit in --window 3
python3 plot_snow_ref.py --init 202611 --baseline era5 --era5 era5_snow_clim_cds.npz --unit in
```

Options: `--palette house|ref`, `--unit in|mm`, `--window 1|3`,
`--baseline hc|era5`, `--proj plate|lcc`, `--suffix`, `--era5`.

### Which climatology?

* `--baseline hc` (default) = anomaly vs **ECMWF's own `hindcast_climate_mean`**
  for the lead month - the ECMWF/C3S standard.  Both fields are on the same
  1 deg SEAS5 grid, so they are differenced natively.
* `--baseline era5` = anomaly vs an ERA5 1991-2020 snowfall climatology.
  ARCO-ERA5 has **no snowfall variable**, so `fetch_era5_snow_arco.py`
  derives it from precipitation x the fraction of sub-freezing six-hourly
  steps; that derivation is biased low in the mountains, which flips the sign
  over the Pacific NW.  The official ERA5 / ERA5-Land monthly-mean snowfall
  (`fetch_era5_snow_cds.py`) is the correct baseline when the CDS queue allows.

### Provenance

`fetch_seas5_snow_hc.py` also downloads ECMWF's `ensemble_mean` product and
checks it against the mean of the 51 `monthly_mean` members: they agree to
**1.8e-12 m/s (1.4e-05 relative)** - the data really is SEAS5.

---

# SEAS5 10 hPa zonal-mean zonal wind (60°N / NH) — pipeline

Reproduces the severe.weather.eu-style seasonal panel:
**daily** SEAS5 member traces + daily ECMWF ensemble mean, the daily
ERA5 1991–2020 climatology layer (mean, record min/max, 10–90/30–70
percentiles) and the ECMWF model-climate mean.

```
era5_layer.py            ERA5 daily climatology layer  -> era5_clim_10hpa.json   (no download)
fetch_seas5.py           CDS monthly statistics (ensemble_mean + hindcast_climate_mean)
fetch_seas5_daily.py     CDS subdaily "original" product -> 51 members x 215 daily 12Z steps
model_climate_m7.py      model climate for lead month 7 (not published by CDS) from past hindcasts
plot_seas5.py            monthly version of the panel
plot_seas5_daily.py      daily version of the panel  <-- matches the reference
plot_seas5_mwx.py        daily panel in the house style (own palette/layout)
plot_era5_only.py        ERA5 layer on its own
wait_and_build.py        polls the CDS for a new init, then builds everything
compare_reference.py     pixel calibration of the published reference PNG
```

## Key CDS facts (learned the hard way)

* dataset for members: `seasonal-original-pressure-levels`
  (monthly statistics live in `seasonal-monthly-pressure-levels`)
* `system=51` — since Nov 2022 C3S serves SEAS5 v5.1 under system 51;
  `system=5` returns NoData for recent inits.
* **never pass `area`** — any area selection → `MarsNoDataError`.
  The global 1.00° grid comes back (60°N is interpolated; the grid is centred
  on half-degrees 89.5…−89.5, latitude axis north→south).
* `leadtime_hour` for a 12Z daily series = `12, 36, 60, …`; 215 values cover
  the full 7-month window (lead months 1–7) of an init.
* the monthly-statistics product only has **lead months 1–6**
  (`fcmonth 7` → `MarsNoDataError`), so month 7 of the model-climate line is
  reconstructed in `model_climate_m7.py` from the model's own past runs.
* the subdaily product does **not** accept `product_type` (a request with
  `hindcast_climate_mean` → HTTP 400).
* ECMWF's seasonal contribution reaches C3S/CDS on the **6th at 12:00 UTC**;
  before that every request for the current init returns
  `AccessError: Restricted access to current C3S seasonal forecast ECMWF contribution`.
* the monthly `ensemble_mean` equals the mean of the 51 `monthly_mean`
  members to ~3e-5 m/s — that is the provenance check used here.

## ERA5 layer

Built offline from the user's own archive (`Forecast-charts` repo,
`data/store/archive/u_*.json.gz`, daily 12Z 1959–2020, 37 levels) —
**no ERA5 download**.  Per calendar day: mean, sd, p10/p30/p70/p90 and the
record min/max over **1991–2020** for 60°N, 70°N, NH (area-weighted) and a
polar-cap domain.  Window: **01 Oct of the init year → 10 Jun** (253 days).

Sanity anchor: 60°N / 10 hPa, 25 Oct → 21.31 ± 4.48 m/s.

## Plot construction (daily version)

| element | source |
|---|---|
| grey spaghetti (51) | daily SEAS5 member values, 12Z |
| black mean | daily ensemble mean |
| blue solid | ERA5 1991–2020 daily mean |
| blue dashed / red dashed | ERA5 daily record min / max (1991–2020) |
| light-blue bands | ERA5 30–70 and 10–90 daily percentiles (1991–2020) |
| red solid | ECMWF model-climate mean: monthly HCMEAN anchors (leads 1–6) interpolated to a daily curve with a monotone cubic; lead month 7 taken from the reconstructed model climate |
| x-axis | 01 Oct of the init year → 01 May (7 months), month-start labels `01 Oct` / `2026` |

Validated against the published reference (same init, October 2026):
ERA5 mean curve within ~1–3 m/s, record min/max matching, model-climate
curve within ±1.3 m/s, daily ensemble mean 11.6 m/s on 01 Oct and −3.1 m/s
on 01 May vs ~13 and ~−2 read off the reference.

## Snow anomaly maps (SEAS5 vs ERA5 climatology)

- `fetch_seas5_snow.py` - SEAS5 monthly-mean snowfall for an init
  (`seasonal-monthly-single-levels`, variable `snowfall`, units
  "m of water equivalent s**-1") -> `data/seas5_<tag>_snow.npz`
  `[member, lead, lat, lon]`.
- `fetch_era5_snow_arco.py` - ERA5 1991-2020 monthly SNOW climatology for the
  eastern-US box, built from ARCO-ERA5 (Google Cloud) because the CDS ERA5
  queue was unusable.  ARCO's single-level stores have **no snowfall**, so
  snow = 24 h precipitation x fraction of the day's six-hourly steps with
  2 m T < 0 degC.  ARCO store:
  `ar/1959-2022-6h-240x121_equiangular_with_poles_conservative.zarr`
  (chunks are 8 time steps; decode with numcodecs.Blosc).
- `plot_snow_anomaly.py` - one single-panel map per lead month, green =
  above average, brown = below, land-only mask from the US-states GeoJSON
  (matplotlib Path.contains_points, then a one-cell dilation).


### Reference-style snow maps (new, 2026-11-06)
`plot_snow_ref.py` reproduces the look of the satellitexw.com ECMWF seasonal
snowfall-anomaly panels:

* **Lambert conformal conic** (33/45N, central meridian 96W) - the projected
  grid is curvilinear, so both the basemap and the anomaly are drawn with
  `pcolormesh` (`shading="nearest"`, `edgecolors="face"` - without the
  face-coloured edges the projected quads leave a faint diagonal hatch).
* **Shaded relief** (drawn over the US and Mexico only - Canada is left white,
  with just a faint hint of its provincial boundaries) from ARCO-ERA5
  `geopotential_at_surface`
  (`ar/1959-2022-6h-1440x721.zarr`, chunk `0.0`) -> orography -> hillshade
  (`fetch_relief.py` -> `data/relief_025.npz`); ocean is white, land shows
  the hillshade through the translucent anomaly layer (alpha 0.70).
* **Borders** from Natural Earth 50m: `ne_50m_admin_1_states_provinces`
  (US states, Canadian provinces) and `ne_50m_admin_0_countries`
  (thick US national outline = the international border).
* **Field clipped at the US/Canada border** - the mask is the union of the US
  state polygons, so nothing is drawn north of the border.
  Mask gotcha: NE's Alaska ring crosses the antimeridian, so a compound
  Path with it corrupts every `contains_points` test - drop polygons whose
  vertices are outside the view window and OR the per-polygon tests.
* **Palettes**: `--palette house` (default) = the user's own colourbar sampled
  from their pasted bar: brown `#654116` -> near-white -> teal `#1f4c44`
  (brown = below average, teal = above). `--palette ref` = the blue/red
  satellitexw convention (option only - do not ship it by default).
* **Baselines**: `--baseline hc` (default) = anomaly vs **ECMWF's own
  `hindcast_climate_mean`** for that lead month (the ECMWF/C3S standard); both
  fields are on the same 1 deg SEAS5 grid so they are differenced natively.
  `--baseline era5` = anomaly vs an ERA5 1991-2020 snowfall climatology
  (`--era5 <npz>`).  The ARCO-derived ERA5 snow climatology is biased low in
  the mountains (ARCO has no snowfall variable - it is precip x sub-freezing
  fraction), which flips the sign over the Pacific NW; the official ERA5 /
  ERA5-Land monthly-mean snowfall is the fix (`fetch_era5_snow_cds.py`).
* `--era5 <npz>` selects the climatology file, `--suffix <s>` adds a filename
  suffix (used for the `_era5` variants).
* `--unit in|mm` (default `in`): switches the whole figure to inches of water
  equivalent - colourbar label, max/min stamp, descriptor and the band ladder
  all follow.  1 in = 25.4 mm w.e.
* `--window 1|3`: `1` = the six single-month panels, `3` = the rolling 3-month
  means (NDJ, DJF, JFM, FMA - the 3-month windows that fit the six available
  lead months).  The 3-month anomaly is the mean of the three monthly
  anomalies, so the baseline is the matching 3-month mean of the climatology.
* Provenance: `fetch_seas5_snow_hc.py` also downloads `hindcast_climate_mean`
  and `ensemble_mean` and proves the member set: mean(51 monthly_mean members)
  == ensemble_mean to 1.8e-12 m/s (1.4e-05 relative).

### SEAS5 resolution
The CDS seasonal datasets have **no resolution parameter** and
`seasonal-monthly-single-levels` (system 51) returns a 1.00 deg global grid
(Ni=360, Nj=180).  There is no higher-res SEAS5 in the CDS, so "higher res"
on a map has to come from the display grid: the 1 deg field is smoothed on
its native grid, then bilinearly interpolated onto a 0.05 deg display grid
before contouring - which is exactly how the reference panel looks.

### CDS API changes (2026-11)
* `reanalysis-era5-single-levels` no longer accepts
  `product_type=monthly_averaged_reanalysis` - it is silently rejected with
  "None of the data you have requested is available yet".  Monthly means now
  live in **`reanalysis-era5-single-levels-monthly-means`** (and
  `reanalysis-era5-land-monthly-means`), while the plain dataset only accepts
  `reanalysis / ensemble_mean / ensemble_members / ensemble_spread`.
* The ERA5 datasets were also queue-saturated all morning
  ("Maximum number queued requests for this dataset has been reached") - the
  seasonal datasets were fine, so the congestion is ERA5-specific.
* Find the valid parameters without guessing:
  `GET {api}/retrieve/v1/processes/{dataset}` (JSON, has the enums) and
  `GET {api}/catalogue/v1/collections?limit=2000` (dataset list).

## Credentials

`.cdsapirc` holds the CDS API token (mode 600, never commit).
