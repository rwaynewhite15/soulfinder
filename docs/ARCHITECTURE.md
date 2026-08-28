# Architecture

## The shape of the problem

Three requirements, and they pull in different directions:

1. **A sliding time-series chart** of religious composition, scaling from world
   to country to state.
2. **An interactive globe** with a heat map of how populations have changed,
   zoomable to local statistics.
3. **Synthetic data** for the local resolution nobody publishes.

The third is what makes this a data project rather than a charting exercise. The
first two are a UI problem with well-trodden answers; the third decides whether
the app is worth building at all, because a beautiful globe rendering
made-up numbers is worse than no globe.

So the architecture is organised around one question: *where did this number
come from, and how do we keep the app honest about it?*

---

## Stack, and why

| Layer | Choice | Why this and not the obvious alternative |
|---|---|---|
| Globe + map | **deck.gl** (`_GlobeView` ↔ `MapView`) | The only mature library that does a 3D globe *and* a zoomable 2D map with the same layer code and the same data. `react-globe.gl` / three-globe look better out of the box and are a dead end the moment you need to zoom to state level. Switching views is a one-line swap; nothing else changes. |
| Charts | **D3 scales + shapes, rendered into React-controlled SVG** | The scrubbable playhead, the draggable range brush, and the crosshair all need direct control of the mark geometry. Recharts and friends fight you on exactly this. D3 for the math, React for the DOM — no `d3.select` anywhere. |
| State | **Zustand** | One store holds `year`, `window`, `selection`, `religion`. Globe and chart both subscribe. This is the whole linked-views mechanism, in ~60 lines. Redux is ceremony at this size; context re-renders the world on every slider tick. |
| Data delivery | **Precomputed static JSON** | No server, no query layer. Every year is precomputed, so scrubbing the slider is an array index rather than a fetch. |
| Pipeline | **Python + numpy/scipy/pandas** | The synthesis is compositional regression, IPF, spatial smoothing. That is numpy's home turf. |

### Why the data layer is a separate program

The pipeline is not "a script that makes the JSON". It is where every claim the
app makes gets decided, so it is a testable Python package with 64 tests, and
the web app is a pure function of its output. This means a modelling change is
reviewable as a diff in one place, and the app cannot quietly disagree with the
pipeline about what a number means.

```
sources/*.csv ──┐
                ├─→ pipeline (interpolate → benchmark → synthesise → validate)
geo/*.geojson ──┘                          │
                                           ↓
                            web/public/data/*.json   (regions, density, meta)
                                           │
                                           ↓
                                     React + deck.gl
```

### Why the data is precomputed rather than served

41 years × 105 regions × 8 religions is 34,440 numbers — about 400KB of JSON.
That is smaller than the deck.gl bundle. A query API would add a network round
trip to every slider tick to save nothing.

The dasymetric point cloud is the interesting case. It is **time-invariant by
design**: each anchor carries "this fraction of the unit's people live here",
and the app multiplies that by the unit's population and composition for the
selected year. One 500KB file serves all 41 years, and scrubbing is a multiply
rather than a fetch. Had the points carried per-year values, this would have
been 41 files.

---

## Scaling world → country → state

One `RegionSeries` type covers all three levels, distinguished only by `level`
and `parent`. The chart does not know or care which level it is drawing.

The map switches its geometry and its colour domain when the selection enters a
country with subnational data, and the globe flattens to a map at zoom 2.5,
where curvature stops helping and starts distorting.

There are two stage views and two lower-pane views, and they compose freely:

| | Globe | All faiths (atlas) |
|---|---|---|
| **Over time** | one religion, drillable to state, with the scrubbable stacked chart | eight globes on one shared camera + the chart |
| **Trends** | one religion + the per-religion trend rail | eight globes + the trend rail |

The eight atlas facets share a single camera, so dragging any one of them turns
all eight. That is the interaction that makes the comparison land — you rotate
to Africa and watch the Christian and Muslim globes trade places along the
Sahel.

**The hierarchy reconciles exactly** — states sum to their country, countries
sum to the world, to within JSON rounding. This is asserted in
`test_build_consistency.py`, not assumed. It is easy to break: benchmarking one
level and not another does it silently, which is precisely the bug that shipped
in the first draft of this pipeline.

---

## Keeping the visuals honest

Three decisions do most of the work here:

**Fixed colour domains.** Computed once over all years and regions, never per
frame. A domain recomputed each year would rescale the ramp as the slider
moves, so a region holding perfectly steady would still change colour. Fixing
the domain means every colour change on the map is a change in the data.

**No categorical choropleth — and the measurement that settled it.** The
obvious way to show "different religions" on one map is to colour each country
by its largest. That puts all eight categorical hues in a view where *any* pair
can end up adjacent, so the palette has to clear separation floors on all 28
pairs rather than the 7 adjacent ones a chart needs.

It doesn't. Running the validator over every subset of the eight-hue order, in
both themes:

| Hues shown at once | Subsets clearing all-pairs floors, both themes |
|---|---|
| 8, 7, 6, 5 | **0** |
| 4 | 2 (`blue, yellow, magenta, green` · `yellow, magenta, green, violet`) |

Four is the ceiling, and neither passing set contains the hues already bound to
Muslim (orange) or Unaffiliated (aqua). So a categorical map would have to
*recolour religions* relative to the chart — a worse problem than the one it
solves.

The remedy is faceting, and it turns out to be the better product anyway: **the
atlas view** gives each religion its own globe on its own **sequential** ramp,
so no two categorical hues are ever adjacent on a map and all eight are
visible. Identity survives because each facet's ramp is generated from that
religion's own chart hue — the blue globe is the same Christian blue as the
blue band in the chart. On the main globe the same idea applies: selecting
Hindu turns the choropleth, the heat layer and the legend all gold.

Generating those ramps needed real colour maths (`src/lib/oklch.ts`). Fading a
hue toward white in sRGB does not produce monotone lightness, and naively
clamping out-of-gamut RGB channels rotates the hue — measured drift was up to
**30°** across a single ramp, turning a one-hue sequential scale into a small
rainbow. Interpolating lightness in OKLab at fixed hue, and gamut-mapping by
reducing *chroma* rather than clipping channels, brings all 16 ramps (8
religions × 2 themes) to monotone lightness with hue held inside 2.6°.

**Trends get their own view.** A stacked chart answers "what is this region
made of"; it is genuinely bad at "what is changing". Band *thickness* is easy
to read, band *slope* is not, and small categories are invisible — a religion
going from 0.5% to 2% quadruples and stays a hairline. The trend rail puts
every religion on its own baseline with a sparkline, sorted by how far it
actually moved, with the magnitudes printed rather than left to the eye.

**Change has two meanings, so the app offers both.** A group can grow by tens
of millions of people while losing share to a faster-growing one. Utah's
Christian share falls 3.1 points between 2010 and 2025 while gaining 214,000
adherents. Picking one and calling it "change" would be a choice about what
story to tell; showing both is not.

---

## One layout trap worth knowing about

The chart measures its container and renders an `<svg>` at that pixel width.
That makes the SVG's intrinsic width part of its container's **max-content**
size — so any grid track sized `auto` or `1fr` (whose floor is `auto`) can never
shrink below the widest chart it has ever held. The layout ratchets wider,
never comes back, and the globe drifts off screen.

Every track that holds measured content is therefore `minmax(0, 1fr)`, with
`min-width: 0` on the panes and `overflow-x: hidden` to clip the one frame
before the observer re-measures. The atlas has the same hazard in reverse — a
fixed globe zoom spills across cell boundaries once cells shrink — so its grid
*and* its zoom are both derived from the measured pane rather than from
breakpoints.

The rule this leaves behind: **anything whose size is derived from a
measurement must live in a track that cannot be widened by it.**

---

## What I would add next

- **Real source data.** The seed tables are hand-compiled approximations. The
  loaders take the real Pew / ARDA / UN files unchanged — see
  `pipeline/sources/README.md`.
- **County-level drill-down.** ARDA's US Religion Census is genuinely
  county-level, so the deepest layer could be observed rather than synthetic.
  The pipeline already handles ragged observation coverage.
- **More observed subnational data.** India, Brazil and Indonesia all publish
  it. Every country added is both better coverage *and* a bigger validation
  set — the cross-validation currently rests on 51 US states.
- **PMTiles** for the geometry if the admin layers grow past a few MB.
- **Uncertainty on the map**, not just in the panel. Texture or opacity
  encoding for synthetic units, so the map itself distinguishes measurement
  from model.
