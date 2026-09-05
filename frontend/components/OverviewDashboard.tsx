"use client";

import { AlertCircle, ArrowUpRight, Factory, Newspaper, Radar, RefreshCw, ShieldAlert, Smartphone, TriangleAlert, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { apiFetch, humanize } from "@/lib/api";
import type { OverviewData } from "@/types";
import GlobalFilters, { FilterValues } from "./GlobalFilters";
import LeafletMap from "./LeafletMap";

const KPI_META = [
  ["active_incidents", "Active Incidents", Radar], ["critical_incidents", "Critical Incidents", TriangleAlert],
  ["news_24h", "News 24H", Newspaper], ["tiktok_24h", "TikTok Signals 24H", Smartphone],
  ["supply_incidents", "Supply Incidents", AlertCircle], ["reported_mt_accidents", "Reported MT Accidents", ShieldAlert],
  ["provinces_affected", "Provinces Affected", ArrowUpRight], ["tbbm_exposed", "TBBM Exposed", Factory],
] as const;

type RefreshJob = {
  job_id: string;
  status: string;
  done: boolean;
  successful?: boolean;
  detail?: string;
  result?: {
    collection?: {
      sources_checked: number;
      candidates_seen: number;
      new_signals: number;
      duplicates: number;
      source_errors: number;
      tiktok?: {
        status: string;
        keywords_run: number;
        runs_successful: number;
        runs_partial: number;
        runs_failed: number;
        results_found: number;
        new_videos: number;
        duplicates: number;
        relevant_videos: number;
        incidents_created: number;
        credits_used: number;
      };
    };
    incidents_recalculated?: number;
    analytics_rows?: number;
  };
};

function LoadingDashboard() {
  return <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">{Array.from({ length: 8 }).map((_, index) => <div key={index} className="panel h-28 p-5"><div className="skeleton h-3 w-24"/><div className="skeleton mt-5 h-9 w-16"/></div>)}</div>;
}

function formatTrendDate(value: string, dateStyle: "weekday" | "full" = "weekday") {
  return new Intl.DateTimeFormat("id-ID", dateStyle === "weekday"
    ? { weekday: "short", timeZone: "UTC" }
    : { weekday: "long", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }
  ).format(new Date(`${value}T00:00:00Z`));
}

export default function OverviewDashboard() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [summary, setSummary] = useState("");
  const [error, setError] = useState("");
  const [appliedFilters, setAppliedFilters] = useState<FilterValues>({});
  const [refreshing, setRefreshing] = useState(false);
  const [refreshStatus, setRefreshStatus] = useState("");
  const [refreshError, setRefreshError] = useState("");
  const [selectedMapDate, setSelectedMapDate] = useState<string | null>(null);
  const [selectedMapEvent, setSelectedMapEvent] = useState<string | null>(null);

  const load = async (filters: FilterValues = {}) => {
    setError("");
    const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value));
    try {
      const [overview, executive] = await Promise.all([
        apiFetch<OverviewData>(`/analytics/overview?${query}`),
        apiFetch<{ summary: string }>(`/analytics/executive-summary?${query}`),
      ]);
      setData(overview);
      setSummary(executive.summary);
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Dashboard gagal dimuat.");
      return false;
    }
  };

  useEffect(() => { void load(); }, []);

  const applyFilters = (filters: FilterValues) => {
    setAppliedFilters(filters);
    setSelectedMapDate(null);
    setSelectedMapEvent(null);
    void load(filters);
  };

  const refreshIntelligence = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setRefreshError("");
    setRefreshStatus("Mengantrekan News Scraper dan TikTok Discovery…");
    try {
      const startResponse = await fetch("/overview-api/intelligence-refresh", {
        method: "POST",
        headers: { Accept: "application/json" },
      });
      let job = await startResponse.json().catch(() => null) as RefreshJob | null;
      if (!startResponse.ok || !job?.job_id) {
        throw new Error(job?.detail || `Pembaruan tidak dapat dimulai (${startResponse.status}).`);
      }

      setRefreshStatus("Menjalankan News Scraper dan TikTok Discovery…");
      const startedAt = Date.now();
      const deadline = startedAt + 20 * 60 * 1000;
      while (!job.done) {
        if (Date.now() >= deadline) throw new Error("Pembaruan masih berjalan lebih dari 20 menit. Proses tetap berjalan di background; periksa System Monitor.");
        await new Promise((resolve) => setTimeout(resolve, 1500));
        const statusResponse = await fetch(`/overview-api/intelligence-refresh/${job.job_id}`, {
          headers: { Accept: "application/json" },
          cache: "no-store",
        });
        job = await statusResponse.json().catch(() => null) as RefreshJob | null;
        if (!statusResponse.ok || !job) {
          throw new Error(job?.detail || `Status pembaruan tidak dapat dibaca (${statusResponse.status}).`);
        }
        const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000);
        const elapsed = elapsedSeconds < 60
          ? `${elapsedSeconds} detik`
          : `${Math.floor(elapsedSeconds / 60)} menit ${elapsedSeconds % 60} detik`;
        setRefreshStatus(`Menjalankan News Scraper dan TikTok Discovery… · ${elapsed}`);
      }

      if (!job.successful) throw new Error(job.detail || "Pembaruan intelligence gagal.");
      setRefreshStatus("Memuat ulang dashboard…");
      if (!await load(appliedFilters)) throw new Error("Data selesai diproses, tetapi dashboard gagal dimuat ulang.");

      const collection = job.result?.collection;
      const tiktok = collection?.tiktok;
      const newsWarning = collection?.source_errors ? ` · ${collection.source_errors} sumber News gagal` : "";
      const tiktokSummary = tiktok?.status === "UP_TO_DATE"
        ? " · TikTok sudah tercakup oleh run yang selesai selama refresh"
        : tiktok?.status.startsWith("SKIPPED")
        ? " · TikTok dilewati karena belum aktif atau tidak tersedia"
        : ` · ${tiktok?.new_videos ?? 0} TikTok baru (${tiktok?.keywords_run ?? 0} keyword)`;
      const tiktokWarning = tiktok && (tiktok.runs_failed || tiktok.runs_partial)
        ? ` · ${tiktok.runs_failed + tiktok.runs_partial} run TikTok bermasalah`
        : "";
      setRefreshStatus(`Selesai · ${collection?.new_signals ?? 0} berita baru${tiktokSummary}${newsWarning}${tiktokWarning} · ${new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })}`);
    } catch (reason) {
      setRefreshStatus("");
      setRefreshError(reason instanceof Error ? reason.message : "Pembaruan intelligence gagal.");
    } finally {
      setRefreshing(false);
    }
  };

  const maxTrend = useMemo(() => Math.max(1, ...(data?.trend.map((item) => item.signals) ?? [1])), [data]);
  const mapFilterActive = Boolean(selectedMapDate || selectedMapEvent);
  const mapIncidents = useMemo(() => (data?.map ?? []).filter((incident) =>
    (!selectedMapDate || incident.incident_date === selectedMapDate)
    && (!selectedMapEvent || incident.event === selectedMapEvent)
  ), [data, selectedMapDate, selectedMapEvent]);
  const mapTerminals = useMemo(() => {
    if (!data || !mapFilterActive) return data?.terminals ?? [];
    const relatedIds = new Set(mapIncidents.map((incident) => incident.nearest_terminal_id).filter(Boolean));
    return data.terminals.filter((terminal) => relatedIds.has(terminal.id));
  }, [data, mapFilterActive, mapIncidents]);
  const resetMapFilters = () => {
    setSelectedMapDate(null);
    setSelectedMapEvent(null);
  };
  return <div className="px-5 pb-10 pt-5 md:px-8 lg:px-10 lg:pt-6">
    <header className="app-page-intro flex flex-col justify-between gap-4 md:flex-row md:items-end">
      <div><div className="eyebrow">National operations picture · Live</div><h1>Fuel Distribution Intelligence</h1><p>Corroborated news intelligence and public TikTok early signals for supply continuity and reported transportation HSSE incidents.</p></div>
      <button disabled={refreshing} onClick={refreshIntelligence} className="flex w-fit items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-600 hover:border-petrol hover:text-petrol disabled:cursor-wait disabled:opacity-60"><RefreshCw size={14} className={refreshing ? "animate-spin" : ""}/> {refreshing ? "Refreshing News + TikTok…" : "Refresh intelligence"}</button>
    </header>
    {refreshStatus && <div aria-live="polite" className={`mb-5 rounded-xl border p-3 text-xs font-bold ${refreshing ? "border-blue-200 bg-blue-50 text-blue-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{refreshStatus}</div>}
    {refreshError && <div role="alert" className="mb-5 rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-bold text-red-700">{refreshError}</div>}
    {error && <div className="mb-5 flex items-center justify-between rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"><span>{error}. The dashboard will reconnect automatically after the API is ready.</span><button onClick={()=>void load(appliedFilters)} className="font-bold">Retry</button></div>}
    <GlobalFilters onApply={applyFilters} compact/>
    {!data ? <LoadingDashboard /> : <>
      <section className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {KPI_META.map(([key, label, Icon], index) => <div className="panel group p-4 md:p-5" key={key}><div className="flex items-center justify-between"><span className="text-[10px] font-bold uppercase tracking-[.1em] text-slate-500">{label}</span><Icon size={17} className={index === 1 ? "text-coral" : "text-petrol"}/></div><div className="metric-number mt-4 text-3xl md:text-4xl">{data.kpis[key].toLocaleString("id-ID")}</div><div className="mt-3 h-1 w-8 rounded-full bg-slate-200 transition-all group-hover:w-16 group-hover:bg-petrol"/></div>)}
      </section>
      <section className="mt-5 grid gap-5 xl:grid-cols-[1.4fr_.8fr]">
        <div className="panel p-5 md:p-6">
          <div className="flex items-start justify-between gap-4"><div><div className="eyebrow">Structured analytics</div><h2 className="mt-1 font-serif text-xl">7-day incident signal trend</h2><p className="mt-1 text-[10px] text-slate-400">Tinggi batang menunjukkan jumlah sinyal · label menampilkan sinyal (S) dan insiden (I)</p></div><span className="shrink-0 rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-bold text-petrol">Live API</span></div>
          <div className="mt-8 flex h-48 items-end gap-3 border-b border-l border-slate-200 px-3 pt-4 md:gap-5">
            {data.trend.map((item) => {
              const selected = selectedMapDate === item.date;
              return <button
                type="button"
                className={`group flex h-full flex-1 flex-col justify-end rounded-t-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol focus-visible:ring-offset-2 ${selectedMapDate && !selected ? "opacity-45" : ""}`}
                key={item.date}
                aria-label={`Filter peta untuk ${formatTrendDate(item.date, "full")}, ${item.signals} sinyal dari ${item.incidents} insiden`}
                aria-pressed={selected}
                onClick={() => setSelectedMapDate((current) => current === item.date ? null : item.date)}
              >
                <span
                  className={`relative mx-auto w-full max-w-12 rounded-t-md transition ${selected ? "bg-coral ring-2 ring-coral/25" : "bg-petrol group-hover:bg-coral"}`}
                  style={{ height: `${Math.max(5, item.signals / maxTrend * 100)}%` }}
                >
                  {item.signals > 0 && <span className={`absolute -top-6 left-1/2 -translate-x-1/2 whitespace-nowrap text-[8px] font-black transition md:text-[9px] ${selected ? "text-coral" : "text-slate-500"}`}>{item.signals}S · {item.incidents}I</span>}
                </span>
                <span className={`mt-2 text-center text-[9px] ${selected ? "font-black text-coral" : "text-slate-400"}`}>{formatTrendDate(item.date)}</span>
              </button>;
            })}
          </div>
        </div>
        <div className="panel overflow-hidden">
          <div className="border-b border-blue-800/20 bg-gradient-to-r from-[#0b73bf] to-[#075f9f] p-5 text-white"><div className="text-[10px] font-bold uppercase tracking-[.14em] text-lime-100">AI executive summary</div><h2 className="mt-2 font-serif text-xl">Situation brief</h2></div>
          <p className="p-5 text-sm leading-7 text-slate-600">{summary}</p>
        </div>
      </section>
      <section className="mt-5 grid gap-5 lg:grid-cols-3">
        <div className="panel p-5 lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><div className="eyebrow">OpenStreetMap · Leaflet</div><h2 className="mt-1 font-serif text-xl">Indonesia situation map</h2></div>
            <div className="flex items-center gap-3"><span className="text-[10px] font-bold text-slate-400">{mapIncidents.length} incident terpetakan</span><Link href="/situation-map" className="text-xs font-bold text-petrol">Open map →</Link></div>
          </div>
          {mapFilterActive && <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-[10px] font-bold text-emerald-900">
            <span>Filter peta aktif:</span>
            {selectedMapDate && <span className="rounded-full bg-white px-2.5 py-1">Tanggal · {formatTrendDate(selectedMapDate, "full")}</span>}
            {selectedMapEvent && <span className="rounded-full bg-white px-2.5 py-1">Kejadian · {humanize(selectedMapEvent)}</span>}
            <button type="button" onClick={resetMapFilters} className="ml-auto flex items-center gap-1 rounded-lg px-2 py-1 text-emerald-800 hover:bg-white"><X size={11}/> Hapus filter peta</button>
          </div>}
          {mapFilterActive && mapIncidents.length === 0 && <p className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">Tidak ada insiden dengan koordinat yang sesuai kombinasi filter ini.</p>}
          <div className="mt-5"><LeafletMap incidents={mapIncidents} terminals={mapTerminals} heightClass="h-64" /></div>
        </div>
        <div className="panel p-5">
          <div className="eyebrow">Signal velocity</div><h2 className="mt-1 font-serif text-xl">Trending issues</h2>
          <div className="mt-5 space-y-2">{data.trending_issues.map((item, index) => {
            const selected = selectedMapEvent === item.name;
            return <button
              type="button"
              key={item.name}
              aria-label={`Filter peta untuk kejadian ${humanize(item.name)}, ${item.count} insiden`}
              aria-pressed={selected}
              onClick={() => setSelectedMapEvent((current) => current === item.name ? null : item.name)}
              className={`block w-full rounded-xl p-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol ${selected ? "bg-emerald-50 ring-1 ring-emerald-200" : "hover:bg-slate-50"} ${selectedMapEvent && !selected ? "opacity-45" : ""}`}
            >
              <span className="flex justify-between text-xs"><span className={`font-bold ${selected ? "text-petrol" : ""}`}>{humanize(item.name)}</span><span className="text-slate-400">{item.count}</span></span>
              <span className="mt-2 block h-1.5 rounded-full bg-slate-100"><span className={`block h-full rounded-full ${selected || index === 0 ? "bg-coral" : "bg-petrol"}`} style={{width:`${Math.max(10, item.count / (data.trending_issues[0]?.count || 1) * 100)}%`}}/></span>
            </button>;
          })}</div>
        </div>
      </section>
    </>}
  </div>;
}
