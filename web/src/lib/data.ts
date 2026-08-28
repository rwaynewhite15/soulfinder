import type { DensityPoint, Meta, RegionBundle, RegionSeries } from "./types";
import { frameIndex } from "./frames";

const base = import.meta.env.BASE_URL ?? "/";

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${base}data/${path}`);
  if (!res.ok) {
    throw new Error(
      `could not load ${path} (${res.status}). Run \`npm run data\` to build the data artifacts.`
    );
  }
  return res.json() as Promise<T>;
}

export interface AppData {
  bundle: RegionBundle;
  meta: Meta;
  byId: Map<string, RegionSeries>;
  countries: RegionSeries[];
  /** macro-regions carrying the historical layer */
  macroRegions: RegionSeries[];
  admin1: RegionSeries[];
  /** admin-1 units keyed by their geometry id, for joining to the GeoJSON */
  admin1ByGeoId: Map<string, RegionSeries>;
  /** region id -> map anchor, for the fly-to on selection */
  centroids: Map<string, { lon: number; lat: number }>;
  countryGeo: GeoJSON.FeatureCollection;
  stateGeo: GeoJSON.FeatureCollection;
  densityWorld: DensityPoint[];
  densityUsa: DensityPoint[];
}

export async function loadAll(): Promise<AppData> {
  const [bundle, meta, countryGeo, stateGeo, densityWorld, densityUsa] = await Promise.all([
    getJSON<RegionBundle>("regions.json"),
    getJSON<Meta>("meta.json"),
    getJSON<GeoJSON.FeatureCollection>("geo/countries.geojson"),
    getJSON<GeoJSON.FeatureCollection>("geo/us-states.geojson"),
    getJSON<DensityPoint[]>("density-world.json"),
    getJSON<DensityPoint[]>("density-usa.json"),
  ]);

  const byId = new Map(bundle.series.map((s) => [s.id, s]));
  const countries = bundle.series.filter((s) => s.level === "country");
  const macroRegions = bundle.series.filter((s) => s.level === "region");
  const admin1 = bundle.series.filter((s) => s.level === "admin1");
  const admin1ByGeoId = new Map(
    admin1.filter((s) => s.geo_id).map((s) => [s.geo_id as string, s])
  );

  // build-geo.mjs stamps an area-weighted centroid onto every feature, so the
  // fly-to lands on the landmass rather than the middle of a bounding box.
  const centroids = new Map<string, { lon: number; lat: number }>();
  for (const f of countryGeo.features) {
    const p = f.properties ?? {};
    if (p.iso3) centroids.set(String(p.iso3), { lon: Number(p.lon), lat: Number(p.lat) });
  }
  for (const f of stateGeo.features) {
    const p = f.properties ?? {};
    const s = admin1ByGeoId.get(String(p.geo_id));
    if (s) centroids.set(s.id, { lon: Number(p.lon), lat: Number(p.lat) });
  }

  return {
    bundle, meta, byId, countries, macroRegions, admin1, admin1ByGeoId, centroids,
    countryGeo, stateGeo, densityWorld, densityUsa,
  };
}

/**
 * Index of a year within the per-frame arrays.
 *
 * The old arithmetic fallback (`year - years[0]`) was correct only while the
 * grid was one frame per year. It now spans year 0 to 2050 at varying
 * resolution, so this delegates to a binary search over the real grid.
 */
export function yearIndex(years: number[], year: number): number {
  return frameIndex(years, year);
}

export function shareOf(s: RegionSeries, yi: number, ri: number): number {
  return s.shares[yi]?.[ri] ?? 0;
}

export function peopleOf(s: RegionSeries, yi: number, ri: number): number {
  return (s.shares[yi]?.[ri] ?? 0) * (s.population[yi] ?? 0);
}

/**
 * Change in a religion between two years.
 *
 * "share" is the change in percentage points; "people" is the change in
 * absolute adherents. They can point in opposite directions -- a group can grow
 * by millions while losing share to a faster-growing one -- which is exactly
 * why the app offers both rather than picking one and calling it "change".
 */
export function change(
  s: RegionSeries, fromIdx: number, toIdx: number, ri: number, mode: "share" | "people"
): number {
  if (mode === "share") return shareOf(s, toIdx, ri) - shareOf(s, fromIdx, ri);
  return peopleOf(s, toIdx, ri) - peopleOf(s, fromIdx, ri);
}
