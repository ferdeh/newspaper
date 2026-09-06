"use client";

import dynamic from "next/dynamic";
import type { OverviewData, ProvinceHeatmapDatum, TerminalMapPoint } from "@/types";

export type IncidentMapPoint = OverviewData["map"][number];

export type LeafletMapProps = {
  incidents: IncidentMapPoint[];
  terminals: TerminalMapPoint[];
  heightClass?: string;
  showConnections?: boolean;
  selectedIncidentId?: number | null;
  provinceHeatmap?: ProvinceHeatmapDatum[];
  showProvinceHeatmapToggle?: boolean;
  allowFullscreen?: boolean;
};

const LeafletMapInner = dynamic(() => import("./LeafletMapInner"), {
  ssr: false,
  loading: () => <div className="skeleton h-full min-h-64 w-full" />,
});

export default function LeafletMap({ incidents = [], terminals = [], provinceHeatmap = [], ...props }: LeafletMapProps) {
  return <LeafletMapInner incidents={incidents} terminals={terminals} provinceHeatmap={provinceHeatmap} {...props} />;
}
