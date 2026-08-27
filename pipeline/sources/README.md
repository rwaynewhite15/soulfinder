# Source data

Everything here is **prototype seed data**: approximations of publicly reported
figures, compiled by hand so the pipeline has something end-to-end to run on.
It is good enough to exercise and validate the machinery and to make the app
real; it is **not** a citable source, and no number in it should be quoted.

Swapping in the authoritative data is meant to be a file drop — the loaders in
`soulfinder/io.py` read exactly these schemas.

| File | Replace with | Notes |
|---|---|---|
| `national_religion.csv` | Pew Research Center, *Religious Composition by Country, 2010–2050* | Same 8 categories, same decadal grid. Ragged year coverage is fine — the interpolator handles per-country knots. |
| `country_population.csv` | UN World Population Prospects | Keep the `WLD` control row; the rest-of-world residual is derived from it. |
| `admin1_covariates.csv` | Census / national statistical office tables | Add rows for any country; the covariate model is fitted, not hard-coded. |
| `admin1_religion_observed.csv` | ARDA *US Religion Census* (county-level), Pew *Religious Landscape Study* (state-level) | This doubles as the validation hold-out. More observed units = a better-tested model. |
| `cities.csv` | GeoNames / Natural Earth populated places | Only coordinates and metro population are used. |
| `geo/` | generated — do not edit | Written by `web/scripts/build-geo.mjs` from the bundled Natural Earth and US Census TopoJSON. |

## The two-instrument problem

`national_religion.csv` and `admin1_religion_observed.csv` are different
surveys and disagree at the national level — by about 6 percentage points on
the Christian share for the US. This is a property of the real products too,
not an artifact of the approximation.

The pipeline does not average the disagreement away. It benchmarks: the
subnational instrument sets the level, the national instrument supplies the
trend (`soulfinder/benchmark.py`). Ignoring this costs real accuracy —
cross-validated skill goes from **+18.8%** to **−15.9%**, i.e. the model
becomes worse than assuming every state looks like the national average.
