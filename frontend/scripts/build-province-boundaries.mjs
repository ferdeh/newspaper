import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const SOURCE_PAGE = "https://geoservices.big.go.id/gis/rest/services/STIG/Batas_Provinsi/MapServer/0";
const OUTPUT_URL = new URL("../public/data/indonesia-provinces.geojson", import.meta.url);
const TOLERANCE = 0.005;

function squaredSegmentDistance(point, start, end) {
  let x = start[0];
  let y = start[1];
  let dx = end[0] - x;
  let dy = end[1] - y;
  if (dx !== 0 || dy !== 0) {
    const position = ((point[0] - x) * dx + (point[1] - y) * dy) / (dx * dx + dy * dy);
    if (position > 1) {
      x = end[0];
      y = end[1];
    } else if (position > 0) {
      x += dx * position;
      y += dy * position;
    }
  }
  dx = point[0] - x;
  dy = point[1] - y;
  return dx * dx + dy * dy;
}

function simplifyStep(points, first, last, squaredTolerance, selected) {
  let maxDistance = squaredTolerance;
  let index = 0;
  for (let cursor = first + 1; cursor < last; cursor += 1) {
    const distance = squaredSegmentDistance(points[cursor], points[first], points[last]);
    if (distance > maxDistance) {
      index = cursor;
      maxDistance = distance;
    }
  }
  if (maxDistance > squaredTolerance) {
    if (index - first > 1) simplifyStep(points, first, index, squaredTolerance, selected);
    selected.push(points[index]);
    if (last - index > 1) simplifyStep(points, index, last, squaredTolerance, selected);
  }
}

function simplifyRing(ring) {
  if (!Array.isArray(ring) || ring.length <= 4) return ring;
  const points = ring.map(([lng, lat]) => [Number(lng.toFixed(4)), Number(lat.toFixed(4))]);
  const selected = [points[0]];
  simplifyStep(points, 0, points.length - 1, TOLERANCE * TOLERANCE, selected);
  selected.push(points[points.length - 1]);
  return selected.length >= 4 ? selected : points;
}

function simplifyGeometry(geometry) {
  if (geometry.type === "Polygon") {
    return { ...geometry, coordinates: geometry.coordinates.map(simplifyRing) };
  }
  if (geometry.type === "MultiPolygon") {
    return { ...geometry, coordinates: geometry.coordinates.map((polygon) => polygon.map(simplifyRing)) };
  }
  throw new Error(`Unsupported geometry type: ${geometry.type}`);
}

const sourceUrl = new URL(`${SOURCE_PAGE}/query`);
sourceUrl.searchParams.set("where", "1=1");
sourceUrl.searchParams.set("outFields", "KDPPUM,WADMPR");
sourceUrl.searchParams.set("returnGeometry", "true");
sourceUrl.searchParams.set("returnZ", "false");
sourceUrl.searchParams.set("returnM", "false");
sourceUrl.searchParams.set("outSR", "4326");
sourceUrl.searchParams.set("geometryPrecision", "4");
sourceUrl.searchParams.set("maxAllowableOffset", "0.01");
sourceUrl.searchParams.set("f", "geojson");

const response = await fetch(sourceUrl, { headers: { Accept: "application/geo+json, application/json" } });
if (!response.ok) throw new Error(`Boundary source returned HTTP ${response.status}`);
const payload = await response.json();
if (payload.type !== "FeatureCollection" || !Array.isArray(payload.features)) throw new Error("Invalid GeoJSON response");

const features = payload.features.flatMap((feature) => {
  const name = typeof feature.properties?.WADMPR === "string" ? feature.properties.WADMPR.trim() : "";
  if (!name || !feature.geometry) return [];
  const code = typeof feature.properties?.KDPPUM === "string" ? feature.properties.KDPPUM.trim() : "";
  return [{ type: "Feature", properties: { code, name }, geometry: simplifyGeometry(feature.geometry) }];
});

if (features.length !== 38) throw new Error(`Expected 38 provinces, received ${features.length}`);

const output = {
  type: "FeatureCollection",
  attribution: "Badan Informasi Geospasial · Batas Administrasi Provinsi",
  source: SOURCE_PAGE,
  generated_at: new Date().toISOString(),
  features,
};

await mkdir(fileURLToPath(new URL("../public/data/", import.meta.url)), { recursive: true });
await writeFile(fileURLToPath(OUTPUT_URL), `${JSON.stringify(output)}\n`);
console.log(`Wrote ${features.length} provinces to ${fileURLToPath(OUTPUT_URL)}`);
