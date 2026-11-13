# The sub-seasonal half of the polar cap section: GEFS v12 and EC46

The seasonal route (`fetch_polar_models.py`, C3S `seasonal-original-pressure-levels`)
only reaches the seasonal models.  Two more sources for the SAME quantity -
the area weighted (cos(lat)) mean geopotential height over 60-90N on twelve
pressure levels, daily 12Z - were looked for: NOAA's GEFS v12 and ECMWF's
EC46.  One works, one is behind a licence that has to be ticked by hand.

## (A) NOAA GEFS v12 - WORKS

### The route

    https://nomads.ncep.noaa.gov/pub/data/nccf/com/gens/prod/gefs.YYYYMMDD/HH/

The same tree is served verbatim by the AWS open-data bucket

    https://noaa-gefs-pds.s3.amazonaws.com/gefs.YYYYMMDD/HH/

and it also sits under `.../com/gens/v12.3/` (the version tag).  `gens` is
the GEFS tree of the new GFS system; `v12.3` is its version.  The archive
keeps four cycles a day (00, 06, 12, 18Z) and about four days.

Under the cycle:

    atmos/init/            the model initial conditions (netCDF tiles)
    atmos/pgrb2ap5/        the 0.50 degree GRIB2, half "a"
    atmos/pgrb2bp5/        the 0.50 degree GRIB2, half "b"
    atmos/pgrb2sp25/       the 0.25 degree GRIB2, SURFACE ONLY

There is no request to make: the files are fetched by HTTP GET.  The script
`fetch_polar_gefs.py` discovers the newest cycle, then for every daily 12Z
lead it pulls the `.idx` file beside each member's GRIB2 and fetches only the
twelve HGT messages with byte-range requests.

### The numbers

* **members: 31.**  `gec00.*` is the control, `gep01.*` ... `gep30.*` are the
  perturbed members.  (The brief said four; the archive says thirty-one, and
  the archive is what the data is.  The four-member product is the S2S
  archive on `s2s.noaa.gov`, which is not reachable - see below.)
* **the run: 20261113 00Z**, the cycle that was live when this was done.
* **the span: 16 days, 2026-11-13 12Z to 2026-11-28 12Z**, i.e. the leads
  12, 36, ..., 372 h.  The 0.50 degree archive itself runs out to lead 840 h
  (35 days, 6-hourly beyond f240); the section uses the 16-day window.
* **the grid: 0.50 x 0.50, 720 x 361**, 61 rows inside the cap (60.0N to
  90.0N, 0.5 degree apart).
* **the levels: all twelve** - 10, 30, 50, 100, 200, 300, 400, 500, 700, 850,
  925, 1000 hPa.  The GRIB2 `HGT` is in **geopotential METRES**, so it is
  multiplied by 9.80665 to land on the same m2/s2 scale as the ERA5 half.
* **the file key: `gefsv12`** in `data/polar_model_z.json`, in the same
  shape the seasonal puller writes (`times`, `values`, `members`, `levels`),
  with `run` and `source` added.

### The gotchas

* **The twelve levels are split over the two halves.**  The "a" half has
  10, 50, 100, 200, 250, 300, 500, 700, 850, 925, 1000 hPa; the "b" half
  has 1, 2, 3, 5, 7, 20, **30**, 70, 150, 350, **400**, 450, ... hPa.  A
  request that reads only the "a" half is missing 30 and 400 hPa.
* **The 0.25 degree tree is surface only.**  `pgrb2sp25` holds the surface
  fields and nothing else, so it cannot serve the section.
* **The `.idx` file has no length field.**  The line is
  `index:offset:d=YYYYMMDDHH:VAR:level:fcst:ens`, so the length of a
  message is the OFFSET OF THE NEXT MESSAGE, and the last message runs to
  the size of the file.  The byte range of a message is therefore
  `bytes=offset_next-1` backwards to its own offset.
* **`geavg` is published late.**  NCEP's own ensemble mean (and the spread,
  `gespr`) only appears once the whole ensemble is done; in the live cycle
  the "b" half's `geavg` was not there yet while the member files were.  So
  the series is computed from the 31 member files instead - and it comes out
  IDENTICAL to NCEP's `geavg` (checked at 2026-11-13 12Z: 296403, 197140,
  153904, 110144, 84790, 51403, 27569, 13219, 6875, 997 m2/s2 at 10, 50,
  100, 200, 300, 500, 700, 850, 925, 1000 hPa, to the last digit).
* **NOMADS answers 503 in bursts** under a lot of parallel requests, so the
  puller retries, and the AWS mirror is the fallback host.  A byte range
  comes back as HTTP **206**, not 200 - a client that only accepts 200 will
  call that a failure.
* The live cycle grows while it is read: f348 and f372 were not there when
  the first pass ran and were there ten minutes later.

### The routes that do NOT work from here

| route | answer |
|---|---|
| `https://nomads.ncep.noaa.gov/pub/S2S/` | 403 - the directory does not exist on NOMADS |
| `https://nomads.ncep.noaa.gov/pub/data/nccf/com/s2s/` | 403 - same |
| `https://s2s.noaa.gov` | the name does not resolve |
| `https://noaa-s2s-pds.s3.amazonaws.com` | `NoSuchBucket` |
| `https://ftp.cpc.ncep.noaa.gov/S2S/` | only the CFSv2 real-time tars (TIGGE format); no GEFS |
| `https://ftp.cpc.ncep.noaa.gov/S2S/S2SHC/` | empty |

(NOMADS answers **403** for a directory that does not exist and 404 for a
file that does not, so a 403 on a listing means "no such tree", not "no
permission".)

## (B) ECMWF EC46 - BLOCKED BY THE LICENCE

### The route and the request

    POST https://ecds.ecmwf.int/api/retrieve/v1/processes/s2s-forecasts/execute
    headers: PRIVATE-TOKEN: <the CDS key in .cdsapirc>, Content-Type: application/json
    {
      "inputs": {
        "origin": "ecmwf", "system": 46,
        "year": "2026", "month": "11", "day": "13", "time": "00:00",
        "level_type": "pressure",
        "variable": ["geopotential_height"],
        "level_value": ["10_hpa", "50_hpa", "100_hpa", "200_hpa", "300_hpa",
                        "500_hpa", "700_hpa", "850_hpa", "925_hpa", "1000_hpa"],
        "forecast_type": ["control_forecast", "perturbed_forecast"],
        "leadtime_hour": ["24_48", "48_72", ..., "456_480"],
        "area": [90, -180, 60, 180],
        "data_format": "grib"
      },
      "outputs": {"asset": {"value": {"type": "file"}}}
    }

The key in `.cdsapirc` works on ECDS as well; the key's own `url:` field
stays the CDS and is not used here.  `data_format` is an INPUT, not an
output; `outputs.asset.value.type` must be the dict `{"type": "file"}`.

### The blocker

Every request is refused with

    HTTP 403 {"type": "permission denied", "title": "required licences not accepted",
              "detail": "Not all the required licences have been accepted; please visit
                         https://ecds.ecmwf.int/datasets/s2s-forecasts?tab=download#manage-licences ..."}

What was tried:

* the full request above with `system: 46` - 403, the licence refusal;
* the same request without `system` and without `outputs` - 403, the same
  refusal (so the shape is not what is wrong);
* a deliberately malformed request (year 1999, month 99) - 400 "No valid
  dates", which shows the dates are checked before the licence and that a
  well-formed request reaches the licence gate;
* `GET /api/retrieve/v1/processes` - 200, the three processes are
  `s2s-forecasts`, `s2s-reforecasts`, `tigge-forecasts`;
* `GET /api/licences` and `GET /api/retrieve/v1/licences` - 404: **there is
  no API to accept the licence**.  It has to be ticked by hand in the web UI
  at the link above.

So the EC46 series cannot be built until the licence is accepted.  The
script `fetch_polar_ec46.py` is ready for it and writes **nothing** while
the licence is refused - a chart must never be published without real data
behind it.  When the licence is accepted it will write the `ec46` key in
`data/polar_model_z.json` in the same shape as the other records.

Two things to know about EC46 when it does run:

* the catalogue's `level_value` enum holds **ten** pressure levels - no
  30 hPa and no 400 hPa - so an EC46 section would carry ten levels rather
  than the reference's twelve (the same limitation the S2S catalogue has for
  every centre);
* the `leadtime_hour` ranges are the weekly windows 24_48 ... 456_480, so
  the series is a set of weekly windows, not the daily 12Z series the
  seasonal and GEFS routes give.

## The check on the GEFS series

The polar-cap mean geopotential height at 10 hPa, from
`data/polar_model_z.json["gefsv12"]` (the ensemble mean of 31 members):

    first day  2026-11-13 12Z   296403 m2/s2   = 30225 m
    last day   2026-11-28 12Z   289602 m2/s2   = 29531 m

Both are inside the 290000-300000 m2/s2 band the polar cap lives in at
10 hPa, and the 16-day drift is smooth and of the right size for the
season.  The 500 hPa level comes out at 51403 m2/s2 (5241 m), which is the
right size for the 500 hPa surface as well.

## The scripts

* `fetch_polar_gefs.py` - the GEFS v12 series, into the key `gefsv12`.
* `fetch_polar_ec46.py` - the EC46 series, into the key `ec46` (licence).
* `verify_polar_gefs.py` - our ensemble mean against NCEP's own `geavg`.
