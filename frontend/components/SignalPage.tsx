"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch, formatDate, humanize } from "@/lib/api";
import PageHeader from "./PageHeader";

type NewsRow={id:number;published_at:string;source:string;title:string;url:string;relevance:number;event?:string;location?:string;incident_id?:number;incident_code?:string;demo:boolean};
type TikTokRow={id:number;published_at:string;creator:string;caption:string;hashtags:string[];views:number;url:string;event?:string;location?:string;confidence?:number;incident_id?:number;incident_code?:string;demo:boolean};

export default function SignalPage({type,embedded=false}:{type:"news"|"tiktok";embedded?:boolean}){
  const [rows,setRows]=useState<(NewsRow|TikTokRow)[]>([]);const [loading,setLoading]=useState(true);const [error,setError]=useState("");
  useEffect(()=>{apiFetch<{items:(NewsRow|TikTokRow)[]}>(`/${type}`).then(x=>setRows(x.items)).catch(x=>setError(x.message)).finally(()=>setLoading(false));},[type]);
  const news=type==="news";
  return <div className={embedded?"":"px-5 pb-10 pt-5 md:px-8 lg:px-10 lg:pt-6"}>{!embedded&&<PageHeader eyebrow={news?"Corroboration layer":"Early signal layer"} title={news?"News intelligence":"TikTok public signals"} description={news?"Live RSS reporting and clearly labelled demo evidence, cleaned and classified through the same incident pipeline.":"Public post metadata is retained as early evidence only. No video is downloaded or embedded."}/>}
    {!news&&<div className="mb-5 rounded-xl border border-pink-200 bg-pink-50 p-3 text-xs text-pink-900">TikTok content is an unverified early signal. Confidence and cross-source corroboration determine whether it supports an incident.</div>}
    <div className="panel overflow-hidden">{error?<div className="p-8 text-red-600">{error}</div>:loading?<div className="space-y-3 p-5">{Array.from({length:8}).map((_,i)=><div key={i} className="skeleton h-10"/>)}</div>:rows.length===0?<div className="p-12 text-center text-slate-400">No signals in this view.</div>:<div className="scroll-table"><table className="data-table"><thead><tr><th>Published</th><th>{news?"Source":"Creator"}</th><th>{news?"Title":"Caption"}</th>{!news&&<th>Reach</th>}<th>Classification</th><th>Location</th><th>Confidence</th><th>Incident</th><th>Origin</th></tr></thead><tbody>{rows.map((row)=><tr key={row.id}><td className="whitespace-nowrap text-slate-500">{formatDate(row.published_at,true)}</td><td><div className="font-bold">{news?(row as NewsRow).source:(row as TikTokRow).creator}</div><span className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-[9px] font-black ${row.demo?"bg-amber-50 text-amber-700":"bg-emerald-50 text-emerald-700"}`}>{row.demo?"DEMO":"LIVE"}</span></td><td><div className="max-w-xl text-xs font-bold">{news?(row as NewsRow).title:(row as TikTokRow).caption}</div>{!news&&<div className="mt-1 text-[9px] text-slate-400">{(row as TikTokRow).hashtags.map(x=>`#${x}`).join(" ")}</div>}</td>{!news&&<td>{(row as TikTokRow).views.toLocaleString("id-ID")} views</td>}<td>{row.event?<span className="rounded-md bg-slate-100 px-2 py-1 text-[10px] font-bold">{humanize(row.event)}</span>:"—"}</td><td>{row.location||"Unresolved"}</td><td>{Math.round(((news?(row as NewsRow).relevance:(row as TikTokRow).confidence)||0)*100)}%</td><td>{row.incident_id?<Link className="font-bold text-petrol" href={`/incidents/${row.incident_id}`}>{row.incident_code}</Link>:<span className="text-slate-300">Not linked</span>}</td><td><a href={row.url} target="_blank" rel="noreferrer" aria-label="Open original signal" className="text-petrol"><ExternalLink size={14}/></a></td></tr>)}</tbody></table></div>}</div>
  </div>;
}
