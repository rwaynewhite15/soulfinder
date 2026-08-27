import { useCallback, useEffect, useMemo, useState } from "react";
import DeckGL from "@deck.gl/react";
import { _GlobeView as GlobeView } from "@deck.gl/core";
import { GeoJsonLayer } from "@deck.gl/layers";
import { useStore } from "../state/store";
import { categorical, hexToRgb } from "../lib/palette";
import { rampAt, sequentialRamp } from "../lib/oklch";
import { shareOf, yearIndex } from "../lib/data";
import type { AppData } from "../lib/data";
import { pct } from "../lib/format";

/** 4x2 on a wide screen, 2x4 when narrow -- eight columns of globe would be
 *  unreadable slivers on a laptop half-screen. */
function useGrid(): { cols: number; rows: number } {
  const [narrow, setNarrow] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(max-width: 1080px)").matches
  );
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1080px)");
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return narrow ? { cols: 2, rows: 4 } : { cols: 4, rows: 2 };
}

interface ViewState {
  longitude: number; latitude: number; zoom: number; pitch: number; bearing: number;
}
const INITIAL: ViewState = { longitude: 20, latitude: 12, zoom: 0.18, pitch: 0, bearing: 0 };

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
  const { cols: COLS, rows: ROWS } = useGrid();
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
      <div className="atlas-stage">
      <DeckGL
        views={views as never}
        // one shared camera for all eight facets: deck falls back to a
        // view-less viewState for every view, which is exactly the coupling
        // that makes spinning one globe spin them all
        viewState={viewState as never}
        onViewStateChange={({ viewState: vs }) => setViewState(vs as ViewState)}
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
