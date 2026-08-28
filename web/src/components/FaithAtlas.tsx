import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import DeckGL from "@deck.gl/react";
import { _GlobeView as GlobeView } from "@deck.gl/core";
import { GeoJsonLayer } from "@deck.gl/layers";
import { useStore } from "../state/store";
import { categorical, hexToRgb } from "../lib/palette";
import { rampAt, sequentialRamp } from "../lib/oklch";
import { shareOf, yearIndex } from "../lib/data";
import type { AppData } from "../lib/data";
import { pct } from "../lib/format";

/**
 * Choose the facet grid and the globe zoom from the pane's actual size.
 *
 * A fixed 4x2 grid with a fixed zoom only looks right at one window size. Once
 * the pane narrows the cells shrink but the globes do not, so they spill across
 * cell boundaries into their neighbours. Both have to follow the measurement:
 * pick whichever 8-cell arrangement yields the largest globe, then size the
 * globe to the cell it actually got.
 */
function useAtlasLayout(ref: React.RefObject<HTMLDivElement>) {
  const [box, setBox] = useState({ w: 0, h: 0 });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => {
      const w = Math.round(e.contentRect.width);
      const h = Math.round(e.contentRect.height);
      setBox((prev) => (Math.abs(prev.w - w) > 1 || Math.abs(prev.h - h) > 1 ? { w, h } : prev));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);

  return useMemo(() => {
    const { w, h } = box;
    if (w < 2 || h < 2) return { cols: 4, rows: 2, zoom: -1 };

    // Each cell keeps room for its label chrome; the globe takes what is left.
    const globeFor = (cols: number, rows: number) =>
      Math.min((w / cols) * 0.92, (h / rows) * 0.74);

    // Only the two-dimensional arrangements are candidates. A single row or
    // column occasionally yields a marginally larger globe on an extreme aspect
    // ratio, but it is a worse comparison grid and leaves no width for a
    // facet's name and figures -- which are the point of the panel.
    const MIN_CELL_W = 150;
    // 4x2 is the default; 2x4 has to be clearly better to displace it, so the
    // layout does not flip back and forth while a window is being dragged.
    const SWITCH_MARGIN = 1.1;

    let best = { cols: 4, rows: 2, d: globeFor(4, 2) };
    const alt = { cols: 2, rows: 4, d: globeFor(2, 4) };
    if (w / 2 >= MIN_CELL_W && (alt.d > best.d * SWITCH_MARGIN || w / 4 < MIN_CELL_W)) {
      best = alt;
    }

    // deck.gl sizes the world at 512 * 2^zoom pixels across, and an orthographic
    // globe's visible diameter is that circumference divided by pi.
    const zoom = Math.log2((Math.max(best.d, 24) * Math.PI) / 512);
    return { cols: best.cols, rows: best.rows, zoom };
  }, [box]);
}

interface ViewState {
  longitude: number; latitude: number; zoom: number; pitch: number; bearing: number;
}
const INITIAL: ViewState = { longitude: 20, latitude: 12, zoom: -1, pitch: 0, bearing: 0 };

const BACKDROP: GeoJSON.FeatureCollection = {
  type: "FeatureCollection",
  features: [{
    type: "Feature", properties: {},
    geometry: {
      type: "Polygon",
      coordinates: [[[-180, 90], [0, 90], [180, 90], [180, -90], [0, -90], [-180, -90], [-180, 90]]],
    },
  }],
};

/**
 * Eight globes, one religion each.
 *
 * This is the faceted answer to "show different religions on the globe at
 * once". The direct approach -- one map coloured categorically by religion --
 * cannot be made colour-safe: on a map any two religions can end up adjacent,
 * and measurement on the validated eight-hue order shows at most FOUR clear the
 * all-pairs separation floors. Worse, the four that do clear them are not the
 * hues already bound to Muslim and Unaffiliated in the chart, so a categorical
 * map would have to recolour religions between the two views.
 *
 * Faceting dissolves the problem instead of trading against it. Each globe is a
 * *sequential* ramp -- one hue, light to dark -- so no two categorical hues are
 * ever adjacent on the same map, and all eight religions can be shown. Identity
 * still comes from colour, because each facet's ramp is built from that
 * religion's own chart hue: the blue globe is the same Christian blue as the
 * blue band in the chart.
 *
 * All eight share one camera. Spinning any globe spins all of them, which is
 * what makes the comparison land -- you rotate to Africa and watch the
 * Christian and Muslim globes trade places along the Sahel.
 */
export default function FaithAtlas({ data }: { data: AppData }) {
  const { year, religion, dark, setReligion, set } = useStore();
  const stageRef = useRef<HTMLDivElement>(null);
  const { cols: COLS, rows: ROWS, zoom: fitZoom } = useAtlasLayout(stageRef);
  const [viewState, setViewState] = useState<ViewState>(INITIAL);

  const years = data.bundle.years;
  const yi = yearIndex(years, year);
  const labels = data.bundle.religions.map((r) => data.bundle.labels[r]);
  const colors = categorical(dark);

  const ramps = useMemo(
    () => colors.map((c) => sequentialRamp(c, 9, dark)),
    [colors, dark]
  );

  /**
   * Each facet is normalised to its own maximum, fixed across all years.
   *
   * A shared domain would be defensible but useless here: Jewish populations
   * peak around 75% in one country and under 2% almost everywhere else, so on a
   * common scale seven of the eight globes would be uniformly blank. Per-facet
   * domains make every footprint visible at the cost of cross-facet magnitude
   * comparison -- so each facet states its own maximum in its header, and the
   * headline share is printed as text where the real comparison belongs.
   */
  const domains = useMemo(
    () => labels.map((_, ri) => {
      let m = 0;
      for (const s of data.countries) {
        for (let i = 0; i < years.length; i++) m = Math.max(m, s.shares[i]?.[ri] ?? 0);
      }
      return Math.max(m, 1e-6);
    }),
    [data.countries, labels, years.length]
  );

  const worldShares = useMemo(() => {
    const w = data.byId.get("WLD");
    return labels.map((_, ri) => (w ? shareOf(w, yi, ri) : 0));
  }, [data.byId, labels, yi]);

  const views = useMemo(
    () => labels.map((_, i) => new GlobeView({
      id: `f${i}`,
      x: `${(i % COLS) * (100 / COLS)}%`,
      y: `${Math.floor(i / COLS) * (100 / ROWS)}%`,
      width: `${100 / COLS}%`,
      height: `${100 / ROWS}%`,
      controller: true,
    })),
    [labels, COLS, ROWS]
  );

  const layers = useMemo(() => {
    const out: unknown[] = [];
    labels.forEach((_, ri) => {
      out.push(new GeoJsonLayer({
        id: `backdrop-f${ri}`,
        data: BACKDROP,
        stroked: false,
        filled: true,
        getFillColor: dark ? [16, 22, 32] : [228, 236, 245],
        updateTriggers: { getFillColor: [dark] },
      }));
      out.push(new GeoJsonLayer({
        id: `countries-f${ri}`,
        data: data.countryGeo as never,
        pickable: false,
        stroked: true,
        filled: true,
        getFillColor: (f: { properties: Record<string, unknown> }) => {
          const s = data.byId.get(String(f.properties.iso3));
          if (!s) return dark ? [40, 40, 38, 120] : [222, 221, 216, 150];
          const t = shareOf(s, yi, ri) / domains[ri];
          return [...hexToRgb(rampAt(ramps[ri], t)), 240];
        },
        getLineColor: dark ? [12, 12, 11, 150] : [255, 255, 255, 170],
        getLineWidth: 0.6,
        lineWidthUnits: "pixels",
        updateTriggers: { getFillColor: [yi, dark, domains, ramps] },
      }));
    });
    return out;
  }, [data, labels, yi, dark, domains, ramps]);

  // Every facet renders the layers whose id ends in its own view id.
  const layerFilter = useCallback(
    ({ layer, viewport }: { layer: { id: string }; viewport: { id: string } }) =>
      layer.id.endsWith(`-${viewport.id}`),
    []
  );

  return (
    <div className="atlas">
      <div className="atlas-stage" ref={stageRef}>
      <DeckGL
        views={views as never}
        // one shared camera for all eight facets: deck falls back to a
        // view-less viewState for every view, which is exactly the coupling
        // that makes spinning one globe spin them all
        viewState={{ ...viewState, zoom: fitZoom } as never}
        // Zoom is owned by the layout, not the user: the facets are a
        // comparison grid, and letting one pan out of its cell breaks it.
        onViewStateChange={({ viewState: vs }) =>
          setViewState({ ...(vs as ViewState), zoom: fitZoom })
        }
        controller={{ dragRotate: false, touchRotate: false }}
        layerFilter={layerFilter as never}
        layers={layers as never}
        style={{ position: "absolute", inset: "0" }}
      />
      <div
        className="atlas-grid"
        style={{
          gridTemplateColumns: `repeat(${COLS}, 1fr)`,
          gridTemplateRows: `repeat(${ROWS}, 1fr)`,
        }}
      >
        {labels.map((l, i) => (
          <button
            key={l}
            className={`facet ${religion === i ? "active" : ""}`}
            onClick={() => { setReligion(i); set("view", "globe"); }}
            title={`Show ${l} on the main globe`}
          >
            <span className="facet-head">
              <span className="dot" style={{ background: colors[i] }} />
              <span className="facet-name">{l}</span>
            </span>
            <span className="facet-stats">
              <span className="facet-world">{pct(worldShares[i], 1)} of world</span>
              <span className="facet-scale">
                <span className="facet-ramp">
                  {ramps[i].map((c, k) => <span key={k} style={{ background: c }} />)}
                </span>
                <span className="facet-max">max {pct(domains[i], 0)}</span>
              </span>
            </span>
          </button>
        ))}
      </div>
      </div>
      <p className="atlas-note">
        Drag any globe — all eight turn together. Click a panel to open it on the main globe.
        <span className="atlas-caveat">
          Each panel is scaled to its own maximum (shown per panel), so footprints
          compare in shape, not in depth.
        </span>
      </p>
    </div>
  );
}
