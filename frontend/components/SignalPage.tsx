"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, formatDate, humanize } from "@/lib/api";
import { SortableHeader, TablePagination, TableToolbar, useDataTable } from "./DataTableControls";
import PageHeader from "./PageHeader";

type NewsRow = {id:number;published_at:string;source:string;title:string;url:string;relevance:number;event?:string;location?:string;incident_id?:number;incident_code?:string;demo:boolean};
type TikTokRow = {id:number;published_at:string;creator:string;caption:string;hashtags:string[];views:number;url:string;event?:string;location?:string;confidence?:number;incident_id?:number;incident_code?:string;demo:boolean};
type SignalRow = NewsRow | TikTokRow;

function isNewsRow(row: SignalRow): row is NewsRow {
  return "source" in row;
}

function sourceName(row: SignalRow) {
  return isNewsRow(row) ? row.source : row.creator;
}

function signalText(row: SignalRow) {
  return isNewsRow(row) ? row.title : `${row.caption} ${row.hashtags.join(" ")}`;
}

function confidence(row: SignalRow) {
  return isNewsRow(row) ? row.relevance : row.confidence ?? 0;
}

function signalSearchText(row: SignalRow) {
  return [row.published_at, sourceName(row), signalText(row), isNewsRow(row) ? "" : row.views, row.event, row.location, confidence(row), row.incident_code, row.demo ? "DEMO" : "LIVE", row.url].join(" ");
}

function signalSortValue(row: SignalRow, key: string) {
  const values: Record<string, string | number | undefined> = {
    published: Date.parse(row.published_at),
    source: sourceName(row),
    content: signalText(row),
    reach: isNewsRow(row) ? 0 : row.views,
    classification: row.event,
    location: row.location,
    confidence: confidence(row),
    incident: row.incident_code,
    origin: row.url,
  };
  return values[key];
}

export default function SignalPage({type, embedded = false}:{type:"news"|"tiktok";embedded?:boolean}) {
  const [rows, setRows] = useState<SignalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const news = type === "news";
  const table = useDataTable({
    rows,
    searchText: signalSearchText,
    sortValue: signalSortValue,
    initialSortKey: "published",
    initialSortDirection: "desc",
  });

  useEffect(() => {
    apiFetch<{items:SignalRow[]}>(`/${type}`)
      .then((response) => setRows(response.items))
      .catch((reason) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [type]);

  const headerProps = { sortKey: table.sortKey, sortDirection: table.sortDirection, onSort: table.toggleSort };
  const title = news ? "News intelligence" : "TikTok public signals";

  return <div className={embedded ? "" : "px-5 pb-10 pt-5 md:px-8 lg:px-10 lg:pt-6"}>
    {!embedded && <PageHeader
      eyebrow={news ? "Corroboration layer" : "Early signal layer"}
      title={title}
      description={news ? "Live RSS reporting and clearly labelled demo evidence, cleaned and classified through the same incident pipeline." : "Public post metadata is retained as early evidence only. No video is downloaded or embedded."}
    />}
    {!news && <div className="mb-5 rounded-xl border border-pink-200 bg-pink-50 p-3 text-xs text-pink-900">TikTok content is an unverified early signal. Confidence and cross-source corroboration determine whether it supports an incident.</div>}
    <div className="panel overflow-hidden">
      <div className="flex flex-col gap-4 border-b border-slate-200 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div><span className="font-serif text-lg">{title}</span><span className="ml-2 text-xs text-slate-400">{table.filteredCount === table.totalCount ? `${table.totalCount} records` : `${table.filteredCount} dari ${table.totalCount} records`}</span></div>
        <TableToolbar search={table.search} onSearchChange={table.setSearch} pageSize={table.pageSize} onPageSizeChange={table.setPageSize} placeholder={news ? "Cari news intelligence…" : "Cari TikTok public signals…"}/>
      </div>
      {error ? <div className="p-8 text-red-600">{error}</div> : loading ? <div className="space-y-3 p-5">{Array.from({length:8}).map((_, index) => <div key={index} className="skeleton h-10"/>)}</div> : rows.length === 0 ? <div className="p-12 text-center text-slate-400">No signals in this view.</div> : table.filteredCount === 0 ? <div className="p-12 text-center text-slate-400">Tidak ada signal yang cocok dengan pencarian “{table.search}”.</div> : <>
        <div className="scroll-table"><table className="data-table"><thead><tr>
          <SortableHeader column="published" label="Published" {...headerProps}/>
          <SortableHeader column="source" label={news ? "Source" : "Creator"} {...headerProps}/>
          <SortableHeader column="content" label={news ? "Title" : "Caption"} {...headerProps}/>
          {!news && (
            <SortableHeader column="reach" label="Reach" {...headerProps}/>
          )}
          <SortableHeader column="classification" label="Classification" {...headerProps}/>
          <SortableHeader column="location" label="Location" {...headerProps}/>
          <SortableHeader column="confidence" label="Confidence" {...headerProps}/>
          <SortableHeader column="incident" label="Incident" {...headerProps}/>
          <SortableHeader column="origin" label="Origin" {...headerProps}/>
        </tr></thead><tbody>{table.pageRows.map((row) => <tr key={row.id}>
          <td className="whitespace-nowrap text-slate-500">{formatDate(row.published_at, true)}</td>
          <td><div className="font-bold">{sourceName(row)}</div><span className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-[9px] font-black ${row.demo ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700"}`}>{row.demo ? "DEMO" : "LIVE"}</span></td>
          <td><div className="max-w-xl text-xs font-bold">{isNewsRow(row) ? row.title : row.caption}</div>{!isNewsRow(row) && <div className="mt-1 text-[9px] text-slate-400">{row.hashtags.map((tag) => `#${tag}`).join(" ")}</div>}</td>
          {!news && <td>{!isNewsRow(row) ? row.views.toLocaleString("id-ID") : 0} views</td>}
          <td>{row.event ? <span className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-bold">{humanize(row.event)}</span> : "—"}</td>
          <td>{row.location || "Unresolved"}</td>
          <td>{Math.round(confidence(row) * 100)}%</td>
          <td>{row.incident_id ? <Link className="font-bold text-petrol" href={`/incidents/${row.incident_id}`}>{row.incident_code}</Link> : <span className="text-slate-300">Not linked</span>}</td>
          <td><a href={row.url} target="_blank" rel="noreferrer" aria-label="Open original signal" className="text-petrol"><ExternalLink size={14}/></a></td>
        </tr>)}</tbody></table></div>
        <TablePagination page={table.page} pageCount={table.pageCount} firstRow={table.firstRow} lastRow={table.lastRow} filteredCount={table.filteredCount} totalCount={table.totalCount} onPageChange={table.setPage}/>
      </>}
    </div>
  </div>;
}
