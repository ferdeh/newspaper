"use client";

import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Factory,
  Globe2,
  Map,
  Search,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch, formatDate, humanize } from "@/lib/api";
import GlobalFilters, { FilterValues } from "./GlobalFilters";
import PageHeader from "./PageHeader";
import LeafletMap from "./LeafletMap";
import type { OverviewData } from "@/types";
import type { IncidentMapPoint } from "./LeafletMap";

const config: Record<string, { title: string; eyebrow: string; description: string; endpoint: string; disclaimer?: string }> = {
  "situation-map": { title: "Indonesia Situation Map", eyebrow: "OpenStreetMap · Leaflet", description: "Live incident coordinates, risk, sources, and TBBM relationships resolved through master data or Google geocoding.", endpoint: "/analytics/overview" },
  "geographic-intelligence": { title: "Geographic Intelligence", eyebrow: "Indonesia → Province → Regency", description: "Regional concentration of supply and reported HSSE media incidents.", endpoint: "/analytics/geography" },
  "product-intelligence": { title: "Product Intelligence", eyebrow: "Fuel product signals", description: "Cross-source mentions, critical incidents, average risk, and direction by product.", endpoint: "/analytics/products" },
  "event-intelligence": { title: "Event Intelligence", eyebrow: "Issue comparison", description: "Current event activity compared with prior observation windows.", endpoint: "/analytics/events" },
  "tbbm-exposure": { title: "TBBM Incident Exposure", eyebrow: "Terminal media exposure", description: "Ranks terminals associated by nearest distance or serving-master mapping. Exposure never implies causation.", endpoint: "/analytics/terminals", disclaimer: "Terminal exposure is a relationship to reported incidents, not evidence that a terminal caused an incident." },
  hsse: { title: "Reported MT Accidents", eyebrow: "HSSE media intelligence", description: "Reported transportation accidents, consequences, and risk—this is not a complete actual accident population.", endpoint: "/analytics/hsse", disclaimer: "Media-reported cases are incomplete and must not be used as the denominator for actual safety performance." },
  "tiktok-early-warning": { title: "TikTok Early Warning", eyebrow: "Lead-time intelligence", description: "Measures when public TikTok signals preceded, followed, or coincided with News corroboration.", endpoint: "/analytics/tiktok" },
  alerts: { title: "Alert history", eyebrow: "WhatsApp operations", description: "Deduplicated notification history after rules, confidence thresholds, cooldown, and escalation checks.", endpoint: "/alerts" },
};

const SITUATION_HUB = {
  title: "Indonesia Situation Map",
  eyebrow: "Geospatial command center",
  description: "Pantau peta insiden, konsentrasi geografis, dan paparan media TBBM dari satu ruang kerja terpadu.",
};

const SITUATION_TABS = [
  { id: "situation-map", label: "Situation Map", icon: Map },
  { id: "geographic-intelligence", label: "Geographic Intelligence", icon: Globe2 },
  { id: "tbbm-exposure", label: "TBBM Incident Exposure", icon: Factory },
] as const;

type SituationTab = (typeof SITUATION_TABS)[number]["id"];

const SITUATION_COLUMNS = ["code", "news_date", "location", "category", "event", "products", "risk", "severity", "news", "tiktok"];
const PAGE_SIZE_OPTIONS = [10, 25, 50] as const;
type SortDirection = "asc" | "desc";

function flattenPayload(section: string, payload: unknown): Record<string, unknown>[] {
  if (Array.isArray(payload)) return payload as Record<string, unknown>[];
  const data = payload as Record<string, unknown>;
  if (section === "situation-map") return (data.map as Record<string, unknown>[]) || [];
  if (section === "hsse") return (data.incidents as Record<string, unknown>[]) || [];
  if (section === "tiktok-early-warning") return (data.by_event as Record<string, unknown>[]) || [];
  if (section === "alerts") return (data.items as Record<string, unknown>[]) || [];
  return Object.entries(data).filter(([, value]) => typeof value !== "object").map(([metric, value]) => ({ metric, value }));
}

function columnLabel(key: string): string {
  return key === "news_date" ? "Tanggal berita pertama" : humanize(key);
}

function cellValue(key: string, value: unknown): string {
  if (key === "news_date") return value ? formatDate(String(value)) : "—";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "number") return value.toLocaleString("id-ID", { maximumFractionDigits: 1 });
  return humanize(String(value ?? "—"));
}

function comparableValue(key: string, value: unknown): number | string {
  if (typeof value === "number") return value;
  if (value == null) return "";
  if (key.includes("date") || key.endsWith("_at")) {
    const timestamp = Date.parse(String(value));
    if (!Number.isNaN(timestamp)) return timestamp;
  }
  if (Array.isArray(value)) return value.join(" ").toLocaleLowerCase("id-ID");
  return String(value).toLocaleLowerCase("id-ID");
}

function formatMetricValue(key: string, value: string | number): string {
  if (typeof value === "string" && key.endsWith("_at")) {
    const timestamp = Date.parse(value);
    if (!Number.isNaN(timestamp)) return formatDate(value, true);
  }
  return typeof value === "number" ? value.toLocaleString("id-ID") : String(value);
}

function displayedDateRange(rows: Record<string, unknown>[]): string | null {
  const timestamps = rows
    .map((row) => row.incident_date ?? row.news_date)
    .filter((value): value is string => typeof value === "string" && !Number.isNaN(Date.parse(value)))
    .map((value) => Date.parse(value));
  if (!timestamps.length) return null;
  const minimum = new Date(Math.min(...timestamps)).toISOString();
  const maximum = new Date(Math.max(...timestamps)).toISOString();
  const start = formatDate(minimum);
  const end = formatDate(maximum);
  return start === end ? start : `${start} – ${end}`;
}

export default function IntelligenceSection({ section, initialTab, embedded = false }: { section: string; initialTab?: string; embedded?: boolean }) {
  const isSituationHub = section === "situation-map";
  const requestedTab = SITUATION_TABS.some((tab) => tab.id === initialTab)
    ? initialTab as SituationTab
    : "situation-map";
  const [activeSection, setActiveSection] = useState<string>(isSituationHub ? requestedTab : section);
  const page = config[activeSection] || config["event-intelligence"];
  const [payload, setPayload] = useState<unknown>(null);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [sharedOverview, setSharedOverview] = useState<OverviewData | null>(null);
  const [overviewError, setOverviewError] = useState("");
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [loadedSection, setLoadedSection] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<FilterValues>({});
  const [selectedIncidentId, setSelectedIncidentId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [pageNumber, setPageNumber] = useState(1);
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZE_OPTIONS)[number]>(10);
  const requestSequence = useRef(0);
  const overviewRequestSequence = useRef(0);
  const activeSectionRef = useRef(activeSection);
  activeSectionRef.current = activeSection;

  useEffect(() => {
    setActiveSection(isSituationHub ? requestedTab : section);
  }, [isSituationHub, requestedTab, section]);

  useEffect(() => {
    if (!isSituationHub) return;
    const syncTabFromUrl = () => {
      const tab = new URL(window.location.href).searchParams.get("tab");
      setActiveSection(SITUATION_TABS.some((item) => item.id === tab) ? tab as SituationTab : "situation-map");
    };
    window.addEventListener("popstate", syncTabFromUrl);
    return () => window.removeEventListener("popstate", syncTabFromUrl);
  }, [isSituationHub]);

  const queryFor = (next: FilterValues) => new URLSearchParams(Object.entries(next).filter(([, value]) => value));

  const applyTablePayload = (targetSection: string, data: unknown) => {
    setPayload(data);
    setRows(flattenPayload(targetSection, data));
    setLoadedSection(targetSection);
  };

  const loadTable = (targetSection: string, next: FilterValues = {}) => {
    const requestId = ++requestSequence.current;
    setLoading(true);
    setError("");
    setSelectedIncidentId(null);
    apiFetch<unknown>(`${config[targetSection].endpoint}?${queryFor(next)}`)
      .then((data) => {
        if (requestId !== requestSequence.current) return;
        applyTablePayload(targetSection, data);
      })
      .catch((reason) => {
        if (requestId === requestSequence.current) {
          setPayload(null);
          setRows([]);
          setLoadedSection(null);
          setError(reason.message);
        }
      })
      .finally(() => {
        if (requestId === requestSequence.current) setLoading(false);
      });
  };

  const loadOverview = (next: FilterValues = {}) => {
    const requestId = ++overviewRequestSequence.current;
    setOverviewLoading(true);
    setOverviewError("");
    if (activeSectionRef.current === "situation-map") {
      ++requestSequence.current;
      setLoading(true);
      setError("");
      setSelectedIncidentId(null);
    }
    apiFetch<OverviewData>(`${config["situation-map"].endpoint}?${queryFor(next)}`)
      .then((data) => {
        if (requestId !== overviewRequestSequence.current) return;
        setSharedOverview(data);
        if (activeSectionRef.current === "situation-map") {
          applyTablePayload("situation-map", data);
          setLoading(false);
        }
      })
      .catch((reason) => {
        if (requestId !== overviewRequestSequence.current) return;
        setOverviewError(reason.message);
        if (activeSectionRef.current === "situation-map") {
          setError(reason.message);
          setLoadedSection(null);
          setLoading(false);
        }
      })
      .finally(() => {
        if (requestId === overviewRequestSequence.current) setOverviewLoading(false);
      });
  };

  useEffect(() => {
    setSearch("");
    setSortKey(null);
    setSortDirection("asc");
    setPageNumber(1);
    if (isSituationHub) {
      if (!sharedOverview && !overviewLoading) loadOverview(filters);
      if (activeSection === "situation-map") {
        ++requestSequence.current;
        if (sharedOverview) {
          applyTablePayload("situation-map", sharedOverview);
          setLoading(false);
          setError("");
        } else {
          setLoading(true);
        }
      } else {
        loadTable(activeSection, filters);
      }
    } else {
      loadTable(activeSection, filters);
    }
  }, [activeSection]); // eslint-disable-line react-hooks/exhaustive-deps

  const columns = useMemo(() => {
    if (activeSection === "situation-map") return SITUATION_COLUMNS;
    const keys = new Set<string>();
    rows.slice(0, 10).forEach((row) => Object.keys(row).forEach((key) => {
      if (!["id", "lat", "lng"].includes(key)) keys.add(key);
    }));
    return [...keys].slice(0, 9);
  }, [activeSection, rows]);

  const metricItems = useMemo(() => {
    if (isSituationHub) {
      if (!sharedOverview) return [];
      const range = displayedDateRange(sharedOverview.map as unknown as Record<string, unknown>[]);
      return [
        { key: "generated_at", label: "Generated at", value: formatMetricValue("generated_at", sharedOverview.generated_at) },
        { key: "unresolved_province_incidents", label: "Unresolved province incidents", value: sharedOverview.unresolved_province_incidents.toLocaleString("id-ID") },
        ...(range ? [{ key: "displayed_date_range", label: "Rentang data peta", value: range }] : []),
      ];
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return [];
    const scalarMetrics = Object.entries(payload as Record<string, unknown>)
      .filter(([, value]) => typeof value === "number" || typeof value === "string")
      .slice(0, 6)
      .map(([key, value]) => ({ key, label: humanize(key), value: formatMetricValue(key, value as string | number) }));
    return scalarMetrics;
  }, [isSituationHub, payload, sharedOverview]);

  const visibleRows = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("id-ID");
    const filtered = query
      ? rows.filter((row) => columns.some((key) => cellValue(key, row[key]).toLocaleLowerCase("id-ID").includes(query)))
      : rows;
    if (!sortKey) return filtered;
    return filtered
      .map((row, index) => ({ row, index }))
      .sort((left, right) => {
        const a = comparableValue(sortKey, left.row[sortKey]);
        const b = comparableValue(sortKey, right.row[sortKey]);
        const result = typeof a === "number" && typeof b === "number"
          ? a - b
          : String(a).localeCompare(String(b), "id-ID", { numeric: true, sensitivity: "base" });
        return result === 0 ? left.index - right.index : (sortDirection === "asc" ? result : -result);
      })
      .map(({ row }) => row);
  }, [columns, rows, search, sortDirection, sortKey]);

  const pageCount = Math.max(1, Math.ceil(visibleRows.length / pageSize));
  const paginatedRows = useMemo(() => {
    const start = (pageNumber - 1) * pageSize;
    return visibleRows.slice(start, start + pageSize);
  }, [pageNumber, pageSize, visibleRows]);
  const firstRow = visibleRows.length ? (pageNumber - 1) * pageSize + 1 : 0;
  const lastRow = Math.min(pageNumber * pageSize, visibleRows.length);
  const contentLoading = loading || loadedSection !== activeSection;

  useEffect(() => setPageNumber(1), [activeSection, search, pageSize, sortKey, sortDirection]);
  useEffect(() => setPageNumber((current) => Math.min(current, pageCount)), [pageCount]);

  const toggleSort = (key: string) => {
    if (sortKey === key) setSortDirection((current) => current === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDirection("asc");
    }
  };

  const selectSituationTab = (next: SituationTab) => {
    if (next === activeSection) return;
    setActiveSection(next);
    const nextUrl = next === "situation-map" ? "/situation-map" : `/situation-map?tab=${next}`;
    window.history.pushState({ ...window.history.state }, "", nextUrl);
  };

  const applyFilters = (next: FilterValues) => {
    setFilters(next);
    if (isSituationHub) {
      loadOverview(next);
      if (activeSection !== "situation-map") loadTable(activeSection, next);
    } else {
      loadTable(activeSection, next);
    }
  };

  return (
    <div className={embedded ? "" : "px-5 pb-10 pt-5 md:px-8 lg:px-10 lg:pt-6"}>
      {!embedded && <PageHeader
        eyebrow={isSituationHub ? SITUATION_HUB.eyebrow : page.eyebrow}
        title={isSituationHub ? SITUATION_HUB.title : page.title}
        description={isSituationHub ? SITUATION_HUB.description : page.description}
      />}

      {isSituationHub && (
        <section className="panel mb-5 overflow-hidden" aria-label="Indonesia Situation Map views">
          <div className="flex overflow-x-auto border-b border-slate-200 p-2" role="tablist" aria-label="Indonesia Situation Map tabs">
            {SITUATION_TABS.map(({ id, label, icon: Icon }) => {
              const active = activeSection === id;
              return (
                <button
                  key={id}
                  id={`situation-tab-${id}`}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  aria-controls="situation-tab-panel"
                  tabIndex={active ? 0 : -1}
                  onClick={() => selectSituationTab(id)}
                  className={`flex min-h-11 shrink-0 items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-bold transition ${active ? "bg-ink text-white shadow-sm" : "text-slate-500 hover:bg-slate-100 hover:text-ink"}`}
                >
                  <Icon size={16} aria-hidden="true" />
                  {label}
                </button>
              );
            })}
          </div>
          <div className="flex items-start gap-3 px-5 py-4">
            <div>
              <div className="eyebrow">{config["situation-map"].eyebrow}</div>
              <h2 className="mt-1 font-serif text-lg">{config["situation-map"].title}</h2>
              <p className="mt-1 max-w-4xl text-xs leading-5 text-slate-500">{config["situation-map"].description}</p>
            </div>
          </div>
        </section>
      )}

      <div
        id={isSituationHub ? "situation-tab-panel" : undefined}
        role={isSituationHub ? "tabpanel" : undefined}
        aria-labelledby={isSituationHub ? `situation-tab-${activeSection}` : undefined}
      >
      <GlobalFilters onApply={applyFilters} compact />

      {isSituationHub && overviewError && <div role="alert" className="mb-5 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">Data peta terbaru tidak dapat dimuat: {overviewError}. Peta terakhir yang berhasil dimuat tetap ditampilkan.</div>}

      {metricItems.length > 0 && (
        <div className={`mb-5 grid gap-3 ${isSituationHub ? "grid-cols-1 sm:grid-cols-3" : "grid-cols-2 md:grid-cols-3 xl:grid-cols-6"}`}>
          {metricItems.map((metric) => (
            <div key={metric.key} className="panel min-w-0 p-4">
              <div className="text-[9px] font-bold uppercase tracking-wider text-slate-400">{metric.label}</div>
              <div className="mt-3 break-words text-lg font-bold leading-snug tracking-tight text-ink sm:text-xl">{metric.value}</div>
            </div>
          ))}
        </div>
      )}

      {isSituationHub && overviewLoading && sharedOverview === null && <div className="panel mb-5 p-5"><div className="skeleton h-[420px] w-full" /></div>}

      {isSituationHub && sharedOverview !== null && (
        <div className="panel mb-5 p-5">
          <LeafletMap
            incidents={sharedOverview.map as IncidentMapPoint[]}
            terminals={sharedOverview.terminals}
            selectedIncidentId={activeSection === "situation-map" ? selectedIncidentId : null}
            provinceHeatmap={sharedOverview.province_heatmap}
            showProvinceHeatmapToggle
          />
          <p className="mt-3 text-[10px] leading-4 text-slate-500">Titik insiden pada peta berasal dari baris Structured Analytics yang sama. Marker kuning menandai gangguan pasokan, merah menandai laporan kecelakaan MT, biru menandai gangguan eksternal, dan hijau adalah referensi master TBBM.</p>
        </div>
      )}

      <div className="panel overflow-hidden">
        <div className="flex flex-col gap-4 border-b border-slate-200 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <span className="font-serif text-lg">Structured analytics</span>
            <span className="ml-2 text-xs text-slate-400">{visibleRows.length === rows.length ? `${rows.length} rows` : `${visibleRows.length} dari ${rows.length} rows`}</span>
            {activeSection === "situation-map" && <span className="ml-3 text-[10px] text-slate-400">Klik baris untuk menyorot titik yang sama pada peta.</span>}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <label className="relative block min-w-0 sm:w-72">
              <span className="sr-only">Cari Structured Analytics</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={14} />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Cari seluruh kolom…"
                className="h-10 w-full rounded-xl border border-slate-200 bg-white pl-9 pr-9 text-xs text-slate-600 focus:border-lime focus:outline-none focus:ring-2 focus:ring-lime/20"
              />
              {search && <button type="button" onClick={() => setSearch("")} aria-label="Hapus pencarian" className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-ink"><X size={13} /></button>}
            </label>
            <label className="flex items-center gap-2 whitespace-nowrap text-[10px] font-bold uppercase tracking-wider text-slate-400">
              Baris
              <select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value) as (typeof PAGE_SIZE_OPTIONS)[number])} className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold text-ink">
                {PAGE_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size}</option>)}
              </select>
            </label>
          </div>
        </div>

        {page.disclaimer && <div className="border-b border-amber-200 bg-amber-50 px-5 py-3 text-xs text-amber-900">{page.disclaimer}</div>}

        {error ? (
          <div className="p-8 text-red-600">{error}</div>
        ) : contentLoading ? (
          <div className="space-y-3 p-5">{Array.from({ length: 6 }).map((_, index) => <div key={index} className="skeleton h-10" />)}</div>
        ) : rows.length === 0 ? (
          <div className="p-12 text-center text-slate-400">No structured records match this view.</div>
        ) : visibleRows.length === 0 ? (
          <div className="p-12 text-center text-slate-400"><Search className="mx-auto mb-3" size={24} /><p>Tidak ada data yang cocok dengan pencarian “{search}”.</p><button type="button" onClick={() => setSearch("")} className="mt-3 text-xs font-bold text-petrol">Hapus pencarian</button></div>
        ) : (
          <>
            <div className="scroll-table">
              <table className="data-table">
                <thead>
                  <tr>
                    {columns.map((key) => {
                      const active = sortKey === key;
                      const SortIcon = active ? (sortDirection === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
                      return (
                        <th key={key} aria-sort={active ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}>
                          <button type="button" onClick={() => toggleSort(key)} className={`inline-flex items-center gap-1.5 rounded-md py-1 text-left transition ${active ? "text-petrol" : "hover:text-ink"}`}>
                            {columnLabel(key)} <SortIcon size={11} aria-hidden="true" />
                          </button>
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {paginatedRows.map((row, index) => {
                    const incidentId = typeof row.id === "number" ? row.id : null;
                    const selectable = activeSection === "situation-map" && incidentId !== null;
                    const selected = selectable && selectedIncidentId === incidentId;
                    return (
                      <tr
                        key={incidentId ?? `${pageNumber}-${index}`}
                        className={selected ? "map-linked-row-selected" : selectable ? "map-linked-row" : ""}
                        onClick={selectable ? () => setSelectedIncidentId(incidentId) : undefined}
                        onKeyDown={selectable ? (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedIncidentId(incidentId); } } : undefined}
                        tabIndex={selectable ? 0 : undefined}
                        aria-selected={selectable ? selected : undefined}
                      >
                        {columns.map((key) => <td key={key}>{cellValue(key, row[key])}</td>)}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="flex flex-col gap-3 border-t border-slate-200 bg-slate-50/60 px-5 py-3 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between">
              <span>Menampilkan <strong className="text-ink">{firstRow}–{lastRow}</strong> dari <strong className="text-ink">{visibleRows.length}</strong> baris</span>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => setPageNumber((current) => Math.max(1, current - 1))} disabled={pageNumber === 1} className="grid h-9 w-9 place-items-center rounded-lg border border-slate-200 bg-white text-ink disabled:cursor-not-allowed disabled:opacity-35" aria-label="Halaman sebelumnya"><ChevronLeft size={15} /></button>
                <span className="min-w-24 text-center font-semibold text-ink">Halaman {pageNumber} / {pageCount}</span>
                <button type="button" onClick={() => setPageNumber((current) => Math.min(pageCount, current + 1))} disabled={pageNumber === pageCount} className="grid h-9 w-9 place-items-center rounded-lg border border-slate-200 bg-white text-ink disabled:cursor-not-allowed disabled:opacity-35" aria-label="Halaman berikutnya"><ChevronRight size={15} /></button>
              </div>
            </div>
          </>
        )}
      </div>
      </div>
    </div>
  );
}
