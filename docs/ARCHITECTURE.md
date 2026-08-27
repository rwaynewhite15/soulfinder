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

**No categorical choropleth.** Colouring countries by "largest religion" would
put all eight categorical hues in a single view where any pair can end up
adjacent, and eight hues cannot clear colour-vision-deficiency separation
floors under that condition. The map encodes one religion's magnitude on a
single-hue sequential ramp, or change on a diverging ramp with a neutral grey
midpoint. Categorical colour is used only in the chart, where the pairs that
can touch are the adjacent ones — which the eight-slot order does clear.

**Change has two meanings, so the app offers both.** A group can grow by tens
of millions of people while losing share to a faster-growing one. Utah's
Christian share falls 3.1 points between 2010 and 2025 while gaining 214,000
adherents. Picking one and calling it "change" would be a choice about what
story to tell; showing both is not.

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
