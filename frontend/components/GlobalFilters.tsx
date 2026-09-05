"use client";

import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { FormEvent, useState } from "react";

export type FilterValues = Record<string, string>;

const initial: FilterValues = { date_from: "", date_to: "", province: "", regency: "", product: "", event: "", source: "", severity: "", terminal: "" };

export default function GlobalFilters({ onApply, compact = false }: { onApply: (filters: FilterValues) => void; compact?: boolean }) {
  const [values, setValues] = useState(initial);
  const update = (key: string, value: string) => setValues((current) => ({ ...current, [key]: value }));
  const submit = (event: FormEvent) => { event.preventDefault(); onApply(values); };
  const reset = () => { setValues(initial); onApply(initial); };
  const control = "h-9 min-w-0 rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] text-slate-600";
  return <form onSubmit={submit} className="panel mb-5 p-3"><div className="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[.1em] text-slate-500"><SlidersHorizontal size={13}/> Global intelligence filters</div><div className={`grid gap-2 ${compact ? "grid-cols-2 md:grid-cols-5" : "grid-cols-2 md:grid-cols-4 xl:grid-cols-9"}`}>
    <input aria-label="Start date" type="date" className={control} value={values.date_from} onChange={(e) => update("date_from", e.target.value)}/>
    <input aria-label="End date" type="date" className={control} value={values.date_to} onChange={(e) => update("date_to", e.target.value)}/>
    <select aria-label="Province" className={control} value={values.province} onChange={(e) => update("province", e.target.value)}><option value="">All provinces</option>{["Aceh","Kalimantan Timur","Nusa Tenggara Barat","Nusa Tenggara Timur","Sulawesi Barat","Sulawesi Selatan","Sumatera Utara"].map(x=><option key={x}>{x}</option>)}</select>
    <input aria-label="Regency" className={control} placeholder="Regency / city" value={values.regency} onChange={(e) => update("regency", e.target.value)}/>
    <select aria-label="Product" className={control} value={values.product} onChange={(e) => update("product", e.target.value)}><option value="">All products</option>{["PERTALITE","PERTAMAX","BIOSOLAR","BBM"].map(x=><option key={x}>{x}</option>)}</select>
    <select aria-label="Event type" className={control} value={values.event} onChange={(e) => update("event", e.target.value)}><option value="">All events</option>{["QUEUE","STOCK_OUT","FUEL_SHORTAGE","TANK_TRUCK_ACCIDENT","FIRE","FLOOD"].map(x=><option key={x}>{x.replaceAll("_"," ")}</option>)}</select>
    <select aria-label="Source" className={control} value={values.source} onChange={(e) => update("source", e.target.value)}><option value="">All sources</option><option>NEWS</option><option>TIKTOK</option></select>
    <select aria-label="Severity" className={control} value={values.severity} onChange={(e) => update("severity", e.target.value)}><option value="">All risk bands</option>{["CRITICAL","HIGH","WARNING","WATCH","NORMAL"].map(x=><option key={x}>{x}</option>)}</select>
    <div className="flex gap-2"><button className="h-9 flex-1 rounded-lg bg-ink px-3 text-[11px] font-bold text-white hover:bg-petrol">Apply</button><button type="button" onClick={reset} aria-label="Reset filters" className="grid h-9 w-9 place-items-center rounded-lg border border-slate-200 bg-white text-slate-500"><RotateCcw size={13}/></button></div>
  </div></form>;
}
