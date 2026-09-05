"use client";

import {
  ArrowUpDown, Check, ChevronLeft, ChevronRight, CircleAlert, ExternalLink, Eye, Factory, Gauge,
  MapPin, Pencil, Plus, RefreshCw, Search, Settings2, SlidersHorizontal, Trash2, X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch, formatDate, humanize } from "@/lib/api";
import PageHeader from "./PageHeader";
import TbbmMap, { TbbmMapItem } from "./TbbmMap";

type Province = { id: number; code: string; name: string; is_active: boolean };
type Keyword = { id: number; keyword: string; is_active: boolean; sort_order: number };
type Summary = Record<"total_terminal" | "verified" | "need_review" | "tbbm" | "fuel_terminal" | "integrated_terminal" | "depot_bbm" | "tlpg", number>;
type Tbbm = TbbmMapItem & {
  normalized_name: string; city?: string | null; regency?: string | null; province_id?: number | null; postal_code?: string | null;
  google_place_id?: string | null; google_maps_uri?: string | null; google_primary_type?: string | null; google_types: string[];
  source: string; operational_status: string; first_discovered_at?: string | null; last_discovered_at?: string | null;
  last_verified_at?: string | null; created_at: string; updated_at: string;
  provenance?: { id: string; keyword: string; query_text: string; first_seen_at: string; last_seen_at: string }[];
};
type Job = {
  id: string; status: string; search_scope: string; selected_provinces: Province[]; selected_keywords: Keyword[];
  existing_data_mode: string; total_queries: number; completed_queries: number; successful_queries: number; failed_queries: number;
  raw_result_count: number; unique_place_count: number; existing_match_count: number; new_candidate_count: number;
  possible_duplicate_count: number; rejected_auto_count: number; current_province?: string | null; current_keyword?: string | null;
  progress: number; created_by?: string | null; started_at?: string | null; finished_at?: string | null; created_at: string;
  error_message?: string | null;
};
type Candidate = {
  id: string; discovery_job_id: string; province_id?: number | null; province_name?: string | null; keyword_id?: number | null;
  keyword: string; source_keywords: string[]; query_text: string; query_page: number; google_place_id?: string | null;
  place_name: string; normalized_name: string; formatted_address?: string | null; latitude: number; longitude: number;
  google_maps_uri?: string | null; google_types: string[]; google_primary_type?: string | null; terminal_type: string;
  match_status: string; review_status: string; rejection_reason?: string | null; matched_master_tbbm_id?: string | null;
  duplicate_group_id?: string | null; duplicate_distance_meters?: number | null; duplicate_score?: number | null;
  address_similarity?: number | null; discovered_at: string; matched_master?: Tbbm | null;
  query_provenance?: { keyword: string; query_text: string; province_name: string; query_page: number }[];
};
type TbbmSettings = {
  api: string; api_key_status: string; api_key_source?: string | null; country: string; language_code: string;
  search_strategy: string; request_delay_ms: number; maximum_retry: number; timeout_seconds: number;
  duplicate_radius_meters: number; name_similarity_threshold: number;
};
type KeywordPerformance = { keyword_id: number; keyword: string; raw_places: number; unique_candidates: number; approved_terminals: number };

const emptySummary: Summary = { total_terminal: 0, verified: 0, need_review: 0, tbbm: 0, fuel_terminal: 0, integrated_terminal: 0, depot_bbm: 0, tlpg: 0 };
const terminalTypes = ["TBBM", "FUEL_TERMINAL", "INTEGRATED_TERMINAL", "DEPOT_BBM", "TLPG", "OTHER"];
const inputClass = "h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-700";
const buttonPrimary = "inline-flex items-center justify-center gap-2 rounded-xl bg-ink px-4 py-2.5 text-xs font-bold text-white hover:bg-petrol disabled:opacity-50";
const buttonSecondary = "inline-flex items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-xs font-bold text-slate-600 hover:bg-slate-50 disabled:opacity-50";

const blankDraft = {
  name: "", terminal_type: "TBBM", address: "", province_id: "", city: "", regency: "", postal_code: "",
  latitude: "", longitude: "", operational_status: "UNKNOWN", verification_status: "NEED_REVIEW",
  google_place_id: "", google_maps_uri: "",
};

async function protectedFetch<T>(path: string, method: "POST" | "PATCH" | "DELETE" = "POST", payload?: unknown): Promise<T> {
  const response = await fetch(path ? `/tbbm-api/${path}` : "/tbbm-api", {
    method,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const result = await response.json().catch(() => null) as ({ detail?: string } & T) | null;
  if (!response.ok) throw new Error(result?.detail || `API request failed (${response.status})`);
  return result as T;
}

function Badge({ value }: { value: string }) {
  const tone = value.includes("REJECT") || value === "FAILED" ? "bg-red-50 text-red-700"
    : value.includes("DUPLICATE") || value.includes("ERROR") || value === "NEED_REVIEW" ? "bg-amber-50 text-amber-700"
      : value === "VERIFIED" || value === "APPROVED" || value === "COMPLETED" || value === "ACTIVE" ? "bg-emerald-50 text-emerald-700"
        : value === "RUNNING" ? "bg-blue-50 text-blue-700" : "bg-slate-100 text-slate-600";
  return <span className={`inline-flex rounded-full px-2 py-1 text-[9px] font-black tracking-wide ${tone}`}>{humanize(value)}</span>;
}

function Modal({ title, eyebrow, onClose, children, width = "max-w-3xl" }: { title: string; eyebrow: string; onClose: () => void; children: React.ReactNode; width?: string }) {
  return <div className="fixed inset-0 z-[1000] grid place-items-center overflow-y-auto bg-slate-950/45 p-4" role="dialog" aria-modal="true">
    <div className={`my-6 w-full ${width} max-h-[92vh] overflow-y-auto rounded-2xl bg-white shadow-2xl`}>
      <div className="sticky top-0 z-10 flex items-start justify-between border-b border-slate-200 bg-white px-6 py-5">
        <div><div className="eyebrow">{eyebrow}</div><h2 className="mt-1 font-serif text-2xl">{title}</h2></div>
        <button onClick={onClose} aria-label="Close" className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X size={18} /></button>
      </div>
      {children}
    </div>
  </div>;
}

export default function TbbmConsole() {
  const [tab, setTab] = useState<"master" | "results" | "history">("master");
  const [summary, setSummary] = useState<Summary>(emptySummary);
  const [masters, setMasters] = useState<Tbbm[]>([]);
  const [mapTerminals, setMapTerminals] = useState<Tbbm[]>([]);
  const [masterTotal, setMasterTotal] = useState(0);
  const [masterPage, setMasterPage] = useState(1);
  const [provinces, setProvinces] = useState<Province[]>([]);
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [settings, setSettings] = useState<TbbmSettings | null>(null);
  const [performance, setPerformance] = useState<KeywordPerformance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filters, setFilters] = useState({ search: "", province_id: "", terminal_type: "", verification_status: "", operational_status: "", source: "", sort_by: "name", sort_order: "asc" });
  const [discoveryOpen, setDiscoveryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [masterMode, setMasterMode] = useState<"add" | "edit" | "view" | null>(null);
  const [activeMaster, setActiveMaster] = useState<Tbbm | null>(null);
  const [masterDraft, setMasterDraft] = useState(blankDraft);
  const [currentJob, setCurrentJob] = useState<Job | null>(null);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [results, setResults] = useState<Candidate[]>([]);
  const [resultTotal, setResultTotal] = useState(0);
  const [resultPage, setResultPage] = useState(1);
  const [resultFilters, setResultFilters] = useState({ province_id: "", keyword_id: "", terminal_type: "", match_status: "", review_status: "" });
  const [selectedResults, setSelectedResults] = useState<string[]>([]);
  const [activeCandidate, setActiveCandidate] = useState<Candidate | null>(null);
  const [editingCandidate, setEditingCandidate] = useState(false);
  const [mergeTarget, setMergeTarget] = useState("");
  const [busy, setBusy] = useState(false);

  const loadMasters = useCallback(async (page = masterPage, nextFilters = filters) => {
    const query = new URLSearchParams({ page: String(page), per_page: "25" });
    Object.entries(nextFilters).forEach(([key, value]) => value && query.set(key, value));
    const data = await apiFetch<{ items: Tbbm[]; total: number }>(`/tbbm?${query}`);
    setMasters(data.items); setMasterTotal(data.total);
  }, [filters, masterPage]);

  const loadJobs = useCallback(async () => {
    const data = await apiFetch<{ items: Job[] }>("/tbbm/discovery/jobs?per_page=100");
    setJobs(data.items);
    const active = data.items.find((job) => ["PENDING", "RUNNING"].includes(job.status));
    if (active) setCurrentJob(active);
    setSelectedJobId((value) => value || data.items[0]?.id || "");
    return data.items;
  }, []);

  const loadBase = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [nextSummary, nextMap, nextProvinces, nextKeywords, nextSettings, nextPerformance] = await Promise.all([
        apiFetch<Summary>("/tbbm/summary"), apiFetch<Tbbm[]>("/tbbm/map"), apiFetch<Province[]>("/tbbm/provinces"),
        apiFetch<Keyword[]>("/tbbm/discovery/keywords"), apiFetch<TbbmSettings>("/tbbm/settings"),
        apiFetch<KeywordPerformance[]>("/tbbm/discovery/analytics/keywords"),
      ]);
      setSummary(nextSummary); setMapTerminals(nextMap); setProvinces(nextProvinces); setKeywords(nextKeywords);
      setSettings(nextSettings); setPerformance(nextPerformance);
      await Promise.all([loadMasters(), loadJobs()]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Master TBBM gagal dimuat."); }
    finally { setLoading(false); }
  }, [loadJobs, loadMasters]);

  useEffect(() => { void loadBase(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadResults = useCallback(async (jobId = selectedJobId, page = resultPage, nextFilters = resultFilters) => {
    if (!jobId) { setResults([]); setResultTotal(0); return; }
    const query = new URLSearchParams({ page: String(page), per_page: "25" });
    Object.entries(nextFilters).forEach(([key, value]) => value && query.set(key, value));
    const data = await apiFetch<{ items: Candidate[]; total: number }>(`/tbbm/discovery/jobs/${jobId}/results?${query}`);
    setResults(data.items); setResultTotal(data.total); setSelectedResults([]);
  }, [resultFilters, resultPage, selectedJobId]);

  useEffect(() => { if (tab === "results" && selectedJobId) void loadResults(selectedJobId, 1); }, [tab, selectedJobId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!currentJob || !["PENDING", "RUNNING"].includes(currentJob.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const job = await apiFetch<Job>(`/tbbm/discovery/jobs/${currentJob.id}`);
        setCurrentJob(job);
        if (!["PENDING", "RUNNING"].includes(job.status)) {
          window.clearInterval(timer); await loadBase();
          if (selectedJobId === job.id) await loadResults(job.id, 1);
        }
      } catch { /* retain last truthful state; manual refresh remains available */ }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [currentJob?.id, currentJob?.status, loadBase, loadResults, selectedJobId]);

  const setFilter = (key: string, value: string) => setFilters((current) => ({ ...current, [key]: value }));
  const applyFilters = (event: FormEvent) => { event.preventDefault(); setMasterPage(1); void loadMasters(1); };
  const resetFilters = () => {
    const next = { search: "", province_id: "", terminal_type: "", verification_status: "", operational_status: "", source: "", sort_by: "name", sort_order: "asc" };
    setFilters(next); setMasterPage(1); void loadMasters(1, next);
  };
  const sortMaster = (sortBy: string) => {
    const next = { ...filters, sort_by: sortBy, sort_order: filters.sort_by === sortBy && filters.sort_order === "asc" ? "desc" : "asc" };
    setFilters(next); setMasterPage(1); void loadMasters(1, next);
  };

  const openMaster = async (row: Tbbm, mode: "view" | "edit") => {
    setError("");
    try {
      const detail = await apiFetch<Tbbm>(`/tbbm/${row.id}`);
      setActiveMaster(detail); setMasterMode(mode);
      setMasterDraft({
        name: detail.name, terminal_type: detail.terminal_type, address: detail.address || "", province_id: String(detail.province_id || ""),
        city: detail.city || "", regency: detail.regency || "", postal_code: detail.postal_code || "",
        latitude: String(detail.latitude), longitude: String(detail.longitude), operational_status: detail.operational_status,
        verification_status: detail.verification_status, google_place_id: detail.google_place_id || "", google_maps_uri: detail.google_maps_uri || "",
      });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Detail gagal dimuat."); }
  };

  const submitMaster = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError("");
    const payload = {
      name: masterDraft.name, terminal_type: masterDraft.terminal_type, address: masterDraft.address || null,
      province_id: masterDraft.province_id ? Number(masterDraft.province_id) : null, city: masterDraft.city || null,
      regency: masterDraft.regency || null, postal_code: masterDraft.postal_code || null,
      latitude: Number(masterDraft.latitude), longitude: Number(masterDraft.longitude),
      operational_status: masterDraft.operational_status, verification_status: masterDraft.verification_status,
      google_place_id: masterDraft.google_place_id || null, google_maps_uri: masterDraft.google_maps_uri || null,
    };
    try {
      if (masterMode === "edit" && activeMaster) await protectedFetch<Tbbm>(activeMaster.id, "PATCH", payload);
      else await protectedFetch<Tbbm>("", "POST", payload);
      setMasterMode(null); setNotice(masterMode === "edit" ? "Master TBBM diperbarui." : "Master TBBM manual ditambahkan.");
      await loadBase();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Master TBBM gagal disimpan."); }
    finally { setBusy(false); }
  };

  const deactivateMaster = async (row: Tbbm) => {
    if (!window.confirm(`Nonaktifkan ${row.name}? Data historis tetap disimpan.`)) return;
    try { await protectedFetch(row.id, "DELETE"); setNotice("Master TBBM dinonaktifkan."); await loadBase(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Master TBBM gagal dinonaktifkan."); }
  };

  const openCandidate = async (row: Candidate) => {
    try {
      const detail = await apiFetch<Candidate>(`/tbbm/discovery/results/${row.id}`);
      setActiveCandidate(detail); setEditingCandidate(false); setMergeTarget(detail.matched_master_tbbm_id || "");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Candidate detail gagal dimuat."); }
  };

  const reviewAction = async (action: "approve" | "keep" | "merge" | "reject") => {
    if (!activeCandidate) return;
    let payload: unknown = undefined;
    let path = `discovery/results/${activeCandidate.id}/${action === "keep" ? "approve?keep_both=true" : action}`;
    if (action === "merge") {
      if (!mergeTarget) { setError("Pilih Master TBBM tujuan merge."); return; }
      payload = { master_tbbm_id: mergeTarget };
    }
    if (action === "reject") {
      const reason = window.prompt("Alasan penolakan kandidat:", activeCandidate.rejection_reason || "Bukan terminal BBM yang valid.");
      if (!reason) return;
      payload = { reason };
    }
    setBusy(true);
    try {
      await protectedFetch(path, "POST", payload); setActiveCandidate(null); setNotice("Review kandidat tersimpan.");
      await Promise.all([loadBase(), loadResults(selectedJobId, resultPage)]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Review kandidat gagal."); }
    finally { setBusy(false); }
  };

  const saveCandidate = async () => {
    if (!activeCandidate) return;
    setBusy(true);
    try {
      const next = await protectedFetch<Candidate>(`discovery/results/${activeCandidate.id}`, "PATCH", {
        place_name: activeCandidate.place_name, terminal_type: activeCandidate.terminal_type,
        formatted_address: activeCandidate.formatted_address || null, province_id: activeCandidate.province_id || null,
        latitude: Number(activeCandidate.latitude), longitude: Number(activeCandidate.longitude),
      });
      setActiveCandidate(next); setEditingCandidate(false); setNotice("Kandidat diperbarui."); await loadResults(selectedJobId, resultPage);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Kandidat gagal diperbarui."); }
    finally { setBusy(false); }
  };

  const bulkReview = async (action: "approve" | "reject") => {
    if (!selectedResults.length) return;
    const payload = { result_ids: selectedResults, ...(action === "reject" ? { reason: "Ditolak melalui bulk review." } : {}) };
    try {
      await protectedFetch(`discovery/results/bulk-${action}`, "POST", payload); setNotice(`${selectedResults.length} kandidat selesai direview.`);
      await Promise.all([loadBase(), loadResults(selectedJobId, resultPage)]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Bulk review gagal."); }
  };

  const cards: [string, number][] = [
    ["Total Terminal", summary.total_terminal], ["Verified", summary.verified], ["Need Review", summary.need_review],
    ["TBBM", summary.tbbm], ["Fuel Terminal", summary.fuel_terminal], ["Integrated Terminal", summary.integrated_terminal],
    ["Depot BBM", summary.depot_bbm], ["TLPG", summary.tlpg],
  ];
  const selectedJob = jobs.find((job) => job.id === selectedJobId);
  const allResultsChecked = results.length > 0 && results.every((item) => selectedResults.includes(item.id));
  const candidateMap = activeCandidate ? [{
    id: activeCandidate.id, tbbm_code: "CANDIDATE", name: activeCandidate.place_name,
    terminal_type: activeCandidate.terminal_type, province_name: activeCandidate.province_name,
    address: activeCandidate.formatted_address, verification_status: "NEED_REVIEW",
    latitude: activeCandidate.latitude, longitude: activeCandidate.longitude,
  }] : [];

  return <div className="px-5 pb-10 pt-5 md:px-8 lg:px-10 lg:pt-6">
    <PageHeader
      eyebrow="Master Data"
      title="Master Data TBBM / Fuel Terminal"
      description="Referensi lokasi terminal BBM Pertamina di seluruh Indonesia"
      action={<div className="flex flex-wrap gap-2">
        <button onClick={() => setSettingsOpen(true)} className={buttonSecondary}><Settings2 size={14} />API Settings</button>
        <button onClick={() => { setMasterDraft(blankDraft); setActiveMaster(null); setMasterMode("add"); }} className={buttonSecondary}><Plus size={14} />Add Manual</button>
        <button onClick={() => setDiscoveryOpen(true)} className={buttonPrimary}><MapPin size={14} />Get Data TBBM</button>
      </div>}
    />

    {(error || notice) && <div className={`mb-5 flex items-start justify-between rounded-xl border p-3 text-xs ${error ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>
      <span>{error || notice}</span><button onClick={() => { setError(""); setNotice(""); }}><X size={14} /></button>
    </div>}

    <div className="mb-5 flex flex-wrap gap-2 border-b border-slate-200">
      {(["master", "results", "history"] as const).map((item) => <button key={item} onClick={() => setTab(item)} className={`border-b-2 px-4 py-3 text-xs font-bold ${tab === item ? "border-petrol text-petrol" : "border-transparent text-slate-400"}`}>
        {item === "master" ? "Master TBBM" : item === "results" ? "Discovery Results" : "Discovery History"}
      </button>)}
    </div>

    {currentJob && <JobProgress job={currentJob} onRefresh={async () => setCurrentJob(await apiFetch<Job>(`/tbbm/discovery/jobs/${currentJob.id}`))} onView={() => { setSelectedJobId(currentJob.id); setTab("results"); }} onCancel={async () => {
      try { setCurrentJob(await protectedFetch<Job>(`discovery/jobs/${currentJob.id}/cancel`)); await loadJobs(); }
      catch (reason) { setError(reason instanceof Error ? reason.message : "Job gagal dibatalkan."); }
    }} />}

    {loading ? <div className="space-y-4"><div className="skeleton h-24" /><div className="skeleton h-96" /></div> : tab === "master" ? <>
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        {cards.map(([label, value]) => <div key={label} className="panel px-4 py-3"><div className="text-[9px] font-bold uppercase tracking-wider text-slate-400">{label}</div><div className="metric-number mt-1 text-2xl">{value.toLocaleString("id-ID")}</div></div>)}
      </div>
      <form onSubmit={applyFilters} className="panel mb-5 p-3">
        <div className="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider text-slate-500"><SlidersHorizontal size={13} /> Filter Master TBBM</div>
        <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-8">
          <div className="relative md:col-span-2"><Search className="absolute left-3 top-3 text-slate-400" size={14} /><input className={`${inputClass} pl-9`} placeholder="Nama, alamat, atau kode TBBM" value={filters.search} onChange={(event) => setFilter("search", event.target.value)} /></div>
          <select className={inputClass} value={filters.province_id} onChange={(event) => setFilter("province_id", event.target.value)}><option value="">Semua provinsi</option>{provinces.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select>
          <select className={inputClass} value={filters.terminal_type} onChange={(event) => setFilter("terminal_type", event.target.value)}><option value="">Semua tipe</option>{terminalTypes.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}</select>
          <select className={inputClass} value={filters.verification_status} onChange={(event) => setFilter("verification_status", event.target.value)}><option value="">Semua verifikasi</option>{["VERIFIED", "NEED_REVIEW", "REJECTED"].map((value) => <option key={value}>{value}</option>)}</select>
          <select className={inputClass} value={filters.operational_status} onChange={(event) => setFilter("operational_status", event.target.value)}><option value="">Semua operasional</option>{["ACTIVE", "INACTIVE", "UNKNOWN"].map((value) => <option key={value}>{value}</option>)}</select>
          <select className={inputClass} value={filters.source} onChange={(event) => setFilter("source", event.target.value)}><option value="">Semua sumber</option>{["GOOGLE_PLACES", "MANUAL", "IMPORT"].map((value) => <option key={value} value={value}>{humanize(value)}</option>)}</select>
          <div className="flex gap-2"><button className="h-10 flex-1 rounded-lg bg-ink text-xs font-bold text-white">Apply</button><button type="button" onClick={resetFilters} className="grid h-10 w-10 place-items-center rounded-lg border border-slate-200"><RefreshCw size={13} /></button></div>
        </div>
      </form>
      {mapTerminals.length ? <div className="panel mb-5 p-3"><TbbmMap terminals={mapTerminals} selectedId={activeMaster?.id} onSelect={(item) => void openMaster(item as Tbbm, "view")} /></div> : <div className="panel mb-5 p-12 text-center"><MapPin className="mx-auto text-slate-300" /><p className="mt-3 font-serif text-xl">Belum ada Master TBBM.</p><button onClick={() => setDiscoveryOpen(true)} className={`${buttonPrimary} mt-4`}>Get Data TBBM</button></div>}
      <div className="panel overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4"><div><strong className="text-sm">Master terminal</strong><span className="ml-2 text-xs text-slate-400">{masterTotal} records</span></div><button onClick={() => void loadMasters()} className={buttonSecondary}><RefreshCw size={13} />Refresh</button></div>
        {masters.length ? <div className="scroll-table max-h-[620px]"><table className="data-table"><thead className="sticky top-0 z-10 bg-white"><tr><th><button onClick={() => sortMaster("code")}>Kode <ArrowUpDown className="inline" size={10} /></button></th><th><button onClick={() => sortMaster("name")}>Terminal Name <ArrowUpDown className="inline" size={10} /></button></th><th><button onClick={() => sortMaster("terminal_type")}>Type <ArrowUpDown className="inline" size={10} /></button></th><th><button onClick={() => sortMaster("province")}>Province <ArrowUpDown className="inline" size={10} /></button></th><th>Address</th><th>Latitude</th><th>Longitude</th><th><button onClick={() => sortMaster("verification")}>Verification <ArrowUpDown className="inline" size={10} /></button></th><th><button onClick={() => sortMaster("operational")}>Operational <ArrowUpDown className="inline" size={10} /></button></th><th>Source</th><th><button onClick={() => sortMaster("last_verified")}>Last Verified <ArrowUpDown className="inline" size={10} /></button></th><th>Actions</th></tr></thead><tbody>{masters.map((row) => <tr key={row.id}>
          <td className="font-bold text-petrol">{row.tbbm_code}</td><td className="min-w-52 font-bold">{row.name}</td><td><Badge value={row.terminal_type} /></td><td>{row.province_name || "—"}</td><td><div className="max-w-64 text-xs text-slate-500">{row.address || "—"}</div></td><td>{row.latitude.toFixed(6)}</td><td>{row.longitude.toFixed(6)}</td><td><Badge value={row.verification_status} /></td><td><Badge value={row.operational_status} /></td><td>{humanize(row.source)}</td><td className="whitespace-nowrap">{row.last_verified_at ? formatDate(row.last_verified_at, true) : "—"}</td><td><div className="flex gap-1"><button title="View" onClick={() => void openMaster(row, "view")} className="rounded-lg p-2 hover:bg-slate-100"><Eye size={14} /></button><button title="Edit" onClick={() => void openMaster(row, "edit")} className="rounded-lg p-2 hover:bg-slate-100"><Pencil size={14} /></button><button title="View map" onClick={() => { setActiveMaster(row); window.scrollTo({ top: 320, behavior: "smooth" }); }} className="rounded-lg p-2 hover:bg-slate-100"><MapPin size={14} /></button><button title="Deactivate" onClick={() => void deactivateMaster(row)} className="rounded-lg p-2 text-red-500 hover:bg-red-50"><Trash2 size={14} /></button></div></td>
        </tr>)}</tbody></table></div> : <div className="p-12 text-center text-slate-400">Belum ada Master TBBM sesuai filter.</div>}
        <Pagination page={masterPage} total={masterTotal} perPage={25} onPage={(page) => { setMasterPage(page); void loadMasters(page); }} />
      </div>
    </> : tab === "results" ? <>
      <div className="panel mb-5 p-4">
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
          <select className={inputClass} value={selectedJobId} onChange={(event) => { setSelectedJobId(event.target.value); setResultPage(1); }}><option value="">Pilih discovery job</option>{jobs.map((job) => <option key={job.id} value={job.id}>{job.id.slice(0, 8)} · {job.status} · {formatDate(job.created_at, true)}</option>)}</select>
          <select className={inputClass} value={resultFilters.province_id} onChange={(event) => setResultFilters((value) => ({ ...value, province_id: event.target.value }))}><option value="">Semua provinsi</option>{provinces.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select>
          <select className={inputClass} value={resultFilters.keyword_id} onChange={(event) => setResultFilters((value) => ({ ...value, keyword_id: event.target.value }))}><option value="">Semua keyword</option>{keywords.map((row) => <option key={row.id} value={row.id}>{row.keyword}</option>)}</select>
          <select className={inputClass} value={resultFilters.terminal_type} onChange={(event) => setResultFilters((value) => ({ ...value, terminal_type: event.target.value }))}><option value="">Semua tipe</option>{terminalTypes.map((value) => <option key={value}>{value}</option>)}</select>
          <select className={inputClass} value={resultFilters.match_status} onChange={(event) => setResultFilters((value) => ({ ...value, match_status: event.target.value }))}><option value="">Semua match</option>{["NEW", "EXISTING", "POSSIBLE_DUPLICATE", "AUTO_REJECTED"].map((value) => <option key={value}>{value}</option>)}</select>
          <div className="flex gap-2"><select className={inputClass} value={resultFilters.review_status} onChange={(event) => setResultFilters((value) => ({ ...value, review_status: event.target.value }))}><option value="">Semua review</option>{["PENDING_REVIEW", "APPROVED", "REJECTED", "MERGED"].map((value) => <option key={value}>{value}</option>)}</select><button onClick={() => { setResultPage(1); void loadResults(selectedJobId, 1); }} className="rounded-lg bg-ink px-3 text-white"><Search size={14} /></button></div>
        </div>
      </div>
      {selectedJob && <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">{[
        ["Raw", selectedJob.raw_result_count], ["Unique", selectedJob.unique_place_count], ["Existing", selectedJob.existing_match_count], ["New", selectedJob.new_candidate_count],
        ["Duplicates", selectedJob.possible_duplicate_count], ["Auto Rejected", selectedJob.rejected_auto_count], ["API Errors", selectedJob.failed_queries], ["Progress", `${selectedJob.progress}%`],
      ].map(([label, value]) => <div key={label} className="panel p-3"><div className="text-[9px] font-bold uppercase text-slate-400">{label}</div><div className="metric-number mt-1 text-xl">{value}</div></div>)}</div>}
      <div className="panel overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4"><div><strong className="text-sm">Discovery candidates</strong><span className="ml-2 text-xs text-slate-400">{resultTotal} unique places</span></div><div className="flex gap-2"><button disabled={!selectedResults.length} onClick={() => void bulkReview("approve")} className={buttonPrimary}><Check size={13} />Approve Selected</button><button disabled={!selectedResults.length} onClick={() => void bulkReview("reject")} className={buttonSecondary}><X size={13} />Reject Selected</button></div></div>
        {results.length ? <div className="scroll-table max-h-[650px]"><table className="data-table"><thead className="sticky top-0 z-10 bg-white"><tr><th><input type="checkbox" checked={allResultsChecked} onChange={(event) => setSelectedResults(event.target.checked ? results.map((row) => row.id) : [])} /></th><th>Candidate</th><th>Type</th><th>Province</th><th>Address</th><th>Coordinates</th><th>Keyword</th><th>Place ID</th><th>Match</th><th>Review</th><th>Matched Master</th><th>Distance</th><th>Similarity</th><th>Actions</th></tr></thead><tbody>{results.map((row) => <tr key={row.id}>
          <td><input type="checkbox" checked={selectedResults.includes(row.id)} onChange={(event) => setSelectedResults((current) => event.target.checked ? [...current, row.id] : current.filter((id) => id !== row.id))} /></td><td className="min-w-52 font-bold">{row.place_name}</td><td><Badge value={row.terminal_type} /></td><td>{row.province_name || "—"}</td><td><div className="max-w-64 text-xs text-slate-500">{row.formatted_address || "—"}</div></td><td className="whitespace-nowrap">{row.latitude.toFixed(5)}, {row.longitude.toFixed(5)}</td><td><div className="max-w-40 text-xs">{row.source_keywords.join(", ")}</div></td><td><div className="max-w-32 truncate" title={row.google_place_id || ""}>{row.google_place_id || "—"}</div></td><td><Badge value={row.match_status} /></td><td><Badge value={row.review_status} /></td><td>{row.matched_master?.name || "—"}</td><td>{row.duplicate_distance_meters != null ? `${Math.round(row.duplicate_distance_meters)} m` : "—"}</td><td>{row.duplicate_score != null ? `${Math.round(row.duplicate_score * 100)}%` : "—"}</td><td><button onClick={() => void openCandidate(row)} className={buttonSecondary}><Eye size={13} />Review</button></td>
        </tr>)}</tbody></table></div> : <div className="p-12 text-center"><Factory className="mx-auto text-slate-300" /><p className="mt-3 font-serif text-xl">Belum ada discovery result.</p><p className="mt-1 text-xs text-slate-400">Pilih job atau jalankan Get Data TBBM.</p></div>}
        <Pagination page={resultPage} total={resultTotal} perPage={25} onPage={(page) => { setResultPage(page); void loadResults(selectedJobId, page); }} />
      </div>
    </> : <>
      <div className="panel mb-5 overflow-hidden"><div className="border-b border-slate-200 px-5 py-4"><strong className="text-sm">Discovery History</strong></div>{jobs.length ? <div className="scroll-table"><table className="data-table"><thead><tr><th>Job ID</th><th>Created By</th><th>Started</th><th>Finished</th><th>Scope</th><th>Provinces</th><th>Keywords</th><th>Queries</th><th>Failed</th><th>Raw</th><th>Unique</th><th>New</th><th>Duplicates</th><th>Status</th><th>Actions</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.id}>
        <td className="font-mono text-[10px]">{job.id}</td><td>{job.created_by || "system"}</td><td className="whitespace-nowrap">{job.started_at ? formatDate(job.started_at, true) : "—"}</td><td className="whitespace-nowrap">{job.finished_at ? formatDate(job.finished_at, true) : "—"}</td><td>{humanize(job.search_scope)}</td><td>{job.selected_provinces.length}</td><td>{job.selected_keywords.length}</td><td>{job.completed_queries} / {job.total_queries}</td><td>{job.failed_queries}</td><td>{job.raw_result_count}</td><td>{job.unique_place_count}</td><td>{job.new_candidate_count}</td><td>{job.possible_duplicate_count}</td><td><Badge value={job.status} /></td><td><div className="flex gap-1"><button onClick={() => { setSelectedJobId(job.id); setTab("results"); }} className={buttonSecondary}>View Result</button>{job.failed_queries > 0 && <button onClick={async () => { try { const retry = await protectedFetch<Job>(`discovery/jobs/${job.id}/retry-failed`); setCurrentJob(retry); await loadJobs(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Retry gagal."); } }} className={buttonSecondary}><RefreshCw size={12} />Retry Failed</button>}</div></td>
      </tr>)}</tbody></table></div> : <div className="p-12 text-center text-slate-400">Belum ada histori discovery.</div>}</div>
      <div className="panel overflow-hidden"><div className="border-b border-slate-200 px-5 py-4"><div className="eyebrow">Keyword effectiveness</div><h2 className="mt-1 font-serif text-xl">Keyword Performance</h2></div><div className="scroll-table"><table className="data-table"><thead><tr><th>Keyword</th><th>Raw Places</th><th>Unique Candidates</th><th>Approved Terminals</th></tr></thead><tbody>{performance.map((row) => <tr key={row.keyword_id}><td className="font-bold">{row.keyword}</td><td>{row.raw_places}</td><td>{row.unique_candidates}</td><td>{row.approved_terminals}</td></tr>)}</tbody></table></div></div>
    </>}

    {discoveryOpen && <DiscoveryModal keywords={keywords.filter((row) => row.is_active)} provinces={provinces} settings={settings} onClose={() => setDiscoveryOpen(false)} onStart={async (payload) => {
      setBusy(true); setError("");
      try { const job = await protectedFetch<Job>("discovery/jobs", "POST", payload); setCurrentJob(job); setSelectedJobId(job.id); setDiscoveryOpen(false); setNotice("Discovery job dijadwalkan."); await loadJobs(); }
      catch (reason) { setError(reason instanceof Error ? reason.message : "Discovery job gagal dibuat."); }
      finally { setBusy(false); }
    }} busy={busy} />}

    {settingsOpen && settings && <SettingsModal settings={settings} keywords={keywords} onClose={() => setSettingsOpen(false)} onSaved={async () => { await loadBase(); }} setError={setError} setNotice={setNotice} />}

    {masterMode && <Modal title={masterMode === "add" ? "Add Manual TBBM" : masterMode === "edit" ? "Edit Master TBBM" : activeMaster?.name || "Master TBBM Detail"} eyebrow="Master record" onClose={() => setMasterMode(null)}>
      {masterMode === "view" && activeMaster ? <div className="space-y-5 p-6">
        <div className="grid gap-4 md:grid-cols-3"><Detail label="Identity" value={`${activeMaster.tbbm_code} · ${activeMaster.name}`} /><Detail label="Terminal Type" value={humanize(activeMaster.terminal_type)} /><Detail label="Source" value={humanize(activeMaster.source)} /><Detail label="Verification" value={humanize(activeMaster.verification_status)} /><Detail label="Operational" value={humanize(activeMaster.operational_status)} /><Detail label="Province" value={activeMaster.province_name || "—"} /><Detail label="Address" value={activeMaster.address || "—"} /><Detail label="Coordinates" value={`${activeMaster.latitude}, ${activeMaster.longitude}`} /><Detail label="Google Place ID" value={activeMaster.google_place_id || "—"} /></div>
        <TbbmMap terminals={[activeMaster]} heightClass="h-72" selectedId={activeMaster.id} />
        <div><h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Discovery Provenance</h3>{activeMaster.provenance?.length ? <div className="mt-2 divide-y divide-slate-100 rounded-xl border border-slate-200">{activeMaster.provenance.map((item) => <div key={item.id} className="p-3 text-xs"><strong>{item.keyword}</strong><div className="mt-1 text-slate-500">{item.query_text} · {formatDate(item.first_seen_at, true)} – {formatDate(item.last_seen_at, true)}</div></div>)}</div> : <p className="mt-2 text-xs text-slate-400">Tidak ada provenance Google; record berasal dari {humanize(activeMaster.source)}.</p>}</div>
        <div className="flex flex-wrap justify-end gap-2">{activeMaster.google_maps_uri && <a href={activeMaster.google_maps_uri} target="_blank" rel="noreferrer" className={buttonSecondary}><ExternalLink size={13} />View Google Maps</a>}<button onClick={() => setMasterMode("edit")} className={buttonPrimary}><Pencil size={13} />Edit</button></div>
      </div> : <form onSubmit={submitMaster} className="p-6"><MasterForm draft={masterDraft} setDraft={setMasterDraft} provinces={provinces} /><div className="mt-6 flex justify-end gap-2"><button type="button" onClick={() => setMasterMode(null)} className={buttonSecondary}>Cancel</button><button disabled={busy} className={buttonPrimary}>{busy ? "Saving…" : "Save TBBM"}</button></div></form>}
    </Modal>}

    {activeCandidate && <Modal title={activeCandidate.place_name} eyebrow="Candidate review" onClose={() => setActiveCandidate(null)} width="max-w-5xl">
      <div className="grid gap-6 p-6 lg:grid-cols-[1.15fr_.85fr]">
        <div>
          {editingCandidate ? <div className="grid gap-3 md:grid-cols-2"><label className="text-[10px] font-bold uppercase text-slate-500">Candidate name<input className={`${inputClass} mt-1`} value={activeCandidate.place_name} onChange={(event) => setActiveCandidate({ ...activeCandidate, place_name: event.target.value })} /></label><label className="text-[10px] font-bold uppercase text-slate-500">Terminal type<select className={`${inputClass} mt-1`} value={activeCandidate.terminal_type} onChange={(event) => setActiveCandidate({ ...activeCandidate, terminal_type: event.target.value })}>{terminalTypes.map((value) => <option key={value}>{value}</option>)}</select></label><label className="text-[10px] font-bold uppercase text-slate-500 md:col-span-2">Address<input className={`${inputClass} mt-1`} value={activeCandidate.formatted_address || ""} onChange={(event) => setActiveCandidate({ ...activeCandidate, formatted_address: event.target.value })} /></label><label className="text-[10px] font-bold uppercase text-slate-500">Latitude<input type="number" step="any" className={`${inputClass} mt-1`} value={activeCandidate.latitude} onChange={(event) => setActiveCandidate({ ...activeCandidate, latitude: Number(event.target.value) })} /></label><label className="text-[10px] font-bold uppercase text-slate-500">Longitude<input type="number" step="any" className={`${inputClass} mt-1`} value={activeCandidate.longitude} onChange={(event) => setActiveCandidate({ ...activeCandidate, longitude: Number(event.target.value) })} /></label><label className="text-[10px] font-bold uppercase text-slate-500">Province<select className={`${inputClass} mt-1`} value={activeCandidate.province_id || ""} onChange={(event) => setActiveCandidate({ ...activeCandidate, province_id: Number(event.target.value) || null })}><option value="">Unknown</option>{provinces.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label><div className="flex items-end gap-2"><button onClick={() => setEditingCandidate(false)} type="button" className={buttonSecondary}>Cancel</button><button onClick={() => void saveCandidate()} type="button" className={buttonPrimary}>Save Candidate</button></div></div> : <div className="grid gap-4 md:grid-cols-2"><Detail label="Terminal Type" value={humanize(activeCandidate.terminal_type)} /><Detail label="Province" value={activeCandidate.province_name || "—"} /><Detail label="Address" value={activeCandidate.formatted_address || "—"} /><Detail label="Coordinates" value={`${activeCandidate.latitude}, ${activeCandidate.longitude}`} /><Detail label="Google Place ID" value={activeCandidate.google_place_id || "—"} /><Detail label="Primary Type" value={activeCandidate.google_primary_type || "—"} /><Detail label="Match Status" value={humanize(activeCandidate.match_status)} /><Detail label="Review Status" value={humanize(activeCandidate.review_status)} /></div>}
          {activeCandidate.rejection_reason && <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800"><CircleAlert className="mr-2 inline" size={14} />{activeCandidate.rejection_reason}</div>}
          <div className="mt-5"><h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Search provenance</h3><div className="mt-2 divide-y divide-slate-100 rounded-xl border border-slate-200">{(activeCandidate.query_provenance || []).map((item, index) => <div key={`${item.query_text}-${index}`} className="p-3 text-xs"><strong>{item.keyword}</strong><div className="mt-1 text-slate-500">{item.query_text} · page {item.query_page}</div></div>)}</div></div>
        </div>
        <div className="space-y-4"><TbbmMap terminals={candidateMap} heightClass="h-64" selectedId={activeCandidate.id} />
          {activeCandidate.matched_master && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><div className="text-[10px] font-bold uppercase tracking-wider text-amber-700">Potential existing match</div><div className="mt-2 font-bold">{activeCandidate.matched_master.name}</div><div className="mt-1 text-xs text-slate-600">{activeCandidate.matched_master.address || "—"}</div><div className="mt-2 text-xs">Distance: <strong>{activeCandidate.duplicate_distance_meters ? `${Math.round(activeCandidate.duplicate_distance_meters)} m` : "exact Place ID"}</strong> · Similarity: <strong>{activeCandidate.duplicate_score ? `${Math.round(activeCandidate.duplicate_score * 100)}%` : "—"}</strong></div></div>}
          <label className="block text-[10px] font-bold uppercase text-slate-500">Merge target<select className={`${inputClass} mt-1`} value={mergeTarget} onChange={(event) => setMergeTarget(event.target.value)}><option value="">Select existing Master TBBM</option>{mapTerminals.map((row) => <option key={row.id} value={row.id}>{row.tbbm_code} · {row.name}</option>)}</select></label>
        </div>
      </div>
      <div className="sticky bottom-0 flex flex-wrap justify-end gap-2 border-t border-slate-200 bg-white px-6 py-4"><button onClick={() => setEditingCandidate(true)} className={buttonSecondary}><Pencil size={13} />Edit Candidate</button>{activeCandidate.google_maps_uri && <a className={buttonSecondary} href={activeCandidate.google_maps_uri} target="_blank" rel="noreferrer"><ExternalLink size={13} />Google Maps</a>}<button disabled={busy} onClick={() => void reviewAction("reject")} className={buttonSecondary}>Keep Existing / Reject</button><button disabled={busy || !mergeTarget} onClick={() => void reviewAction("merge")} className={buttonSecondary}>Merge with Existing</button>{activeCandidate.match_status === "POSSIBLE_DUPLICATE" ? <button disabled={busy} onClick={() => void reviewAction("keep")} className={buttonPrimary}>Keep Both</button> : <button disabled={busy} onClick={() => void reviewAction("approve")} className={buttonPrimary}>Approve as New</button>}</div>
    </Modal>}
  </div>;
}

function JobProgress({ job, onRefresh, onView, onCancel }: { job: Job; onRefresh: () => void; onView: () => void; onCancel: () => void }) {
  return <div className="panel mb-5 overflow-hidden"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4"><div><div className="eyebrow">TBBM Discovery</div><div className="mt-1 flex items-center gap-2"><Badge value={job.status} /><span className="font-mono text-[10px] text-slate-400">{job.id}</span></div></div><div className="flex gap-2"><button onClick={onRefresh} className={buttonSecondary}><RefreshCw size={13} />Refresh</button><button onClick={onView} className={buttonSecondary}><Eye size={13} />View Detail</button>{["PENDING", "RUNNING"].includes(job.status) && <button onClick={onCancel} className={buttonSecondary}><X size={13} />Cancel Job</button>}</div></div>
    <div className="p-5"><div className="mb-2 flex justify-between text-xs font-bold"><span>{job.current_province || "Menyiapkan / menyelesaikan job"} · {job.current_keyword || "—"}</span><span>{job.progress}%</span></div><div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-petrol transition-all" style={{ width: `${Math.min(job.progress, 100)}%` }} /></div><div className="mt-4 grid grid-cols-2 gap-3 text-xs md:grid-cols-4 xl:grid-cols-8">{[["Search Jobs", `${job.completed_queries} / ${job.total_queries}`], ["Raw Places", job.raw_result_count], ["Unique Places", job.unique_place_count], ["Possible Duplicates", job.possible_duplicate_count], ["Failed Requests", job.failed_queries], ["Started", job.started_at ? formatDate(job.started_at, true) : "—"], ["Finished", job.finished_at ? formatDate(job.finished_at, true) : "—"], ["New Candidates", job.new_candidate_count]].map(([label, value]) => <div key={label}><div className="text-[9px] font-bold uppercase text-slate-400">{label}</div><div className="mt-1 font-bold">{value}</div></div>)}</div>{job.error_message && <div className="mt-4 rounded-lg bg-amber-50 p-3 text-xs text-amber-800">{job.error_message}</div>}</div>
  </div>;
}

function Pagination({ page, total, perPage, onPage }: { page: number; total: number; perPage: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / perPage));
  return <div className="flex items-center justify-between border-t border-slate-200 px-5 py-3 text-xs text-slate-500"><span>Page {page} of {pages}</span><div className="flex gap-1"><button disabled={page <= 1} onClick={() => onPage(page - 1)} className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"><ChevronLeft size={14} /></button><button disabled={page >= pages} onClick={() => onPage(page + 1)} className="rounded-lg border border-slate-200 p-2 disabled:opacity-30"><ChevronRight size={14} /></button></div></div>;
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div><div className="text-[9px] font-bold uppercase tracking-wider text-slate-400">{label}</div><div className="mt-1 break-words text-xs font-semibold leading-5">{value}</div></div>;
}

function MasterForm({ draft, setDraft, provinces }: { draft: typeof blankDraft; setDraft: React.Dispatch<React.SetStateAction<typeof blankDraft>>; provinces: Province[] }) {
  const update = (key: keyof typeof blankDraft, value: string) => setDraft((current) => ({ ...current, [key]: value }));
  return <div className="grid gap-4 md:grid-cols-2">
    <label className="text-[10px] font-bold uppercase text-slate-500 md:col-span-2">Terminal Name *<input required minLength={2} className={`${inputClass} mt-1`} value={draft.name} onChange={(event) => update("name", event.target.value)} /></label>
    <label className="text-[10px] font-bold uppercase text-slate-500">Terminal Type *<select required className={`${inputClass} mt-1`} value={draft.terminal_type} onChange={(event) => update("terminal_type", event.target.value)}>{terminalTypes.map((value) => <option key={value}>{value}</option>)}</select></label>
    <label className="text-[10px] font-bold uppercase text-slate-500">Province<select className={`${inputClass} mt-1`} value={draft.province_id} onChange={(event) => update("province_id", event.target.value)}><option value="">Unknown</option>{provinces.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
    <label className="text-[10px] font-bold uppercase text-slate-500 md:col-span-2">Address<input className={`${inputClass} mt-1`} value={draft.address} onChange={(event) => update("address", event.target.value)} /></label>
    <label className="text-[10px] font-bold uppercase text-slate-500">City<input className={`${inputClass} mt-1`} value={draft.city} onChange={(event) => update("city", event.target.value)} /></label>
    <label className="text-[10px] font-bold uppercase text-slate-500">Regency<input className={`${inputClass} mt-1`} value={draft.regency} onChange={(event) => update("regency", event.target.value)} /></label>
    <label className="text-[10px] font-bold uppercase text-slate-500">Latitude *<input required type="number" min={-90} max={90} step="any" className={`${inputClass} mt-1`} value={draft.latitude} onChange={(event) => update("latitude", event.target.value)} /></label>
    <label className="text-[10px] font-bold uppercase text-slate-500">Longitude *<input required type="number" min={-180} max={180} step="any" className={`${inputClass} mt-1`} value={draft.longitude} onChange={(event) => update("longitude", event.target.value)} /></label>
    <label className="text-[10px] font-bold uppercase text-slate-500">Verification<select className={`${inputClass} mt-1`} value={draft.verification_status} onChange={(event) => update("verification_status", event.target.value)}>{["VERIFIED", "NEED_REVIEW", "REJECTED"].map((value) => <option key={value}>{value}</option>)}</select></label>
    <label className="text-[10px] font-bold uppercase text-slate-500">Operational<select className={`${inputClass} mt-1`} value={draft.operational_status} onChange={(event) => update("operational_status", event.target.value)}>{["ACTIVE", "INACTIVE", "UNKNOWN"].map((value) => <option key={value}>{value}</option>)}</select></label>
    <label className="text-[10px] font-bold uppercase text-slate-500">Google Place ID<input className={`${inputClass} mt-1`} value={draft.google_place_id} onChange={(event) => update("google_place_id", event.target.value)} /></label>
    <label className="text-[10px] font-bold uppercase text-slate-500">Google Maps URI<input type="url" className={`${inputClass} mt-1`} value={draft.google_maps_uri} onChange={(event) => update("google_maps_uri", event.target.value)} /></label>
  </div>;
}

function DiscoveryModal({ keywords, provinces, settings, onClose, onStart, busy }: { keywords: Keyword[]; provinces: Province[]; settings: TbbmSettings | null; onClose: () => void; onStart: (payload: unknown) => Promise<void>; busy: boolean }) {
  const [selectedKeywords, setSelectedKeywords] = useState(keywords.map((row) => row.id));
  const [scope, setScope] = useState("ENTIRE_INDONESIA");
  const [selectedProvinces, setSelectedProvinces] = useState<number[]>([]);
  const [mode, setMode] = useState("UPDATE_AND_ADD");
  const submit = (event: FormEvent) => { event.preventDefault(); void onStart({ search_scope: scope, selected_province_ids: selectedProvinces, selected_keyword_ids: selectedKeywords, existing_data_mode: mode }); };
  return <Modal title="Get TBBM Data from Google Maps" eyebrow="Google Places Text Search (New)" onClose={onClose} width="max-w-2xl"><form onSubmit={submit} className="space-y-6 p-6">
    {settings?.api_key_status !== "CONFIGURED" && <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">Google Places API key belum dikonfigurasi. Tambahkan melalui Settings → Geocoding sebelum memulai.</div>}
    <section><div className="flex items-center justify-between"><h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Search Keywords</h3><div className="flex gap-2"><button type="button" onClick={() => setSelectedKeywords(keywords.map((row) => row.id))} className="text-[10px] font-bold text-petrol">Select All</button><button type="button" onClick={() => setSelectedKeywords([])} className="text-[10px] font-bold text-slate-400">Clear All</button></div></div><div className="mt-3 grid gap-2 sm:grid-cols-2">{keywords.map((row) => <label key={row.id} className="flex items-center gap-2 rounded-lg border border-slate-200 p-2.5 text-xs"><input type="checkbox" checked={selectedKeywords.includes(row.id)} onChange={(event) => setSelectedKeywords((current) => event.target.checked ? [...current, row.id] : current.filter((id) => id !== row.id))} />{row.keyword}</label>)}</div></section>
    <section><h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Search Coverage</h3><div className="mt-3 flex gap-5 text-xs"><label className="flex items-center gap-2"><input type="radio" checked={scope === "ENTIRE_INDONESIA"} onChange={() => setScope("ENTIRE_INDONESIA")} />Entire Indonesia</label><label className="flex items-center gap-2"><input type="radio" checked={scope === "SELECTED_PROVINCE"} onChange={() => setScope("SELECTED_PROVINCE")} />Selected Province</label></div>{scope === "SELECTED_PROVINCE" && <select multiple required className="mt-3 h-40 w-full rounded-xl border border-slate-200 p-2 text-xs" value={selectedProvinces.map(String)} onChange={(event) => setSelectedProvinces(Array.from(event.currentTarget.selectedOptions).map((option) => Number(option.value)))}>{provinces.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select>}</section>
    <section className="grid gap-4 rounded-xl bg-slate-50 p-4 md:grid-cols-2"><Detail label="Search Strategy" value="Province-Based Search" /><Detail label="Estimated baseline queries" value={String((scope === "ENTIRE_INDONESIA" ? provinces.length : selectedProvinces.length) * selectedKeywords.length)} /></section>
    <section><h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Existing Data Handling</h3><div className="mt-3 space-y-2 text-xs"><label className="flex items-center gap-2"><input type="radio" checked={mode === "UPDATE_AND_ADD"} onChange={() => setMode("UPDATE_AND_ADD")} />Update existing & add new candidates</label><label className="flex items-center gap-2"><input type="radio" checked={mode === "ADD_NEW_ONLY"} onChange={() => setMode("ADD_NEW_ONLY")} />Add new candidates only</label></div><p className="mt-2 text-[10px] text-slate-400">Kandidat tidak pernah otomatis masuk ke Master TBBM.</p></section>
    <div className="flex justify-end gap-2"><button type="button" onClick={onClose} className={buttonSecondary}>Cancel</button><button disabled={busy || !selectedKeywords.length || settings?.api_key_status !== "CONFIGURED"} className={buttonPrimary}>{busy ? "Starting…" : "Start Search"}</button></div>
  </form></Modal>;
}

function SettingsModal({ settings, keywords, onClose, onSaved, setError, setNotice }: { settings: TbbmSettings; keywords: Keyword[]; onClose: () => void; onSaved: () => Promise<void>; setError: (value: string) => void; setNotice: (value: string) => void }) {
  const [draft, setDraft] = useState(settings);
  const [newKeyword, setNewKeyword] = useState("");
  const [busy, setBusy] = useState(false);
  const saveSettings = async () => { setBusy(true); try { await protectedFetch("settings", "PATCH", { request_delay_ms: draft.request_delay_ms, maximum_retry: draft.maximum_retry, timeout_seconds: draft.timeout_seconds, duplicate_radius_meters: draft.duplicate_radius_meters, name_similarity_threshold: draft.name_similarity_threshold }); setNotice("Google Places settings diperbarui."); await onSaved(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Settings gagal disimpan."); } finally { setBusy(false); } };
  const test = async () => { setBusy(true); try { const result = await protectedFetch<{ result_count: number }>("settings/test-google-places"); setNotice(`Google Places terhubung; ${result.result_count} hasil uji diterima.`); } catch (reason) { setError(reason instanceof Error ? reason.message : "Test connection gagal."); } finally { setBusy(false); } };
  const addKeyword = async () => { if (!newKeyword.trim()) return; try { await protectedFetch("discovery/keywords", "POST", { keyword: newKeyword, is_active: true, sort_order: keywords.length + 1 }); setNewKeyword(""); await onSaved(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Keyword gagal ditambahkan."); } };
  const updateKeyword = async (row: Keyword, values: Partial<Keyword>) => { try { await protectedFetch(`discovery/keywords/${row.id}`, "PATCH", values); await onSaved(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Keyword gagal diperbarui."); } };
  return <Modal title="Google Maps Platform Settings" eyebrow="Places API (New)" onClose={onClose} width="max-w-4xl"><div className="space-y-6 p-6">
    <div className="grid gap-3 md:grid-cols-4"><Detail label="API" value={settings.api} /><Detail label="API Key" value={humanize(settings.api_key_status)} /><Detail label="Country / Language" value={`${settings.country} / ${settings.language_code}`} /><Detail label="Search Strategy" value={humanize(settings.search_strategy)} /></div>
    <div className="rounded-xl border border-slate-200 p-4"><div className="grid gap-4 md:grid-cols-5"><label className="text-[10px] font-bold uppercase text-slate-500">Request delay (ms)<input type="number" min={0} className={`${inputClass} mt-1`} value={draft.request_delay_ms} onChange={(event) => setDraft({ ...draft, request_delay_ms: Number(event.target.value) })} /></label><label className="text-[10px] font-bold uppercase text-slate-500">Maximum retry<input type="number" min={0} max={10} className={`${inputClass} mt-1`} value={draft.maximum_retry} onChange={(event) => setDraft({ ...draft, maximum_retry: Number(event.target.value) })} /></label><label className="text-[10px] font-bold uppercase text-slate-500">Timeout seconds<input type="number" min={1} className={`${inputClass} mt-1`} value={draft.timeout_seconds} onChange={(event) => setDraft({ ...draft, timeout_seconds: Number(event.target.value) })} /></label><label className="text-[10px] font-bold uppercase text-slate-500">Duplicate radius (m)<input type="number" min={10} className={`${inputClass} mt-1`} value={draft.duplicate_radius_meters} onChange={(event) => setDraft({ ...draft, duplicate_radius_meters: Number(event.target.value) })} /></label><label className="text-[10px] font-bold uppercase text-slate-500">Name threshold<input type="number" min={0} max={1} step={0.01} className={`${inputClass} mt-1`} value={draft.name_similarity_threshold} onChange={(event) => setDraft({ ...draft, name_similarity_threshold: Number(event.target.value) })} /></label></div><div className="mt-4 flex justify-end gap-2"><button disabled={busy || settings.api_key_status !== "CONFIGURED"} onClick={() => void test()} className={buttonSecondary}><Gauge size={13} />Test Connection</button><button disabled={busy} onClick={() => void saveSettings()} className={buttonPrimary}>Save Settings</button></div><p className="mt-3 text-[10px] text-slate-400">API key tetap backend-only dan tidak pernah ditampilkan. Konfigurasikan secret melalui Settings → Geocoding.</p></div>
    <div className="rounded-xl border border-slate-200"><div className="flex items-center justify-between border-b border-slate-200 p-4"><div><div className="eyebrow">Discovery Keywords</div><h3 className="mt-1 font-serif text-xl">Keyword Settings</h3></div><div className="flex gap-2"><input className={inputClass} placeholder="New keyword" value={newKeyword} onChange={(event) => setNewKeyword(event.target.value)} /><button onClick={() => void addKeyword()} className={buttonPrimary}><Plus size={13} />Add</button></div></div><div className="scroll-table max-h-80"><table className="data-table"><thead className="sticky top-0 bg-white"><tr><th>Keyword</th><th>Active</th><th>Sort Order</th><th>Action</th></tr></thead><tbody>{keywords.map((row) => <tr key={row.id}><td className="font-bold">{row.keyword}</td><td><button onClick={() => void updateKeyword(row, { is_active: !row.is_active })}><Badge value={row.is_active ? "ACTIVE" : "INACTIVE"} /></button></td><td><input aria-label={`Sort order ${row.keyword}`} type="number" min={0} className="h-8 w-20 rounded-lg border border-slate-200 px-2 text-xs" defaultValue={row.sort_order} onBlur={(event) => Number(event.target.value) !== row.sort_order && void updateKeyword(row, { sort_order: Number(event.target.value) })} /></td><td><button title="Deactivate" onClick={() => void protectedFetch(`discovery/keywords/${row.id}`, "DELETE").then(onSaved).catch((reason) => setError(reason.message))} className="rounded-lg p-2 text-red-500 hover:bg-red-50"><Trash2 size={14} /></button></td></tr>)}</tbody></table></div></div>
    <div className="flex justify-end"><button onClick={onClose} className={buttonSecondary}>Close</button></div>
  </div></Modal>;
}
