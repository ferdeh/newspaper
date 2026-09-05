"use client";

import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, formatDate, humanize } from "@/lib/api";
import type { Incident } from "@/types";
import { SortableHeader, TablePagination, TableToolbar, useDataTable } from "./DataTableControls";
import GlobalFilters, { FilterValues } from "./GlobalFilters";
import PageHeader from "./PageHeader";

function incidentSearchText(item: Incident) {
  return [
    item.incident_code, item.date, item.location, item.province, item.regency,
    item.category, item.event, item.products.join(" "), item.risk, item.severity,
    item.news_count, item.tiktok_count, item.trend, item.status, item.nearest_terminal,
  ].join(" ");
}

function incidentSortValue(item: Incident, key: string) {
  const values: Record<string, string | number | undefined> = {
    incident: item.incident_code,
    date: Date.parse(item.date),
    location: `${item.location} ${item.province ?? ""}`,
    category: `${item.category} ${item.event}`,
    product: item.products.join(" "),
    risk: item.risk,
    news: item.news_count,
    tiktok: item.tiktok_count,
    trend: item.trend,
    status: item.status,
    tbbm: item.nearest_terminal,
  };
  return values[key];
}

export default function IncidentsTable() {
  const [items, setItems] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState<FilterValues>({});
  const table = useDataTable({
    rows: items,
    searchText: incidentSearchText,
    sortValue: incidentSortValue,
    initialSortKey: "date",
    initialSortDirection: "desc",
  });

  const load = (next = filters) => {
    setLoading(true);
    setError("");
    const query = new URLSearchParams(Object.entries(next).filter(([, value]) => value));
    apiFetch<{items: Incident[]}>(`/incidents?${query}`)
      .then((data) => setItems(data.items))
      .catch((reason) => setError(reason.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => load({}), []); // eslint-disable-line react-hooks/exhaustive-deps
  const apply = (next: FilterValues) => { setFilters(next); load(next); };
  const headerProps = { sortKey: table.sortKey, sortDirection: table.sortDirection, onSort: table.toggleSort };

  return <div className="px-5 pb-10 pt-5 md:px-8 lg:px-10 lg:pt-6">
    <PageHeader eyebrow="Incident operations" title="Incident register" description="One real-world incident can contain many News and TikTok signals. Filtered results are resolved server-side against incident fields." action={<button onClick={() => load()} className="flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-bold"><RefreshCw size={14}/>Refresh</button>}/>
    <GlobalFilters onApply={apply}/>
    <div className="panel overflow-hidden">
      <div className="flex flex-col gap-4 border-b border-slate-200 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div><span className="text-sm font-bold">Corroborated incidents</span><span className="ml-2 text-xs text-slate-400">{table.filteredCount === table.totalCount ? `${table.totalCount} records` : `${table.filteredCount} dari ${table.totalCount} records`}</span></div>
        <TableToolbar search={table.search} onSearchChange={table.setSearch} pageSize={table.pageSize} onPageSizeChange={table.setPageSize} placeholder="Cari incident…"/>
      </div>
      {error ? <div className="p-10 text-center text-sm text-red-600">{error}</div> : loading ? <div className="space-y-3 p-5">{Array.from({length:6}).map((_, index) => <div key={index} className="skeleton h-10"/>)}</div> : items.length === 0 ? <div className="p-12 text-center"><p className="font-serif text-xl">No incidents match this view</p><p className="mt-2 text-sm text-slate-400">Reset filters to return to the national picture.</p></div> : table.filteredCount === 0 ? <div className="p-12 text-center text-slate-400">Tidak ada incident yang cocok dengan pencarian “{table.search}”.</div> : <>
        <div className="scroll-table"><table className="data-table"><thead><tr>
          <SortableHeader column="incident" label="Incident ID" {...headerProps}/>
          <SortableHeader column="date" label="Date" {...headerProps}/>
          <SortableHeader column="location" label="Location" {...headerProps}/>
          <SortableHeader column="category" label="Category / Event" {...headerProps}/>
          <SortableHeader column="product" label="Product" {...headerProps}/>
          <SortableHeader column="risk" label="Risk" {...headerProps}/>
          <SortableHeader column="news" label="News" {...headerProps}/>
          <SortableHeader column="tiktok" label="TikTok" {...headerProps}/>
          <SortableHeader column="trend" label="Trend" {...headerProps}/>
          <SortableHeader column="status" label="Status" {...headerProps}/>
          <SortableHeader column="tbbm" label="TBBM" {...headerProps}/>
        </tr></thead><tbody>{table.pageRows.map((item) => <tr key={item.id}>
          <td><Link href={`/incidents/${item.id}`} className="font-bold text-petrol hover:underline">{item.incident_code}</Link></td>
          <td className="whitespace-nowrap text-slate-500">{formatDate(item.date)}</td>
          <td><div className="font-bold">{item.location}</div><div className="mt-1 text-[10px] text-slate-400">{item.province}</div></td>
          <td><div className="text-[10px] font-bold text-slate-400">{humanize(item.category)}</div><div className="mt-1 font-bold">{humanize(item.event)}</div></td>
          <td>{item.products.join(", ")}</td>
          <td><span className={`risk-badge risk-${item.severity}`}>{Math.round(item.risk)} {item.severity}</span></td>
          <td>{item.news_count}</td><td>{item.tiktok_count}</td>
          <td className="text-[10px] font-bold">{humanize(item.trend)}</td>
          <td><span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-bold">{item.status}</span></td>
          <td><div className="max-w-36 text-xs">{item.nearest_terminal || "—"}</div><div className="mt-1 text-[9px] text-slate-400">Nearest exposure</div></td>
        </tr>)}</tbody></table></div>
        <TablePagination page={table.page} pageCount={table.pageCount} firstRow={table.firstRow} lastRow={table.lastRow} filteredCount={table.filteredCount} totalCount={table.totalCount} onPageChange={table.setPage}/>
      </>}
    </div>
  </div>;
}
