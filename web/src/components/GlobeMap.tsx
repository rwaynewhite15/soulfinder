import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import DeckGL from "@deck.gl/react";
import { _GlobeView as GlobeView, MapView, type PickingInfo } from "@deck.gl/core";
import { GeoJsonLayer, ScatterplotLayer } from "@deck.gl/layers";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import { useStore } from "../state/store";
import { categorical, divergingAt, hexToRgb } from "../lib/palette";
import { rampAt, sequentialRamp } from "../lib/oklch";
import { change, peopleOf, shareOf, yearIndex } from "../lib/data";
import { colorDomain } from "../lib/domain";
import { pct, people, pp, signedPeople } from "../lib/format";
import { formatYear } from "../lib/frames";
import type { AppData, } from "../lib/data";
import type { RegionSeries } from "../lib/types";

/**
 * Above this zoom the globe stops helping: the curvature distorts the region
 * you are trying to read and half the viewport is sky. Country-level views and
 * below are flat maps.
 */
const FLATTEN_ZOOM = 2.5;

interface ViewState {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch: number;
  bearing: number;
}

const INITIAL: ViewState = { longitude: 10, latitude: 20, zoom: 1.15, pitch: 0, bearing: 0 };

/** Whole-sphere polygon; the vertices at 0 degrees keep the ring valid when triangulated. */
const BACKDROP: GeoJSON.FeatureCollection = {
  type: "FeatureCollection",
  features: [{
    type: "Feature",
    properties: {},
    geometry: {
      type: "Polygon",
      coordinates: [[
        [-180, 90], [0, 90], [180, 90], [180, -90], [0, -90], [-180, -90], [-180, 90],
      ]],
    },
  }],
};

interface Props { data: AppData; }

export default function GlobeMap({ data }: Props) {
  const {
    year, baseYear, religion, mapMetric, changeBasis, showDensity, dark,
    selected, select, hover,
  } = useStore();
  const [viewState, setViewState] = useState<ViewState>(INITIAL);

  // Fly to a region when it is selected from the picker or the breadcrumb, but
  // not when the selection came from clicking the map -- yanking the camera out
  // from under a click the user just made is disorienting.
  const lastSelected = useRef(selected);
  useEffect(() => {
    if (selected === lastSelected.current) return;
    lastSelected.current = selected;
    const c = data.centroids.get(selected);
    if (!c || !Number.isFinite(c.lon) || !Number.isFinite(c.lat)) {
      if (selected === "WLD") setViewState((v) => ({ ...v, ...INITIAL }));
      return;
    }
    const isState = selected.startsWith("USA-");
    setViewState((v) => ({
      ...v,
      longitude: c.lon,
      latitude: c.lat,
      zoom: Math.max(v.zoom, isState ? 4.6 : 2.6),
    }));
  }, [selected, data.centroids]);

  const years = data.bundle.years;
  const yi = yearIndex(years, year);
  const bi = yearIndex(years, baseYear);
  const flat = viewState.zoom >= FLATTEN_ZOOM;

  // Drill into US states once the selection is American *and* the camera is
  // close enough that state outlines are legible.
  const inUsa = selected === "USA" || selected.startsWith("USA-");
  const showStates = inUsa && viewState.zoom >= 2.2;

  const domain = useMemo(
    () => colorDomain(
      showStates ? data.admin1 : data.countries,
      religion, years.length, changeBasis, bi
    ),
    [data, showStates, religion, years.length, changeBasis, bi]
  );

  /**
   * One ramp per religion, built from that religion's own categorical hue.
   *
   * Selecting Hindu turns the whole map gold; selecting Muslim turns it orange.
   * Identity comes from the hue, magnitude from lightness within it, and the
   * choropleth, the heat layer, the legend, the chip and the chart band all
   * agree on what colour a religion is -- without ever putting two categorical
   * hues next to each other on a map, which is the thing that cannot be made
   * colour-safe.
   */
  const ramp = useMemo(
    () => sequentialRamp(categorical(dark)[religion], 13, dark),
    [religion, dark]
  );
  const heatRange = useMemo(
    () => sequentialRamp(categorical(dark)[religion], 6, dark)
      .map((h) => hexToRgb(h) as [number, number, number]),
    [religion, dark]
  );

  const seriesForFeature = useCallback(
    (props: Record<string, unknown>): RegionSeries | undefined =>
      showStates
        ? data.admin1ByGeoId.get(String(props.geo_id))
        : data.byId.get(String(props.iso3)),
    [data, showStates]
  );

  const fillFor = useCallback(
    (s: RegionSeries | undefined): [number, number, number, number] => {
      if (!s) return dark ? [42, 42, 40, 140] : [225, 224, 219, 160];
      if (mapMetric === "share") {
        const t = shareOf(s, yi, religion) / domain.maxShare;
        return [...hexToRgb(rampAt(ramp, t)), 232];
      }
      const d = change(s, bi, yi, religion, changeBasis);
      return [...hexToRgb(divergingAt(d / domain.maxDelta, dark)), 232];
    },
    [mapMetric, yi, bi, religion, changeBasis, domain, dark, ramp]
  );

  const layers = useMemo(() => {
    const ls: unknown[] = [];

    // Ocean/backdrop: one polygon covering the whole sphere, drawn under the
    // land. A polygon rather than a raster texture keeps the app free of any
    // external tile request -- it renders identically offline.
    ls.push(
      new GeoJsonLayer({
        id: "backdrop",
        data: BACKDROP,
        stroked: false,
        filled: true,
        getFillColor: dark ? [14, 20, 30] : [222, 233, 244],
        updateTriggers: { getFillColor: [dark] },
      })
    );

    ls.push(
      new GeoJsonLayer({
        id: showStates ? "states" : "countries",
        data: (showStates ? data.stateGeo : data.countryGeo) as never,
        pickable: true,
        stroked: true,
        filled: true,
        getFillColor: (f: { properties: Record<string, unknown> }) =>
          fillFor(seriesForFeature(f.properties)),
        getLineColor: dark ? [12, 12, 11, 190] : [255, 255, 255, 210],
        getLineWidth: 1,
        lineWidthUnits: "pixels",
        updateTriggers: {
          getFillColor: [yi, bi, religion, mapMetric, changeBasis, dark, showStates, ramp],
        },
        onClick: (info: PickingInfo) => {
          const p = (info.object as { properties?: Record<string, unknown> })?.properties;
          if (!p) return;
          const s = seriesForFeature(p);
          if (s) select(s.id);
        },
        onHover: (info: PickingInfo) => {
          const p = (info.object as { properties?: Record<string, unknown> })?.properties;
          hover(p ? seriesForFeature(p)?.id ?? null : null);
        },
      })
    );

    if (showDensity) {
      const pts = showStates ? data.densityUsa : data.densityWorld;
      const lookup = showStates
        ? (u: string) => data.admin1ByGeoId.get(u)
        : (u: string) => data.byId.get(u);

      if (mapMetric === "share") {
        ls.push(
          new HeatmapLayer({
            id: "density-heat",
            data: pts as never,
            getPosition: (d: { lon: number; lat: number }) => [d.lon, d.lat],
            // Weight = adherents actually living at this anchor: the unit's
            // share of that religion, times its population, times the share of
            // the unit's people the anchor stands for.
            getWeight: (d: { u: string; w: number }) => {
              const s = lookup(d.u);
              return s ? d.w * peopleOf(s, yi, religion) : 0;
            },
            radiusPixels: showStates ? 34 : 26,
            intensity: 1.1,
            threshold: 0.04,
            // The heat ramp wears the selected religion's own hue rather than a
            // fixed blue, so switching religions reads as switching subject and
            // the heat layer agrees with the chip, the chart and the atlas.
            colorRange: heatRange,
            updateTriggers: {
              getWeight: [yi, religion, showStates],
              colorRange: [religion, dark],
            },
          })
        );
      } else {
        // Heatmaps cannot render signed values; growth and decline need to be
        // told apart, so change is drawn as diverging-coloured marks sized by
        // magnitude instead.
        ls.push(
          new ScatterplotLayer({
            id: "density-change",
            data: pts as never,
            pickable: false,
            getPosition: (d: { lon: number; lat: number }) => [d.lon, d.lat],
            getFillColor: (d: { u: string }) => {
              const s = lookup(d.u);
              if (!s) return [0, 0, 0, 0];
              const t = change(s, bi, yi, religion, changeBasis) / domain.maxDelta;
              return [...hexToRgb(divergingAt(t, dark)), 150];
            },
            getRadius: (d: { u: string; w: number }) => {
              const s = lookup(d.u);
              if (!s) return 0;
              const mag = Math.abs(change(s, bi, yi, religion, changeBasis)) / domain.maxDelta;
              return Math.sqrt(Math.max(0, mag) * d.w * 4e5) * (showStates ? 420 : 1400);
            },
            radiusUnits: "meters",
            radiusMinPixels: 1,
            // Kept small deliberately: these marks sit on top of the
            // choropleth, and at larger radii they merge into a wash that
            // hides the per-unit values underneath.
            radiusMaxPixels: showStates ? 11 : 8,
            stroked: false,
            updateTriggers: {
              getFillColor: [yi, bi, religion, changeBasis, dark, showStates],
              getRadius: [yi, bi, religion, changeBasis, showStates],
            },
          })
        );
      }
    }

    return ls;
  }, [
    data, showStates, showDensity, mapMetric, changeBasis, religion, yi, bi,
    dark, domain, fillFor, seriesForFeature, select, hover, heatRange,
  ]);

  const getTooltip = useCallback(
    (info: PickingInfo) => {
      const p = (info.object as { properties?: Record<string, unknown> })?.properties;
      if (!p) return null;
      const s = seriesForFeature(p);
      const label = data.bundle.labels[data.bundle.religions[religion]];
      if (!s) {
        return {
          html: `<div class="map-tip"><b>${String(p.name ?? "Unknown")}</b>
                 <div class="tip-muted">No data in this build</div></div>`,
        };
      }
      const share = shareOf(s, yi, religion);
      const d = change(s, bi, yi, religion, changeBasis);
      const delta = changeBasis === "share" ? pp(d) : signedPeople(d);
      return {
        html: `<div class="map-tip">
                 <b>${s.name}</b>
                 <div class="tip-row"><span>${label}</span><span>${pct(share)}</span></div>
                 <div class="tip-row"><span>vs ${formatYear(baseYear)}</span><span>${delta}</span></div>
                 <div class="tip-row"><span>Population ${formatYear(year)}</span><span>${people(s.population[yi] ?? 0)}</span></div>
                 <div class="tip-prov tip-${s.provenance[yi]}">${s.provenance[yi]}</div>
               </div>`,
      };
    },
    [data, seriesForFeature, religion, yi, bi, changeBasis, baseYear, year]
  );

  return (
    <DeckGL
      views={flat ? new MapView({ id: "map", repeat: true }) : new GlobeView({ id: "globe" })}
      viewState={viewState}
      onViewStateChange={({ viewState: vs }) => setViewState(vs as ViewState)}
      controller={{ dragRotate: false, touchRotate: false }}
      layers={layers as never}
      getTooltip={getTooltip as never}
      style={{ position: "absolute", inset: "0" }}
    />
  );
}
