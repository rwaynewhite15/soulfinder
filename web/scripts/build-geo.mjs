/**
 * Converts the bundled Natural Earth / US Census TopoJSON into the two things
 * the rest of the project needs:
 *
 *   web/public/data/geo/*.json      GeoJSON for the map layers
 *   pipeline/sources/geo/*.csv      centroids + areas for the Python pipeline
 *
 * The centroids matter: the pipeline builds its spatial-weights graph from
 * them, so the smoother's notion of "neighbouring state" comes from real
 * geometry rather than from anything hand-entered.
 */
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { feature } from "topojson-client";

const here = dirname(fileURLToPath(import.meta.url));
const webData = resolve(here, "../public/data/geo");
const pipelineGeo = resolve(here, "../../pipeline/sources/geo");
mkdirSync(webData, { recursive: true });
mkdirSync(pipelineGeo, { recursive: true });

const read = (p) => JSON.parse(readFileSync(resolve(here, "../node_modules", p), "utf8"));

/** Ring area via the shoelace formula, in squared degrees. */
function ringArea(ring) {
  let a = 0;
  for (let i = 0, n = ring.length, j = n - 1; i < n; j = i++) {
    a += ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
  }
  return a / 2;
}

/**
 * Area-weighted centroid of a (Multi)Polygon.
 *
 * Averaging raw vertices instead would drag every centroid toward whichever
 * coastline happens to be drawn in the most detail, which for a country like
 * Norway is badly wrong.
 */
function centroid(geometry) {
  const polys = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  let cx = 0, cy = 0, total = 0;
  for (const poly of polys) {
    const ring = poly[0];
    if (!ring || ring.length < 3) continue;
    const a = ringArea(ring);
    let x = 0, y = 0;
    for (let i = 0, n = ring.length, j = n - 1; i < n; j = i++) {
      const f = ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
      x += (ring[j][0] + ring[i][0]) * f;
      y += (ring[j][1] + ring[i][1]) * f;
    }
    if (a !== 0) {
      cx += x / (6 * a) * Math.abs(a);
      cy += y / (6 * a) * Math.abs(a);
      total += Math.abs(a);
    }
  }
  return total > 0 ? [cx / total, cy / total] : [0, 0];
}

function bbox(geometry) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const walk = (c) => {
    if (typeof c[0] === "number") {
      minX = Math.min(minX, c[0]); maxX = Math.max(maxX, c[0]);
      minY = Math.min(minY, c[1]); maxY = Math.max(maxY, c[1]);
    } else c.forEach(walk);
  };
  walk(geometry.coordinates);
  return [minX, minY, maxX, maxY];
}

function area(geometry) {
  const polys = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  return polys.reduce((s, p) => s + (p[0] ? Math.abs(ringArea(p[0])) : 0), 0);
}

// --- countries -------------------------------------------------------------
// world-atlas keys features by numeric M49 code; the pipeline speaks ISO-3166
// alpha-3, so the join goes through this table. Only the countries carried in
// the seed data need an entry.
const M49_TO_ISO3 = {
  4: "AFG", 12: "DZA", 32: "ARG", 36: "AUS", 50: "BGD", 76: "BRA", 124: "CAN",
  152: "CHL", 156: "CHN", 170: "COL", 178: "COG", 180: "COD", 218: "ECU",
  818: "EGY", 231: "ETH", 250: "FRA", 276: "DEU", 288: "GHA", 356: "IND",
  360: "IDN", 364: "IRN", 368: "IRQ", 376: "ISR", 380: "ITA", 392: "JPN",
  404: "KEN", 410: "KOR", 458: "MYS", 484: "MEX", 504: "MAR", 104: "MMR",
  524: "NPL", 528: "NLD", 566: "NGA", 586: "PAK", 604: "PER", 608: "PHL",
  616: "POL", 643: "RUS", 682: "SAU", 710: "ZAF", 724: "ESP", 144: "LKA",
  729: "SDN", 752: "SWE", 764: "THA", 792: "TUR", 800: "UGA", 804: "UKR",
  826: "GBR", 840: "USA", 860: "UZB", 862: "VEN", 704: "VNM", 834: "TZA",
  24: "AGO",
};

const worldTopo = read("world-atlas/countries-110m.json");
const countries = feature(worldTopo, worldTopo.objects.countries);
for (const f of countries.features) {
  const iso3 = M49_TO_ISO3[Number(f.id)] ?? null;
  const [lon, lat] = centroid(f.geometry);
  f.properties = { ...f.properties, iso3, m49: Number(f.id), lon, lat };
}
writeFileSync(resolve(webData, "countries.geojson"), JSON.stringify(countries));

// --- US states -------------------------------------------------------------
const usTopo = read("us-atlas/states-10m.json");
const states = feature(usTopo, usTopo.objects.states);
for (const f of states.features) {
  const [lon, lat] = centroid(f.geometry);
  f.properties = { ...f.properties, geo_id: String(f.id).padStart(2, "0"), lon, lat };
}
writeFileSync(resolve(webData, "us-states.geojson"), JSON.stringify(states));

// --- centroid tables for the Python pipeline -------------------------------
const csv = (rows) => rows.map((r) => r.join(",")).join("\n") + "\n";

writeFileSync(
  resolve(pipelineGeo, "country_centroids.csv"),
  csv([
    ["iso3", "m49", "name", "lat", "lon", "area_sqdeg", "min_lon", "min_lat", "max_lon", "max_lat"],
    ...countries.features
      .filter((f) => f.properties.iso3)
      .map((f) => {
        const b = bbox(f.geometry);
        return [f.properties.iso3, f.properties.m49, JSON.stringify(f.properties.name ?? ""),
          f.properties.lat.toFixed(4), f.properties.lon.toFixed(4), area(f.geometry).toFixed(4),
          ...b.map((v) => v.toFixed(4))];
      }),
  ])
);

writeFileSync(
  resolve(pipelineGeo, "us_state_centroids.csv"),
  csv([
    ["geo_id", "name", "lat", "lon", "area_sqdeg", "min_lon", "min_lat", "max_lon", "max_lat"],
    ...states.features.map((f) => {
      const b = bbox(f.geometry);
      return [f.properties.geo_id, JSON.stringify(f.properties.name ?? ""),
        f.properties.lat.toFixed(4), f.properties.lon.toFixed(4), area(f.geometry).toFixed(4),
        ...b.map((v) => v.toFixed(4))];
    }),
  ])
);

const matched = countries.features.filter((f) => f.properties.iso3).length;
console.log(`geo: ${countries.features.length} countries (${matched} ISO-matched), ${states.features.length} US states`);
