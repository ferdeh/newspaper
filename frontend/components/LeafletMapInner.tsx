"use client";

import { useEffect, useMemo, useState } from "react";
import { CircleMarker, GeoJSON as GeoJSONLayer, MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import { divIcon } from "leaflet";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { LatLngExpression, LatLngTuple, Layer } from "leaflet";
import { formatDate, humanize } from "@/lib/api";
import type { ProvinceHeatmapDatum } from "@/types";
import type { LeafletMapProps } from "./LeafletMap";

type IncidentMapPoint = LeafletMapProps["incidents"][number];

const INDONESIA_CENTER: LatLngExpression = [-2.5, 118];
const OSM_TILE_URL = process.env.NEXT_PUBLIC_OSM_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const PROVINCE_BOUNDARY_SOURCE = "https://geoservices.big.go.id/gis/rest/services/STIG/Batas_Provinsi/MapServer/0";

type ProvinceBoundaryProperties = { code: string; name: string };
type ProvinceBoundaryCollection = FeatureCollection<Geometry, ProvinceBoundaryProperties> & {
  attribution?: string;
  source?: string;
};

function normalizeProvince(value: string): string {
  const normalized = value.trim().toLocaleLowerCase("id-ID").replace(/^provinsi\s+/, "").replace(/\s+/g, " ");
  const aliases: Record<string, string> = {
    jakarta: "dki jakarta",
    "di yogyakarta": "daerah istimewa yogyakarta",
    "d.i. yogyakarta": "daerah istimewa yogyakarta",
    yogyakarta: "daerah istimewa yogyakarta",
    "nanggroe aceh darussalam": "aceh",
  };
  return aliases[normalized] || normalized;
}

function provinceRiskColor(score: number): string {
  if (score >= 80) return "#dc2626";
  if (score >= 65) return "#f97316";
  if (score >= 45) return "#eab308";
  if (score >= 25) return "#3b82f6";
  return "#77b82a";
}

function provinceRiskBand(score: number): string {
  if (score >= 80) return "CRITICAL";
  if (score >= 65) return "HIGH";
  if (score >= 45) return "WARNING";
  if (score >= 25) return "WATCH";
  return "NORMAL";
}

function tooltipLine(container: HTMLElement, label: string, value: string) {
  const line = document.createElement("div");
  line.textContent = `${label}: ${value}`;
  container.appendChild(line);
}

function provinceTooltip(name: string, stats?: ProvinceHeatmapDatum): HTMLElement {
  const content = document.createElement("div");
  content.className = "min-w-52 text-xs leading-5";
  const heading = document.createElement("strong");
  heading.textContent = name;
  content.appendChild(heading);
  if (!stats) {
    tooltipLine(content, "Highest Active Risk", "N/A");
    tooltipLine(content, "Insiden aktif", "Tidak ada data terverifikasi");
    return content;
  }
  tooltipLine(content, "Highest Active Risk", `${stats.max_risk.toLocaleString("id-ID", { maximumFractionDigits: 1 })} · ${provinceRiskBand(stats.max_risk)}`);
  tooltipLine(content, "Average Risk", stats.average_risk.toLocaleString("id-ID", { maximumFractionDigits: 1 }));
  tooltipLine(content, "Insiden aktif", stats.incident_count.toLocaleString("id-ID"));
  tooltipLine(content, "Critical", stats.critical_count.toLocaleString("id-ID"));
  tooltipLine(content, "Supply / HSSE / External", `${stats.supply_incidents} / ${stats.hsse_incidents} / ${stats.external_incidents}`);
  tooltipLine(content, "News / TikTok", `${stats.news_count} / ${stats.tiktok_count}`);
  tooltipLine(content, "Koordinat tersedia", `${stats.mapped_incidents}/${stats.incident_count}`);
  tooltipLine(content, "Periode", `${formatDate(stats.period_start)} – ${formatDate(stats.period_end)}`);
  return content;
}

function incidentColor(category: string): string {
  if (category === "HSSE") return "#ea4a43";
  if (category === "EXTERNAL_DISRUPTION") return "#2563eb";
  return "#f2b84b";
}

function FitViewport({ points }: { points: LatLngTuple[] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 1) map.setView(points[0], 9);
    if (points.length > 1) map.fitBounds(points, { padding: [28, 28], maxZoom: 9 });
  }, [map, points]);
  return null;
}

function FocusIncident({ point }: { point?: LatLngTuple }) {
  const map = useMap();
  useEffect(() => {
    if (point) map.flyTo(point, Math.max(map.getZoom(), 8), { duration: 0.65 });
  }, [map, point]);
  return null;
}

function IncidentPopupContent({ incident, showTerminal = true }: { incident: IncidentMapPoint; showTerminal?: boolean }) {
  return <div className="min-w-56 text-xs leading-5">
    <a href={`/incidents/${incident.id}`} className="font-bold text-[#0b73bf]">{incident.code}</a><br />
    <strong>{incident.location}</strong><br />
    {humanize(incident.event)} · Risk {Math.round(incident.risk)} ({incident.severity})<br />
    <span className="text-slate-500">Tanggal berita pertama {incident.news_date ? formatDate(incident.news_date) : "—"}</span><br />
    <span className="text-slate-500">News {incident.news} · TikTok {incident.tiktok}</span>
    {showTerminal && incident.nearest_terminal && <div className="mt-2 border-t border-slate-200 pt-2">
      TBBM terdekat: <strong>{incident.nearest_terminal}</strong><br />
      {incident.nearest_terminal_distance_km != null && <span>{incident.nearest_terminal_distance_km} km · Durasi: Tidak dihitung</span>}<br />
      <span className="text-slate-500">{humanize(incident.nearest_terminal_distance_source || "")}</span>
    </div>}
  </div>;
}

export default function LeafletMapInner({
  incidents,
  terminals,
  heightClass = "h-[420px]",
  showConnections = true,
  selectedIncidentId,
  provinceHeatmap = [],
  showProvinceHeatmapToggle = false,
}: LeafletMapProps) {
  const [heatmapEnabled, setHeatmapEnabled] = useState(showProvinceHeatmapToggle);
  const [provinceBoundaries, setProvinceBoundaries] = useState<ProvinceBoundaryCollection | null>(null);
  const [boundaryLoading, setBoundaryLoading] = useState(false);
  const [boundaryError, setBoundaryError] = useState("");
  const provinceStats = useMemo(
    () => new Map(provinceHeatmap.map((item) => [normalizeProvince(item.province), item])),
    [provinceHeatmap],
  );
  const heatmapKey = useMemo(
    () => provinceHeatmap.map((item) => `${item.province}:${item.max_risk}:${item.incident_count}`).join("|"),
    [provinceHeatmap],
  );

  useEffect(() => {
    if (!showProvinceHeatmapToggle || !heatmapEnabled || provinceBoundaries || boundaryError) return;
    let active = true;
    setBoundaryLoading(true);
    fetch("/data/indonesia-provinces.geojson")
      .then(async (response) => {
        if (!response.ok) {
          const payload = await response.json().catch(() => null) as { detail?: string } | null;
          throw new Error(payload?.detail || `HTTP ${response.status}`);
        }
        return response.json() as Promise<ProvinceBoundaryCollection>;
      })
      .then((payload) => {
        if (!active) return;
        if (payload.type !== "FeatureCollection" || !Array.isArray(payload.features)) throw new Error("Format batas provinsi tidak valid");
        setProvinceBoundaries(payload);
      })
      .catch((reason) => {
        if (active) setBoundaryError(reason instanceof Error ? reason.message : "Batas provinsi tidak dapat dimuat");
      })
      .finally(() => {
        if (active) setBoundaryLoading(false);
      });
    return () => { active = false; };
  }, [boundaryError, heatmapEnabled, provinceBoundaries, showProvinceHeatmapToggle]);

  const points = useMemo<LatLngTuple[]>(
    () => [
      ...incidents.map((item) => [item.lat, item.lng] as LatLngTuple),
      ...terminals.map((item) => [item.lat, item.lng] as LatLngTuple),
    ],
    [incidents, terminals],
  );
  const selectedPoint = useMemo<LatLngTuple | undefined>(() => {
    const incident = incidents.find((item) => item.id === selectedIncidentId);
    return incident ? [incident.lat, incident.lng] : undefined;
  }, [incidents, selectedIncidentId]);
  const incidentGroups = useMemo(() => {
    const groups = new Map<string, IncidentMapPoint[]>();
    for (const incident of incidents) {
      const key = `${incident.lat.toFixed(6)},${incident.lng.toFixed(6)}`;
      groups.set(key, [...(groups.get(key) ?? []), incident]);
    }
    return [...groups.entries()].map(([key, items]) => ({ key, items, position: [items[0].lat, items[0].lng] as LatLngTuple }));
  }, [incidents]);

  const toggleHeatmap = () => {
    if (!heatmapEnabled && boundaryError) setBoundaryError("");
    setHeatmapEnabled((current) => !current);
  };

  const styleProvince = (feature?: Feature<Geometry, ProvinceBoundaryProperties>) => {
    const name = feature?.properties?.name || "";
    const stats = provinceStats.get(normalizeProvince(name));
    return {
      color: "#ffffff",
      weight: 1.2,
      opacity: 0.9,
      fillColor: stats ? provinceRiskColor(stats.max_risk) : "#94a3b8",
      fillOpacity: stats ? 0.52 : 0.18,
    };
  };

  const bindProvinceTooltip = (feature: Feature<Geometry, ProvinceBoundaryProperties>, layer: Layer) => {
    const name = feature.properties?.name || "Provinsi tidak dikenal";
    layer.bindTooltip(provinceTooltip(name, provinceStats.get(normalizeProvince(name))), {
      sticky: true,
      direction: "auto",
      className: "province-risk-tooltip",
    });
  };

  return <div className={`relative overflow-hidden rounded-xl border border-slate-200 bg-[#eef4f7] ${heightClass}`}>
    <MapContainer center={INDONESIA_CENTER} zoom={5} minZoom={4} scrollWheelZoom={false} preferCanvas className="h-full w-full">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url={OSM_TILE_URL}
      />
      {heatmapEnabled && provinceBoundaries && <GeoJSONLayer
        key={`province-heatmap-${heatmapKey}`}
        data={provinceBoundaries}
        style={styleProvince}
        onEachFeature={bindProvinceTooltip}
      />}
      <FitViewport points={points} />
      <FocusIncident point={selectedPoint} />
      {showConnections && incidents.map((incident) => incident.nearest_terminal_lat != null && incident.nearest_terminal_lng != null
        ? <Polyline
            key={`connection-${incident.id}`}
            positions={[[incident.lat, incident.lng], [incident.nearest_terminal_lat, incident.nearest_terminal_lng]]}
            pathOptions={{ color: "#64748b", weight: 1.5, dashArray: "5 6", opacity: 0.65 }}
          />
        : null)}
      {terminals.map((terminal) => <CircleMarker
        key={`terminal-${terminal.id}`}
        center={[terminal.lat, terminal.lng]}
        radius={4}
        pathOptions={{ color: "#15385b", weight: 2, fillColor: "#0b73bf", fillOpacity: 0.95 }}
      >
        <Popup>
          <div className="min-w-48 text-xs leading-5">
            <strong>{terminal.name}</strong><br />
            {terminal.code} · {humanize(terminal.type)}<br />
            <span className="text-slate-500">{[terminal.city, terminal.province].filter(Boolean).join(", ")}</span>
          </div>
        </Popup>
      </CircleMarker>)}
      {incidentGroups.map((group) => {
        if (group.items.length === 1) {
          const incident = group.items[0];
          const selected = incident.id === selectedIncidentId;
          return <CircleMarker
            key={`incident-${incident.id}`}
            center={group.position}
            radius={selected ? 13 : 8}
            pathOptions={{
              color: selected ? "#15385b" : "#ffffff",
              weight: selected ? 5 : 2.5,
              fillColor: incidentColor(incident.category),
              fillOpacity: 1,
            }}
          >
            <Popup><IncidentPopupContent incident={incident} /></Popup>
          </CircleMarker>;
        }

        const selected = group.items.some((incident) => incident.id === selectedIncidentId);
        const markerSize = selected ? 42 : 36;
        const categories = new Set(group.items.map((incident) => incident.category));
        const color = categories.size === 1 ? incidentColor(group.items[0].category) : "#15385b";
        const textColor = color === "#2563eb" || color === "#15385b" ? "#ffffff" : "#15385b";
        const icon = divIcon({
          className: "co-located-incident-marker",
          html: `<span style="display:grid;place-items:center;width:${markerSize}px;height:${markerSize}px;border-radius:9999px;background:${color};color:${textColor};border:${selected ? 5 : 3}px solid ${selected ? "#15385b" : "#ffffff"};box-shadow:0 3px 10px rgba(15,23,42,.35);font:800 12px system-ui,sans-serif">${group.items.length}</span>`,
          iconSize: [markerSize, markerSize],
          iconAnchor: [markerSize / 2, markerSize / 2],
        });
        return <Marker key={`incident-group-${group.key}`} position={group.position} icon={icon}>
          <Popup maxWidth={340}>
            <div className="min-w-64 text-xs leading-5">
              <strong>{group.items.length} insiden pada koordinat yang sama</strong><br />
              <span className="text-slate-500">{group.items[0].location}</span>
              <div className="mt-2 max-h-64 divide-y divide-slate-200 overflow-y-auto">
                {group.items.map((incident) => <div key={incident.id} className="py-2"><IncidentPopupContent incident={incident} showTerminal={false} /></div>)}
              </div>
            </div>
          </Popup>
        </Marker>;
      })}
      {heatmapEnabled && provinceHeatmap.map((stats) => stats.label_lat != null && stats.label_lng != null
        ? <Marker
            key={`province-count-${stats.province}`}
            position={[stats.label_lat, stats.label_lng]}
            interactive={false}
            zIndexOffset={-1000}
            icon={divIcon({
              className: "province-incident-badge",
              html: `<span>${Math.max(0, Math.trunc(stats.incident_count))}</span>`,
              iconSize: [28, 28],
              iconAnchor: [14, 14],
            })}
          />
        : null)}
    </MapContainer>
    {showProvinceHeatmapToggle && <div className="absolute right-3 top-3 z-[650] flex max-w-64 flex-col items-end gap-2">
      <button
        type="button"
        aria-pressed={heatmapEnabled}
        onClick={toggleHeatmap}
        className={`rounded-lg border px-3 py-2 text-[10px] font-black shadow-md backdrop-blur ${heatmapEnabled ? "border-ink bg-ink text-white" : "border-slate-200 bg-white/95 text-ink"}`}
      >
        Heatmap Provinsi · {heatmapEnabled ? "AKTIF" : "NONAKTIF"}
      </button>
      {boundaryLoading && <span className="rounded-lg bg-white/95 px-2.5 py-1.5 text-[9px] font-bold text-slate-500 shadow">Memuat batas 38 provinsi…</span>}
      {heatmapEnabled && boundaryError && <span role="alert" className="rounded-lg border border-red-200 bg-red-50 px-2.5 py-1.5 text-[9px] font-bold text-red-700 shadow">Heatmap gagal dimuat. Nonaktifkan lalu aktifkan untuk mencoba lagi.</span>}
    </div>}
    {heatmapEnabled && provinceBoundaries && <div className="absolute bottom-3 right-3 z-[500] rounded-lg bg-white/95 p-3 text-[9px] font-bold text-slate-600 shadow">
      <div className="mb-2 text-[9px] font-black uppercase tracking-wider text-ink">Highest Active Risk</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1">
        {[
          ["#77b82a", "0–24 Normal"],
          ["#3b82f6", "25–44 Watch"],
          ["#eab308", "45–64 Warning"],
          ["#f97316", "65–79 High"],
          ["#dc2626", "80–100 Critical"],
          ["#94a3b8", "N/A"],
        ].map(([color, label]) => <span key={label} className="flex items-center gap-1.5"><i className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />{label}</span>)}
      </div>
      <div className="mt-2 border-t border-slate-200 pt-2 text-[8px] font-normal text-slate-400">
        Angka = insiden aktif · <a className="font-bold underline" href={provinceBoundaries.source || PROVINCE_BOUNDARY_SOURCE} target="_blank" rel="noreferrer">Batas provinsi 2022</a>
      </div>
    </div>}
    <div className="pointer-events-none absolute bottom-3 left-3 z-[500] flex flex-wrap gap-3 rounded-lg bg-white/95 px-3 py-2 text-[9px] font-bold text-slate-600 shadow">
      <span className="flex items-center gap-1" title="Berita atau sinyal publik yang diklasifikasikan sebagai gangguan pasokan"><i className="h-2 w-2 rounded-full border border-slate-800 bg-amber-400" />Supply disruption</span>
      <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-coral" />Reported MT accident</span>
      <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-blue-600" />External disruption</span>
      <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-full border border-slate-800 bg-petrol" />TBBM</span>
      {showConnections && <span className="text-slate-400">Dashed line = relationship, not road geometry</span>}
    </div>
  </div>;
}
