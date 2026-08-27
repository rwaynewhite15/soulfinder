# Methodology

How subnational religious composition is synthesised, what it costs, and where
it should not be trusted.

> Every number produced here is about what people believe. Presenting a modelled
> estimate as if it were a census count is the main way an app like this does
> harm, so provenance is a first-class field on every cell, not a footnote.

---

## 1. Compositional data, not eight independent numbers

Religious shares are a **composition**: strictly positive parts carrying only
relative information, constrained to sum to one. The usual operations are
invalid on the simplex.

- Interpolating two compositions componentwise leaves the simplex.
- Ordinary regression on raw shares predicts negative percentages, and clipping
  them back silently destroys the constant-sum constraint.
- Euclidean distance between share vectors calls 0.01 → 0.02 and 0.50 → 0.51
  the same size of change. The first doubles a group; the second grows it by a
  fiftieth.

Everything is therefore done in **log-ratio coordinates**, where the simplex
becomes a real vector space, and mapped back at the end
(`compositional.py`). Validity is then structural rather than enforced by
clipping.

Zeros need care: many countries report 0.0% for some categories, and `log(0)`
is undefined. **Multiplicative zero replacement** substitutes a small value and
rescales the non-zero parts, which preserves the ratios among the observed
parts. Adding a constant to every part — the obvious fix — distorts exactly
those ratios, which are the only thing a compositional analysis may depend on.

Error is reported in two metrics:

- **Aitchison distance** — CLR-space Euclidean distance; measures relative
  change and is subcompositionally coherent.
- **Total variation distance** — half the L1 distance, interpretable directly
  as *the share of people assigned to the wrong group*.

---

## 2. Decadal knots → per-year frames

Source data is decadal (2010, 2020, … 2050). The year slider needs all 41.

Interpolation happens in ALR space using **PCHIP** (shape-preserving cubic
Hermite). A natural cubic spline through 2010/2030/2050 bulges past both
endpoints between knots, inventing local maxima — a religion that declines
monotonically in the source would appear to spike and fall back. Once rendered,
that bulge is indistinguishable from a real trend reversal. PCHIP never
introduces an extremum that is not in the data.

Population is interpolated in **log space**, so the implied growth rate is
constant between knots rather than drifting.

Outside the knot range the series is **clamped, not extrapolated**. Projecting
religion 30 years past the source would be fabrication wearing a spline.

---

## 3. Splicing two instruments that disagree

The national projection and the state-level survey are different products with
different questionnaires, vintages and sampling frames. For the US in 2014 they
disagree by **6.4 percentage points** on the Christian share. This is a
property of the real products, not an artifact of the seed data.

Raking state estimates to the *unreconciled* national marginal forces that
entire 6.4-point gap onto the states. It is not a small effect:

| | out-of-sample TVD | baseline TVD | skill |
|---|---|---|---|
| Raked to the raw national marginal | 0.1056 | 0.0911 | **−15.9% — worse than doing nothing** |
| Benchmarked first | 0.0616 | 0.0760 | **+18.8%** |

(The baseline moves too, because "the national average" is itself one of the two
disagreeing numbers.)

So the pipeline **benchmarks**: the subnational instrument sets the *level*, the
national instrument supplies the *trend*.

```
used(y) = observed(anchor) ⊕ [ national(y) ⊖ national(anchor) ]
```

in log-ratio space, which reproduces the observed composition exactly in the
anchor year and applies the national series' relative year-on-year changes on
top of it. Levels come from the survey that measured states; change over time
comes from the projection built to model change over time. Neither series is
asked to do the other's job.

The benchmarked series becomes the country's **canonical** series — not a
private input to the downscaler. Otherwise the app would show one Christian
share for the US and a different one for the sum of its states.

---

## 4. The four-stage synthesis

For each country-year (`downscale.py`):

**Stage 1 — Compositional regression.** Learn how composition covaries with
observable characteristics (urbanisation, median age, education, foreign-born
share) on units where truth exists, then apply those coefficients where it does
not. OLS per ALR coordinate; the inverse transform re-imposes positivity and
sum-to-one for free. Leading-coordinate R² ≈ 0.80.

**Stage 2 — Spatial smoothing.** A lightweight stand-in for an ICAR prior:
religion is spatially autocorrelated and administrative borders are not walls,
so each unit borrows strength from its neighbours' compositional centre.
Neighbours are k-nearest by centroid; contiguity weights would strand Hawaii
and Alaska entirely. Observed units are held fixed so real data is never
blurred by its modelled neighbours.

**Stage 3 — Shrinkage.** Empirical-Bayes pull toward the national composition
with weight `λᵢ = nᵢ / (nᵢ + κ)`, κ = median unit population. A province of
500,000 people cannot swing to an extreme on the strength of a regression
residual.

**Stage 4 — IPF (raking).** Rescale rows and columns alternately until row sums
match known unit populations and column sums match known national religion
totals — both exactly (converged marginal error ~9.2e-10). Among all matrices
satisfying both marginals, this is the one minimising KL divergence from the
seed.

**Stage 4 is what makes stages 1–3 safe to ship.** The model gets to decide how
a religion is distributed *within* a country. It never gets to change how large
that religion is nationally. A bad covariate model produces a badly-shaped map;
it cannot produce a map that contradicts the source data it was built from.

---

## 5. The heat map: dasymetric allocation

A choropleth of admin polygons asserts something false — that Nevada's
composition is spread evenly across Nevada, including the 80% of it nobody
lives in.

Production pipelines weight by a gridded population raster (WorldPop, GHS-POP,
Meta HRSL). This pipeline builds an equivalent surface from **real metropolitan
coordinates**: a Gaussian mixture centred on actual cities, scaled by metro
population, plus a diffuse rural floor, all masked to the unit's true polygon by
a ray-casting point-in-polygon test. Anchors are then drawn *proportional to*
density rather than by keeping the densest candidates, so the result is a sample
of the population distribution rather than a picture of its peaks.

The city coordinates are real. **The surface between them is synthetic** and is
flagged as such everywhere it surfaces.

---

## 6. Validation

The US is the only country here with observed admin-1 composition, so it is the
test bed. 5-fold cross-validation hides a fold's states, fits on the rest, runs
the full four-stage synthesis, and scores the hidden states. Held-out states
enter exactly as an unmeasured country's provinces would: covariates only.

The baseline is the free alternative — *assume every state matches the national
average*. The model has to beat it by enough to justify its assumptions.

| Metric | Model | Baseline |
|---|---|---|
| Total variation distance | **0.0616** | 0.0760 |
| Aitchison distance | **1.249** | 1.483 |
| Skill (error removed) | **+18.8%** | — |

Per-religion mean absolute error, out of sample:

| Religion | MAE |
|---|---|
| christian | 5.17 pp |
| unaffiliated | 4.18 pp |
| other | 0.92 pp |
| jewish | 0.78 pp |
| muslim | 0.50 pp |
| buddhist | 0.38 pp |
| hindu | 0.34 pp |
| folk | 0.07 pp |

Worst-predicted states:

| State | Model TVD | Baseline TVD |
|---|---|---|
| New Hampshire | 17.7% | 18.6% |
| Vermont | 16.6% | 18.1% |
| Utah | 13.2% | 16.1% |
| Mississippi | 12.5% | 17.1% |
| Alaska | 11.3% | 10.7% |

The failure mode is legible and expected: the worst-predicted states are the
**extremes**. Shrinkage deliberately pulls outliers toward the middle, which
helps on average and hurts precisely where a state is genuinely unusual. Utah
and Mississippi are still predicted far better than baseline; Alaska is the one
state where the model does worse than assuming the national average, which is
what a small, remote, demographically atypical population looks like to a
covariate model.

**A 5-point average error on the Christian share is not a small error.** It is
the honest cost of estimating something nobody measured, and it is why synthetic
cells are labelled and carry intervals.

Two further checks run on every build and fail it if violated:

- **Hierarchy reconciliation** — states sum to their country, countries sum to
  the world, to within serialisation rounding.
- **World rollup vs published figures** — the derived 2010 world composition
  sits 1.40 pp from published world figures at its worst category.

---

## 7. Provenance

Every cell carries one of four flags, and the UI is required to distinguish
them:

| Flag | Meaning |
|---|---|
| `observed` | Reported directly by the source survey for this unit and year. |
| `interpolated` | Between two reported years, along the source trend. |
| `modeled` | Reported for this unit in one year, carried across years by the national trend. |
| `synthetic` | No subnational survey. Estimated from covariates, then raked to the national total. |

Modelled and synthetic cells additionally carry a 5–95% credible interval,
sampled in ALR space and inverted per draw — propagating a symmetric interval
through the nonlinear transform instead would produce intervals covering
negative shares. Observed units carry no interval and the UI renders "—" rather
than a degenerate range, which would manufacture a precision claim nobody made.

---

## Known limitations

- **Seed data is hand-compiled approximation.** Prototype quality. Not citable.
- **Cross-validation rests on 51 US states.** The covariate model is fitted on
  American religious geography and transferred globally, which is a strong
  assumption that the current data cannot test. Skill outside the US is
  unmeasured.
- **Eight categories flatten enormous internal diversity.** "Christian" spans
  Catholic, Orthodox, Pentecostal and LDS; "folk religions" is a residual
  category doing a great deal of work.
- **The rural density floor is a constant**, not an estimated urban/rural
  differential per religion, which is a real and measurable effect.
- **Only the US has an admin-1 layer.** Every other country stops at national.
