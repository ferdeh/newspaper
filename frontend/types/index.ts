export type KPI = {
  active_incidents: number;
  critical_incidents: number;
  news_24h: number;
  tiktok_24h: number;
  supply_incidents: number;
  reported_mt_accidents: number;
  provinces_affected: number;
  tbbm_exposed: number;
};

export type OverviewData = {
  generated_at: string;
  scheduler_update: {
    last_update_at?: string;
    next_update_at?: string;
    interval_minutes: number;
  };
  kpis: KPI;
  trend: { date: string; incidents: number; signals: number }[];
  trending_issues: { name: string; count: number }[];
  regions: { name: string; count: number }[];
  products: { name: string; count: number }[];
  events: { name: string; count: number }[];
  province_heatmap: ProvinceHeatmapDatum[];
  unresolved_province_incidents: number;
  map: {
    id: number; code: string; location: string; province?: string; lat: number; lng: number; category: string; event: string;
    products: string[]; incident_date: string; news_date?: string; risk: number; severity: string; news: number; tiktok: number;
    nearest_terminal?: string; nearest_terminal_id?: string; nearest_terminal_lat?: number; nearest_terminal_lng?: number;
    nearest_terminal_distance_km?: number; nearest_terminal_distance_source?: string; nearest_terminal_duration_minutes?: number;
    serving_terminal?: string; geocoding_provider?: string; geocoding_confidence?: number;
  }[];
  terminals: TerminalMapPoint[];
};

export type ProvinceHeatmapDatum = {
  province: string;
  incident_count: number;
  max_risk: number;
  average_risk: number;
  critical_count: number;
  supply_incidents: number;
  hsse_incidents: number;
  external_incidents: number;
  news_count: number;
  tiktok_count: number;
  mapped_incidents: number;
  label_lat?: number;
  label_lng?: number;
  period_start: string;
  period_end: string;
};

export type TerminalMapPoint = {
  id: string; code: string; name: string; type: string; province: string; city?: string; lat: number; lng: number;
};

export type Incident = {
  id: number; incident_code: string; date: string; last_signal_at: string; location: string; province?: string; regency?: string;
  category: string; event: string; products: string[]; severity: string; source_severity: string; risk: number;
  supply_risk: number; hsse_risk: number; confidence: number; news_count: number; tiktok_count: number; signal_count: number;
  trend: string; status: string; first_detection_source?: string; tiktok_lead_time_minutes?: number;
  nearest_terminal?: string; nearest_terminal_id?: string; nearest_terminal_code?: string;
  nearest_terminal_latitude?: number; nearest_terminal_longitude?: number; nearest_terminal_distance_km?: number;
  nearest_terminal_distance_source?: string; nearest_terminal_duration_minutes?: number;
  serving_terminal?: string; serving_terminal_id?: string; serving_terminal_code?: string;
  serving_terminal_latitude?: number; serving_terminal_longitude?: number; spbu?: string;
  latitude?: number; longitude?: number; geocoded_address?: string; geocoding_provider?: string;
  geocoding_confidence?: number; location_resolution_status: string;
  event_types?: string[]; signals?: SignalRecord[]; risk_history?: RiskPoint[];
  notifications?: NotificationStatus[];
};

export type NotificationStatus = { id:string; channel:string; provider?:string; sender?:string; status:string; attempts:number; max_attempts:number; sent_at?:string; error_code?:string; reconnect_required:boolean };

export type SignalRecord = { id: number; source_type: string; title: string; content: string; url: string; published_at: string; relevance: number; event_types: string[]; confidence?: number; is_primary: boolean; processing_status?: string; false_positive_reason?: string };
export type RiskPoint = { supply_risk: number; hsse_risk: number; severity: string; calculated_at: string };
