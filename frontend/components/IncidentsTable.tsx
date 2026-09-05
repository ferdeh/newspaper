"use client";

import { ArrowUpDown, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { apiFetch, formatDate, humanize } from "@/lib/api";
import type { Incident } from "@/types";
import GlobalFilters, { FilterValues } from "./GlobalFilters";
import PageHeader from "./PageHeader";

export default function IncidentsTable() {
  const [items, setItems] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<"date"|"risk">("date");
  const [filters, setFilters] = useState<FilterValues>({});
  const load = (next = filters) => {
    setLoading(true); setError("");
    const query = new URLSearchParams(Object.entries(next).filter(([,value]) => value));
    apiFetch<{items: Incident[]}>(`/incidents?${query}`).then((data) => setItems(data.items)).catch((reason)=>setError(reason.message)).finally(()=>setLoading(false));
  };
  useEffect(()=>load({}), []);
  const sorted = useMemo(()=>[...items].sort((a,b)=>sort === "risk" ? b.risk-a.risk : +new Date(b.date)-+new Date(a.date)), [items,sort]);
  const apply = (next: FilterValues) => { setFilters(next); load(next); };
  return <div className="px-5 pb-10 pt-5 md:px-8 lg:px-10 lg:pt-6">
    <PageHeader eyebrow="Incident operations" title="Incident register" description="One real-world incident can contain many News and TikTok signals. Filtered results are resolved server-side against incident fields." action={<button onClick={()=>load()} className="flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-bold"><RefreshCw size={14}/>Refresh</button>}/>
    <GlobalFilters onApply={apply}/>
    <div className="panel overflow-hidden"><div className="flex items-center justify-between border-b border-slate-200 px-5 py-4"><div><span className="text-sm font-bold">Corroborated incidents</span><span className="ml-2 text-xs text-slate-400">{items.length} records</span></div><div className="flex gap-1"><button onClick={()=>setSort("date")} className={`rounded-lg px-2.5 py-1.5 text-[10px] font-bold ${sort==="date"?"bg-ink text-white":"bg-slate-100"}`}><ArrowUpDown size={11} className="mr-1 inline"/>Date</button><button onClick={()=>setSort("risk")} className={`rounded-lg px-2.5 py-1.5 text-[10px] font-bold ${sort==="risk"?"bg-ink text-white":"bg-slate-100"}`}>Risk</button></div></div>
      {error ? <div className="p-10 text-center text-sm text-red-600">{error}</div> : loading ? <div className="space-y-3 p-5">{Array.from({length:6}).map((_,i)=><div key={i} className="skeleton h-10"/>)}</div> : sorted.length === 0 ? <div className="p-12 text-center"><p className="font-serif text-xl">No incidents match this view</p><p className="mt-2 text-sm text-slate-400">Reset filters to return to the national picture.</p></div> : <div className="scroll-table"><table className="data-table"><thead><tr><th>Incident ID</th><th>Date</th><th>Location</th><th>Category / Event</th><th>Product</th><th>Risk</th><th>News</th><th>TikTok</th><th>Trend</th><th>Status</th><th>TBBM</th></tr></thead><tbody>{sorted.map(item=><tr key={item.id}><td><Link href={`/incidents/${item.id}`} className="font-bold text-petrol hover:underline">{item.incident_code}</Link></td><td className="whitespace-nowrap text-slate-500">{formatDate(item.date)}</td><td><div className="font-bold">{item.location}</div><div className="mt-1 text-[10px] text-slate-400">{item.province}</div></td><td><div className="text-[10px] font-bold text-slate-400">{humanize(item.category)}</div><div className="mt-1 font-bold">{humanize(item.event)}</div></td><td>{item.products.join(", ")}</td><td><span className={`risk-badge risk-${item.severity}`}>{Math.round(item.risk)} {item.severity}</span></td><td>{item.news_count}</td><td>{item.tiktok_count}</td><td className="text-[10px] font-bold">{humanize(item.trend)}</td><td><span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-bold">{item.status}</span></td><td><div className="max-w-36 text-xs">{item.nearest_terminal || "—"}</div><div className="mt-1 text-[9px] text-slate-400">Nearest exposure</div></td></tr>)}</tbody></table></div>}
    </div>
  </div>;
}
