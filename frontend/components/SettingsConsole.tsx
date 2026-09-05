"use client";

import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, EyeOff, KeyRound, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, formatDate, humanize } from "@/lib/api";
import NewsKeywordsPanel from "./NewsKeywordsPanel";
import PageHeader from "./PageHeader";
import EmailNotificationConsole from "./EmailNotificationConsole";

const tabs = [
  "News Sources", "News Keywords", "TikTok Discovery", "Master Location", "Master SPBU",
  "Risk Parameters", "Alert Rules", "Notifications · Email", "WhatsApp", "LLM", "Geocoding", "Scheduler",
];

type AnyRow = Record<string, unknown>;
type NewsSource = {
  id: number; name: string; coverage_area: string | null; domain: string; source_type: "RSS" | "HTML" | "INTERNAL";
  feed_url: string | null; priority: number; credibility: number; fetch_frequency_minutes: number;
  active: boolean; last_success: string | null; last_error: string | null;
};
type NewsSourcePage = { items: NewsSource[]; total: number; page: number; per_page: number; pages: number };
type SourceSortKey = "name" | "coverage_area" | "domain" | "source_type" | "feed_url" | "priority" | "credibility" | "fetch_frequency_minutes" | "active" | "last_success" | "last_error";
type SourceDraft = {
  name: string; coverage_area: string; domain: string; source_type: NewsSource["source_type"]; feed_url: string;
  priority: string; credibility: string; fetch_frequency_minutes: string; active: boolean;
};

const emptySourceDraft: SourceDraft = {
  name: "", coverage_area: "", domain: "", source_type: "RSS", feed_url: "", priority: "3", credibility: "0.7",
  fetch_frequency_minutes: "120", active: true,
};

function errorDetail(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object" || !("detail" in payload)) return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) => item && typeof item === "object" && "msg" in item ? [String(item.msg)] : []);
    if (messages.length) return messages.join(" ");
  }
  return fallback;
}

export default function SettingsConsole() {
  const [tab, setTab] = useState(tabs[0]);
  const [sources, setSources] = useState<NewsSource[]>([]);
  const [queries, setQueries] = useState<AnyRow[]>([]);
  const [rules, setRules] = useState<AnyRow[]>([]);
  const [masters, setMasters] = useState<Record<string, AnyRow[]>>({});
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [sourceMode, setSourceMode] = useState<"add" | "edit" | null>(null);
  const [activeSource, setActiveSource] = useState<NewsSource | null>(null);
  const [sourceDraft, setSourceDraft] = useState<SourceDraft>({ ...emptySourceDraft });
  const [sourceBusy, setSourceBusy] = useState(false);
  const [sourceLoading, setSourceLoading] = useState(true);
  const [sourceError, setSourceError] = useState("");
  const [sourceNotice, setSourceNotice] = useState("");
  const [sourceTotal, setSourceTotal] = useState(0);
  const [sourcePage, setSourcePage] = useState(1);
  const [sourcePages, setSourcePages] = useState(1);
  const [sourcePerPage, setSourcePerPage] = useState(25);
  const [sourceSearchDraft, setSourceSearchDraft] = useState("");
  const [sourceSearch, setSourceSearch] = useState("");
  const [sourceSortBy, setSourceSortBy] = useState<SourceSortKey>("priority");
  const [sourceSortOrder, setSourceSortOrder] = useState<"asc" | "desc">("asc");
  const [credentialOpen, setCredentialOpen] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveSuccess, setSaveSuccess] = useState("");

  const loadConfig = () => apiFetch<Record<string, unknown>>("/admin/config").then(setConfig);
  const loadSources = async (options: { page?: number; perPage?: number; search?: string; sortBy?: SourceSortKey; sortOrder?: "asc" | "desc" } = {}) => {
    const nextPage = options.page ?? sourcePage;
    const nextPerPage = options.perPage ?? sourcePerPage;
    const nextSearch = options.search ?? sourceSearch;
    const nextSortBy = options.sortBy ?? sourceSortBy;
    const nextSortOrder = options.sortOrder ?? sourceSortOrder;
    const params = new URLSearchParams({
      page: String(nextPage), per_page: String(nextPerPage), sort_by: nextSortBy, sort_order: nextSortOrder,
    });
    if (nextSearch) params.set("search", nextSearch);
    setSourceLoading(true);
    try {
      const result = await apiFetch<NewsSourcePage>(`/admin/news-sources?${params}`);
      setSources(result.items); setSourceTotal(result.total); setSourcePage(result.page);
      setSourcePerPage(result.per_page); setSourcePages(Math.max(1, result.pages));
    } finally { setSourceLoading(false); }
  };

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("tab") === "notifications-email") setTab("Notifications · Email");
    Promise.all([
      apiFetch<NewsSourcePage>("/admin/news-sources?page=1&per_page=25&sort_by=priority&sort_order=asc"),
      apiFetch<AnyRow[]>("/admin/tiktok-queries"),
      apiFetch<AnyRow[]>("/admin/alert-rules"),
      apiFetch<Record<string, AnyRow[]>>("/admin/master-data"),
      apiFetch<Record<string, unknown>>("/admin/config"),
    ]).then(([nextSources, nextQueries, nextRules, nextMasters, nextConfig]) => {
      setSources(nextSources.items); setSourceTotal(nextSources.total); setSourcePage(nextSources.page);
      setSourcePerPage(nextSources.per_page); setSourcePages(Math.max(1, nextSources.pages));
      setQueries(nextQueries); setRules(nextRules); setMasters(nextMasters); setConfig(nextConfig);
    }).catch((reason) => setSourceError(reason instanceof Error ? reason.message : "Konfigurasi gagal dimuat."))
      .finally(() => setSourceLoading(false));
  }, []);

  const openAddSource = () => {
    setActiveSource(null); setSourceDraft({ ...emptySourceDraft }); setSourceError(""); setSourceMode("add");
  };

  const openEditSource = (source: NewsSource) => {
    setActiveSource(source);
    setSourceDraft({
      name: source.name, coverage_area: source.coverage_area || "", domain: source.domain,
      source_type: source.source_type, feed_url: source.feed_url || "",
      priority: String(source.priority), credibility: String(source.credibility),
      fetch_frequency_minutes: String(source.fetch_frequency_minutes), active: source.active,
    });
    setSourceError(""); setSourceMode("edit");
  };

  const closeSource = () => { setSourceMode(null); setActiveSource(null); setSourceError(""); };

  const searchSources = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextSearch = sourceSearchDraft.trim();
    setSourceSearch(nextSearch); setSourcePage(1); setSourceError("");
    void loadSources({ page: 1, search: nextSearch }).catch((reason) => setSourceError(reason instanceof Error ? reason.message : "Pencarian source gagal."));
  };

  const clearSourceSearch = () => {
    setSourceSearchDraft(""); setSourceSearch(""); setSourcePage(1); setSourceError("");
    void loadSources({ page: 1, search: "" }).catch((reason) => setSourceError(reason instanceof Error ? reason.message : "News source gagal dimuat."));
  };

  const sortSources = (sortBy: SourceSortKey) => {
    const nextOrder = sourceSortBy === sortBy && sourceSortOrder === "asc" ? "desc" : "asc";
    setSourceSortBy(sortBy); setSourceSortOrder(nextOrder); setSourcePage(1); setSourceError("");
    void loadSources({ page: 1, sortBy, sortOrder: nextOrder }).catch((reason) => setSourceError(reason instanceof Error ? reason.message : "Sorting source gagal."));
  };

  const changeSourcePage = (page: number) => {
    if (page < 1 || page > sourcePages || page === sourcePage) return;
    setSourceError("");
    void loadSources({ page }).catch((reason) => setSourceError(reason instanceof Error ? reason.message : "Halaman source gagal dimuat."));
  };

  const changeSourcePerPage = (perPage: number) => {
    setSourcePerPage(perPage); setSourcePage(1); setSourceError("");
    void loadSources({ page: 1, perPage }).catch((reason) => setSourceError(reason instanceof Error ? reason.message : "News source gagal dimuat."));
  };

  const saveSource = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSourceBusy(true); setSourceError(""); setSourceNotice("");
    const isEditing = sourceMode === "edit" && activeSource;
    try {
      const response = await fetch(isEditing ? `/settings-api/news-sources/${activeSource.id}` : "/settings-api/news-sources", {
        method: isEditing ? "PATCH" : "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({
          name: sourceDraft.name.trim(), coverage_area: sourceDraft.coverage_area.trim() || null,
          domain: sourceDraft.domain.trim().toLowerCase(), source_type: sourceDraft.source_type,
          feed_url: sourceDraft.feed_url.trim() || null, priority: Number(sourceDraft.priority),
          credibility_score: Number(sourceDraft.credibility), fetch_frequency_minutes: Number(sourceDraft.fetch_frequency_minutes),
          is_active: sourceDraft.active,
        }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorDetail(result, `API request failed (${response.status})`));
      await loadSources({ page: sourcePage });
      setSourceNotice(isEditing ? "News source berhasil diperbarui." : "News source berhasil ditambahkan.");
      closeSource();
    } catch (reason) {
      setSourceError(reason instanceof Error ? reason.message : "News source gagal disimpan.");
    } finally { setSourceBusy(false); }
  };

  const deleteSource = async (source: NewsSource) => {
    if (!window.confirm(`Hapus source ${source.name}? Source tidak akan dikoleksi lagi, tetapi histori artikel tetap disimpan.`)) return;
    setSourceBusy(true); setSourceError(""); setSourceNotice("");
    try {
      const response = await fetch(`/settings-api/news-sources/${source.id}`, { method: "DELETE", headers: { Accept: "application/json" } });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorDetail(result, `API request failed (${response.status})`));
      const targetPage = sources.length === 1 && sourcePage > 1 ? sourcePage - 1 : sourcePage;
      await loadSources({ page: targetPage });
      setSourceNotice("News source berhasil dihapus. Histori artikel tetap tersimpan.");
    } catch (reason) {
      setSourceError(reason instanceof Error ? reason.message : "News source gagal dihapus.");
    } finally { setSourceBusy(false); }
  };

  const closeCredential = () => { setCredentialOpen(false); setApiKey(""); setSaveError(""); setSaveSuccess(""); };

  const saveCredential = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setSaveError(""); setSaveSuccess(""); setSaving(true);
    try {
      const response = await fetch("/settings-api/google-maps", {
        method: "PUT", headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey }),
      });
      const result = await response.json().catch(() => null) as { detail?: string } | null;
      if (!response.ok) throw new Error(result?.detail || `API request failed (${response.status})`);
      await loadConfig(); setApiKey("");
      setSaveSuccess("API key tervalidasi dan tersimpan. Geo-worker sedang memperbarui lokasi insiden.");
    } catch (reason) {
      setSaveError(reason instanceof Error ? reason.message : "API key gagal disimpan.");
    } finally { setSaving(false); }
  };

  let rows: AnyRow[] = [];
  if (tab === "TikTok Keywords") rows = queries;
  if (tab === "Master Location") rows = masters.locations || [];
  if (tab === "Master SPBU") rows = masters.spbu || [];
  if (tab === "Alert Rules" || tab === "Risk Parameters") rows = rules;

  const provider = tab === "WhatsApp" ? config.whatsapp : tab === "LLM" ? config.llm : tab === "Geocoding" ? config.geocoding : null;
  const providerRow = (provider || {}) as AnyRow;
  const columns = rows.length ? Object.keys(rows[0]).slice(0, 8) : [];
  const sourcePageStart = sourceTotal ? (sourcePage - 1) * sourcePerPage + 1 : 0;
  const sourcePageEnd = Math.min(sourcePage * sourcePerPage, sourceTotal);
  const firstVisiblePage = Math.max(1, Math.min(sourcePage - 2, sourcePages - 4));
  const visibleSourcePages = Array.from({ length: Math.min(5, sourcePages) }, (_, index) => firstVisiblePage + index);
  const sortableHeader = (label: string, sortBy: SourceSortKey) => <th>
    <button type="button" onClick={() => sortSources(sortBy)} className="inline-flex items-center gap-1 whitespace-nowrap hover:text-ink" aria-label={`Sort by ${label}`}>
      {label}{sourceSortBy === sortBy ? sourceSortOrder === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} /> : <ArrowUpDown size={12} className="opacity-40" />}
    </button>
  </th>;

  return <div className="px-5 pb-10 pt-5 md:px-8 lg:px-10 lg:pt-6">
    <PageHeader eyebrow="Administration" title="Settings" description="Sources, adaptive queries, master data, risk policy, provider state, and configurable schedules. Secrets are never returned to the browser." />
    <div className="grid gap-5 xl:grid-cols-[220px_1fr]">
      <nav className="panel h-fit p-2">
        {tabs.map((item) => <button key={item} onClick={() => setTab(item)} className={`mb-1 block w-full rounded-lg px-3 py-2.5 text-left text-xs font-bold ${tab === item ? "bg-ink text-white" : "text-slate-500 hover:bg-slate-100"}`}>{item}</button>)}
      </nav>
      <section className="panel min-w-0 overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div><div className="eyebrow">Configuration</div><h2 className="mt-1 font-serif text-xl">{tab}</h2></div>
          {tab === "News Sources" && <button onClick={openAddSource} className="flex items-center gap-2 rounded-lg bg-ink px-3 py-2 text-[10px] font-bold text-white"><Plus size={13} />Add source</button>}
          {tab === "Geocoding" && <button onClick={() => setCredentialOpen(true)} className="flex items-center gap-2 rounded-lg bg-ink px-3 py-2 text-[10px] font-bold text-white"><KeyRound size={13} />Configure API key</button>}
        </div>
        {tab === "Notifications · Email" ? <EmailNotificationConsole /> : provider ? <div className="p-6">
          <div className="max-w-xl rounded-xl border border-slate-200 p-5">
            <div className="flex items-center justify-between">
              <div><div className="text-[10px] font-bold uppercase text-slate-400">Active provider</div><div className="mt-2 font-serif text-2xl">{humanize(String(providerRow.provider))}</div></div>
              <span className={`risk-badge ${providerRow.credential === "not configured" ? "risk-WATCH" : "risk-NORMAL"}`}>{providerRow.credential === "not configured" ? "Credential required" : "Ready"}</span>
            </div>
            <div className="mt-5 flex items-center gap-2 rounded-lg bg-slate-100 p-3 text-xs text-slate-500"><EyeOff size={15} />Credential: {String(providerRow.credential || "not required in local mode")}</div>
            {tab === "Geocoding" && <div className="mt-4 text-xs leading-5 text-slate-500">Required APIs: Geocoding API and Places API (New). Nearest TBBM is calculated locally with PostGIS. Stored values are never displayed again.{Boolean(providerRow.source) && <div className="mt-1">Credential source: {humanize(String(providerRow.source))}</div>}</div>}
          </div>
        </div> : tab === "Scheduler" ? <div className="grid gap-3 p-6 md:grid-cols-2">
          {[["Priority News", "60 minutes"], ["General News", "120 minutes"], ["TikTok due check", "1 minute · per-keyword interval"], ["Geocoding / PostGIS TBBM", "360 minutes"], ["Incident / Risk", "30 minutes"], ["Analytics Refresh", "60 minutes"], ["Daily WhatsApp Digest", "07:00 Asia/Jakarta"]].map(([name, value]) => <div key={name} className="rounded-xl border border-slate-200 p-4"><div className="text-xs font-bold">{name}</div><div className="mt-1 text-sm text-slate-500">{value}</div></div>)}
        </div> : tab === "News Sources" ? <div aria-busy={sourceLoading}>
          {(sourceNotice || sourceError) && <div className={`mx-5 mt-5 rounded-xl border p-3 text-xs ${sourceError ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{sourceError || sourceNotice}</div>}
          <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
            <form onSubmit={searchSources} className="flex w-full max-w-xl gap-2">
              <div className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={15} />
                <input aria-label="Search news sources" value={sourceSearchDraft} onChange={(event) => setSourceSearchDraft(event.target.value)} placeholder="Search name, area, domain, type, or URL" className="h-10 w-full border border-slate-300 py-2 pl-9 pr-3 text-xs" />
              </div>
              <button disabled={sourceLoading} className="rounded-xl bg-ink px-4 py-2 text-xs font-bold text-white disabled:opacity-50">Search</button>
              {(sourceSearch || sourceSearchDraft) && <button type="button" disabled={sourceLoading} onClick={clearSourceSearch} className="rounded-xl border border-slate-300 px-3 py-2 text-xs font-bold text-slate-600 disabled:opacity-50">Clear</button>}
            </form>
            <div className="flex items-center justify-between gap-3 whitespace-nowrap text-xs text-slate-500 lg:justify-end">
              <span>{sourceTotal} sources</span>
              <label className="flex items-center gap-2">Rows
                <select aria-label="Rows per page" value={sourcePerPage} onChange={(event) => changeSourcePerPage(Number(event.target.value))} className="h-9 border border-slate-300 px-2 text-xs">
                  {[10, 25, 50, 100].map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>
            </div>
          </div>
          {sources.length ? <div className={`scroll-table transition-opacity ${sourceLoading ? "opacity-55" : "opacity-100"}`}>
            <table className="data-table">
              <thead><tr>{sortableHeader("Name", "name")}{sortableHeader("Coverage Area", "coverage_area")}{sortableHeader("Domain", "domain")}{sortableHeader("Type", "source_type")}{sortableHeader("Feed URL", "feed_url")}{sortableHeader("Priority", "priority")}{sortableHeader("Credibility", "credibility")}{sortableHeader("Frequency", "fetch_frequency_minutes")}{sortableHeader("Status", "active")}{sortableHeader("Last Success", "last_success")}{sortableHeader("Last Error", "last_error")}<th>Actions</th></tr></thead>
              <tbody>{sources.map((source) => <tr key={source.id}>
                <td className="min-w-48 font-bold">{source.name}</td><td className="min-w-36">{source.coverage_area || "—"}</td><td>{source.domain}</td><td>{source.source_type}</td>
                <td><div className="max-w-64 truncate text-xs text-slate-500" title={source.feed_url || undefined}>{source.feed_url || "—"}</div></td>
                <td>{source.priority}</td><td>{Math.round(source.credibility * 100)}%</td><td className="whitespace-nowrap">{source.fetch_frequency_minutes} min</td>
                <td><span className={`risk-badge ${source.active ? "risk-NORMAL" : "risk-WATCH"}`}>{source.active ? "Active" : "Inactive"}</span></td>
                <td className="whitespace-nowrap">{source.last_success ? formatDate(source.last_success, true) : "—"}</td>
                <td><div className="max-w-60 truncate text-xs text-red-600" title={source.last_error || undefined}>{source.last_error || "—"}</div></td>
                <td><div className="flex gap-1">
                  <button disabled={sourceBusy} title="Edit source" aria-label={`Edit ${source.name}`} onClick={() => openEditSource(source)} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-50"><Pencil size={14} /></button>
                  <button disabled={sourceBusy} title="Delete source" aria-label={`Delete ${source.name}`} onClick={() => void deleteSource(source)} className="rounded-lg p-2 text-red-500 hover:bg-red-50 disabled:opacity-50"><Trash2 size={14} /></button>
                </div></td>
              </tr>)}</tbody>
            </table>
          </div> : <div className="p-12 text-center text-slate-400"><Search className="mx-auto mb-3" size={24} /><p>{sourceLoading ? "Loading news sources…" : sourceSearch ? `No sources match “${sourceSearch}”.` : "No news sources configured."}</p>{!sourceLoading && (sourceSearch ? <button onClick={clearSourceSearch} className="mt-4 rounded-xl border border-slate-300 px-4 py-2.5 text-xs font-bold text-slate-600">Clear search</button> : <button onClick={openAddSource} className="mt-4 rounded-xl bg-ink px-4 py-2.5 text-xs font-bold text-white">Add first source</button>)}</div>}
          {sourceTotal > 0 && <div className="flex flex-col gap-3 border-t border-slate-200 px-5 py-4 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between">
            <span>Showing {sourcePageStart}–{sourcePageEnd} of {sourceTotal}</span>
            <div className="flex items-center gap-1">
              <button type="button" aria-label="Previous page" disabled={sourceLoading || sourcePage <= 1} onClick={() => changeSourcePage(sourcePage - 1)} className="grid h-8 w-8 place-items-center rounded-lg border border-slate-300 disabled:opacity-40"><ChevronLeft size={14} /></button>
              {visibleSourcePages.map((pageNumber) => <button type="button" key={pageNumber} disabled={sourceLoading} onClick={() => changeSourcePage(pageNumber)} aria-current={pageNumber === sourcePage ? "page" : undefined} className={`grid h-8 min-w-8 place-items-center rounded-lg border px-2 font-bold ${pageNumber === sourcePage ? "border-ink bg-ink text-white" : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"}`}>{pageNumber}</button>)}
              <button type="button" aria-label="Next page" disabled={sourceLoading || sourcePage >= sourcePages} onClick={() => changeSourcePage(sourcePage + 1)} className="grid h-8 w-8 place-items-center rounded-lg border border-slate-300 disabled:opacity-40"><ChevronRight size={14} /></button>
            </div>
          </div>}
        </div> : tab === "News Keywords" ? <NewsKeywordsPanel /> : tab === "TikTok Discovery" ? <div className="p-6"><div className="max-w-2xl rounded-xl border border-slate-200 p-5"><div className="eyebrow">Integrated source</div><h3 className="mt-2 font-serif text-xl">TikTok Discovery Settings</h3><p className="mt-3 text-xs leading-5 text-slate-500">Konfigurasi ScrapeCreators API key, schedule, transcript enrichment, credit guard, keyword, manual search, dan audit run tersedia dalam modul TikTok Discovery.</p><Link href="/tiktok-discovery/settings" className="mt-5 inline-flex rounded-lg bg-ink px-4 py-2.5 text-xs font-bold text-white">Open TikTok Discovery Settings</Link></div></div> : rows.length ? <div className="scroll-table">
          <table className="data-table"><thead><tr>{columns.map((key) => <th key={key}>{humanize(key)}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((key) => <td key={key}>{typeof row[key] === "boolean" ? <span className={`risk-badge ${row[key] ? "risk-NORMAL" : "risk-WATCH"}`}>{String(row[key])}</span> : humanize(String(row[key] ?? "—"))}</td>)}</tr>)}</tbody></table>
        </div> : <div className="p-12 text-center text-slate-400"><Search className="mx-auto mb-3" size={24} /><p>No configuration rows in this view.</p></div>}
      </section>
    </div>

    {sourceMode && <div className="fixed inset-0 z-[1000] grid place-items-center overflow-y-auto bg-slate-950/45 p-4" role="dialog" aria-modal="true" aria-labelledby="source-form-title">
      <form onSubmit={saveSource} className="my-6 w-full max-w-2xl rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-200 px-6 py-5">
          <div><div className="eyebrow">News source</div><h2 id="source-form-title" className="mt-1 font-serif text-2xl">{sourceMode === "add" ? "Add source" : "Edit source"}</h2></div>
          <button type="button" onClick={closeSource} aria-label="Close source form" className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X size={18} /></button>
        </div>
        <div className="grid gap-4 p-6 md:grid-cols-2">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Source name
            <input autoFocus required minLength={2} maxLength={160} value={sourceDraft.name} onChange={(event) => setSourceDraft((current) => ({ ...current, name: event.target.value }))} placeholder="ANTARA News" className="mt-2 w-full border border-slate-300 px-3 py-3 text-sm normal-case tracking-normal" />
          </label>
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Coverage area
            <input maxLength={255} value={sourceDraft.coverage_area} onChange={(event) => setSourceDraft((current) => ({ ...current, coverage_area: event.target.value }))} placeholder="Sumatera Utara" className="mt-2 w-full border border-slate-300 px-3 py-3 text-sm normal-case tracking-normal" />
          </label>
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Domain
            <input required minLength={3} maxLength={255} value={sourceDraft.domain} onChange={(event) => setSourceDraft((current) => ({ ...current, domain: event.target.value }))} placeholder="antaranews.com" className="mt-2 w-full border border-slate-300 px-3 py-3 text-sm normal-case tracking-normal" />
            <span className="mt-1 block text-[10px] font-normal normal-case tracking-normal text-slate-400">Tanpa https:// dan path.</span>
          </label>
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Source type
            <select value={sourceDraft.source_type} onChange={(event) => setSourceDraft((current) => ({ ...current, source_type: event.target.value as NewsSource["source_type"] }))} className="mt-2 w-full border border-slate-300 px-3 py-3 text-sm normal-case tracking-normal">
              <option value="RSS">RSS / Atom</option><option value="HTML">HTML page</option>{sourceDraft.source_type === "INTERNAL" && <option value="INTERNAL">Internal ingestion</option>}
            </select>
          </label>
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Feed URL
            <input type="url" required={sourceDraft.source_type !== "INTERNAL" && sourceDraft.active} value={sourceDraft.feed_url} onChange={(event) => setSourceDraft((current) => ({ ...current, feed_url: event.target.value }))} placeholder="https://example.com/rss.xml" className="mt-2 w-full border border-slate-300 px-3 py-3 text-sm normal-case tracking-normal" />
          </label>
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Priority
            <input type="number" required min={1} max={5} value={sourceDraft.priority} onChange={(event) => setSourceDraft((current) => ({ ...current, priority: event.target.value }))} className="mt-2 w-full border border-slate-300 px-3 py-3 text-sm normal-case tracking-normal" />
            <span className="mt-1 block text-[10px] font-normal normal-case tracking-normal text-slate-400">1 paling tinggi, 5 paling rendah.</span>
          </label>
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Credibility score
            <input type="number" required min={0} max={1} step={0.05} value={sourceDraft.credibility} onChange={(event) => setSourceDraft((current) => ({ ...current, credibility: event.target.value }))} className="mt-2 w-full border border-slate-300 px-3 py-3 text-sm normal-case tracking-normal" />
          </label>
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Fetch frequency (minutes)
            <input type="number" required min={5} max={10080} value={sourceDraft.fetch_frequency_minutes} onChange={(event) => setSourceDraft((current) => ({ ...current, fetch_frequency_minutes: event.target.value }))} className="mt-2 w-full border border-slate-300 px-3 py-3 text-sm normal-case tracking-normal" />
          </label>
          <label className="flex items-center gap-3 self-end rounded-xl border border-slate-200 px-4 py-3 text-xs font-bold text-slate-600">
            <input type="checkbox" checked={sourceDraft.active} onChange={(event) => setSourceDraft((current) => ({ ...current, active: event.target.checked }))} className="h-4 w-4" />Active and included in collection
          </label>
          {sourceError && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-700 md:col-span-2">{sourceError}</div>}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4">
          <button type="button" disabled={sourceBusy} onClick={closeSource} className="rounded-xl border border-slate-300 px-4 py-2.5 text-xs font-bold text-slate-600 disabled:opacity-50">Cancel</button>
          <button disabled={sourceBusy} className="flex items-center gap-2 rounded-xl bg-ink px-4 py-2.5 text-xs font-bold text-white disabled:opacity-50"><Plus size={14} />{sourceBusy ? "Saving…" : sourceMode === "add" ? "Add source" : "Save changes"}</button>
        </div>
      </form>
    </div>}

    {credentialOpen && <div className="fixed inset-0 z-[1000] grid place-items-center bg-slate-950/45 p-4" role="dialog" aria-modal="true" aria-labelledby="google-key-title">
      <form onSubmit={saveCredential} className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-start justify-between"><div><div className="eyebrow">Secure credential</div><h2 id="google-key-title" className="mt-1 font-serif text-2xl">Google Maps API key</h2></div><button type="button" onClick={closeCredential} aria-label="Close credential form" className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X size={18} /></button></div>
        <p className="mt-3 text-xs leading-5 text-slate-500">Masukkan Google API key untuk Geocoding dan Places Discovery. UI akan menguji koneksi Geocoding sebelum menyimpannya; koneksi Places dapat diuji dari Master Data → TBBM. Nilainya tidak pernah ditampilkan kembali.</p>
        <label className="mt-5 block text-[10px] font-bold uppercase tracking-wider text-slate-500" htmlFor="google-api-key">Google Maps API key</label>
        <input id="google-api-key" type="password" autoComplete="new-password" required minLength={20} value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Paste API key" className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-3 text-sm" />
        {saveError && <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-700">{saveError}</div>}
        {saveSuccess && <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs leading-5 text-emerald-800">{saveSuccess}</div>}
        <div className="mt-6 flex justify-end gap-2"><button type="button" onClick={closeCredential} className="rounded-xl border border-slate-300 px-4 py-2.5 text-xs font-bold text-slate-600">{saveSuccess ? "Close" : "Cancel"}</button>{!saveSuccess && <button disabled={saving} className="flex items-center gap-2 rounded-xl bg-ink px-4 py-2.5 text-xs font-bold text-white disabled:opacity-50"><Plus size={14} />{saving ? "Testing connection…" : "Test connection & save"}</button>}</div>
      </form>
    </div>}
  </div>;
}
