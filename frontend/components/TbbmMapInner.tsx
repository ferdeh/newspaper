"use client";

import { useEffect, useMemo } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
import type { LatLngExpression, LatLngTuple } from "leaflet";
import { humanize } from "@/lib/api";
import type { TbbmMapProps } from "./TbbmMap";

const INDONESIA_CENTER: LatLngExpression = [-2.5, 118];
const OSM_TILE_URL = process.env.NEXT_PUBLIC_OSM_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

function FitViewport({ points, selected }: { points: LatLngTuple[]; selected?: LatLngTuple }) {
  const map = useMap();
  useEffect(() => {
    if (selected) map.setView(selected, 11);
    else if (points.length === 1) map.setView(points[0], 9);
    else if (points.length > 1) map.fitBounds(points, { padding: [24, 24], maxZoom: 8 });
  }, [map, points, selected]);
  return null;
}

export default function TbbmMapInner({ terminals, heightClass = "h-[390px]", selectedId, onSelect }: TbbmMapProps) {
  const points = useMemo<LatLngTuple[]>(() => terminals.map((item) => [item.latitude, item.longitude]), [terminals]);
  const selected = terminals.find((item) => item.id === selectedId);
  const selectedPoint = selected ? [selected.latitude, selected.longitude] as LatLngTuple : undefined;
  return <div className={`relative overflow-hidden rounded-xl border border-slate-200 bg-[#eef4f7] ${heightClass}`}>
    <MapContainer center={INDONESIA_CENTER} zoom={5} minZoom={4} scrollWheelZoom={false} preferCanvas className="h-full w-full">
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url={OSM_TILE_URL} />
      <FitViewport points={points} selected={selectedPoint} />
      {terminals.map((terminal) => <CircleMarker
        key={terminal.id}
        center={[terminal.latitude, terminal.longitude]}
        radius={terminal.id === selectedId ? 10 : 7}
        pathOptions={{
          color: terminal.id === selectedId ? "#ea4a43" : "#15385b",
          weight: 2, fillColor: terminal.verification_status === "VERIFIED" ? "#77b82a" : "#94a3b8", fillOpacity: 0.95,
        }}
        eventHandlers={{ click: () => onSelect?.(terminal) }}
      >
        <Popup><div className="min-w-52 text-xs leading-5">
          <strong>{terminal.name}</strong><br />
          {terminal.tbbm_code} · {humanize(terminal.terminal_type)}<br />
          <span className="text-slate-500">{terminal.province_name || "Provinsi belum ditetapkan"}</span><br />
          <span className="text-slate-500">{terminal.address || "Alamat belum tersedia"}</span><br />
          <span className="mt-1 inline-block font-bold text-[#0b73bf]">{humanize(terminal.verification_status)}</span>
        </div></Popup>
      </CircleMarker>)}
    </MapContainer>
    <div className="pointer-events-none absolute bottom-3 left-3 z-[500] rounded-lg bg-white/95 px-3 py-2 text-[9px] font-bold text-slate-600 shadow">
      Hijau = TBBM terverifikasi · Abu-abu = perlu review
    </div>
  </div>;
}
