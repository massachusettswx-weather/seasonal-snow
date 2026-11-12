# ECDS: the ECMWF Data Store API (the route to EC46 and S4S)

`https://ecds.ecmwf.int/api` - the `https://ecds.ecm.int/api` host is
unreachable from the sandbox (connection refused).

## The key

**The Copernicus CDS key in `.cdsapirc` works on ECDS as well.** No separate
ECDS account is needed. Send it as the `PRIVATE-TOKEN` header. The key's own
`url:` field stays `https://cds.climate.copernicus.eu/api` - that is the CDS,
not ECDS, and it is not what the S2S calls use.

## The request shape (the one that gets past validation)

```
POST https://ecds.ecmwf.int/api/retrieve/v1/processes/s2s-forecasts/execute
headers: PRIVATE-TOKEN: <key>, Content-Type: application/json
{
  "inputs": {
    "origin": "ecmwf", "level_type": "pressure",
    "variable": "geopotential_height", "level_value": ["1000_hpa"],
    "leadtime_hour": [24], "data_format": "grib"
  },
  "outputs": {"asset": {"value": {"type": "file"}}}
}
```

- `data_format` is an **input**, not an output. Sending it under `outputs`
  gives `422 model_attributes_type`.
- `outputs.asset.value.type` must be a **dict**: `{"type": "file"}`. The bare
  string `"file"` also gives `422`.
- `outputs` can be omitted entirely - the licence check still runs.
- The schema is at `GET /retrieve/v1/processes/s2s-forecasts` (needs the same
  token).

## The licence gate

The licence check runs **before** request validation, so a malformed request
still returns 403, not 422. **A 403 means "the licence is not accepted",
never "your request was wrong".**

The licence must be ticked by hand in the web UI:
`https://ecds.ecmwf.int/datasets/s2s-forecasts?tab=download#manage-licences`
There is **no API for it** - it cannot be done from a script.

## The catalogue

- `s2s-forecasts` - the real-time sub-seasonal to seasonal ensemble.
- `tigge-forecasts` - the TIGGE archive (gated the same way).
- `s2s-reforecasts` - the hindcast.

## The enums (from the process description)

- `origin`: bom, cma, cnr_isac, cptec, cnrm, eccc, **ecmwf**, hmcr, iap_cas,
  jma, kma, ncep, ukmo
- `level_type`: **pressure**, single_level, isentropic, oceanic
- `level_value` (pressure): 1000, 100, 10, 200, 300, 320_k, 500, 50, 700, 850,
  925 hPa - **ten levels, no 30 hPa and no 400 hPa**
- `variable`: includes **`geopotential_height`** (not `geopotential`)
- `forecast_type`: control_forecast, perturbed_forecast
- `leadtime_hour`: 359 values, 98 of them ranges; the max single lead is
  **1560 h (65 days)**; the daily leads are 24...1560 (65 values)
- `data_format`: grib (the only value)
- `area`: accepted

## Why this matters

The CDS seasonal datasets stop at 6 lead months and cannot give a
sub-seasonal product at all. **EC46 (the 46-day ensemble) is only on ECDS**,
and it is the only route to the polar-cap section for a sub-seasonal run.
