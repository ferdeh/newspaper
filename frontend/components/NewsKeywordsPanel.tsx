"use client";

import { Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { apiFetch, formatDate } from "@/lib/api";

type NewsKeyword = {
  id: number;
  keyword: string;
  active: boolean;
  created_at: string;
  updated_at: string;
};

type KeywordDraft = { keyword: string; active: boolean };

const emptyDraft: KeywordDraft = { keyword: "", active: true };

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

export default function NewsKeywordsPanel() {
  const [keywords, setKeywords] = useState<NewsKeyword[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [mode, setMode] = useState<"add" | "edit" | null>(null);
  const [activeKeyword, setActiveKeyword] = useState<NewsKeyword | null>(null);
  const [draft, setDraft] = useState<KeywordDraft>({ ...emptyDraft });

  const loadKeywords = async () => {
    setLoading(true);
    try {
      setKeywords(await apiFetch<NewsKeyword[]>("/admin/news-keywords"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadKeywords().catch((reason) => setError(reason instanceof Error ? reason.message : "News keyword gagal dimuat."));
  }, []);

  const openAdd = () => {
    setActiveKeyword(null);
    setDraft({ ...emptyDraft });
    setError("");
    setMode("add");
  };

  const openEdit = (keyword: NewsKeyword) => {
    setActiveKeyword(keyword);
    setDraft({ keyword: keyword.keyword, active: keyword.active });
    setError("");
    setMode("edit");
  };

  const closeForm = () => {
    setMode(null);
    setActiveKeyword(null);
    setError("");
  };

  const saveKeyword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    const isEditing = mode === "edit" && activeKeyword;
    try {
      const response = await fetch(isEditing ? `/settings-api/news-keywords/${activeKeyword.id}` : "/settings-api/news-keywords", {
        method: isEditing ? "PATCH" : "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ keyword: draft.keyword.trim(), is_active: draft.active }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorDetail(result, `API request failed (${response.status})`));
      await loadKeywords();
      setNotice(isEditing ? "News keyword berhasil diperbarui." : "News keyword berhasil ditambahkan.");
      closeForm();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "News keyword gagal disimpan.");
    } finally {
      setBusy(false);
    }
  };

  const deleteKeyword = async (keyword: NewsKeyword) => {
    if (!window.confirm(`Hapus keyword “${keyword.keyword}”? Berita lama tetap tersimpan, tetapi keyword tidak digunakan lagi pada koleksi berikutnya.`)) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(`/settings-api/news-keywords/${keyword.id}`, { method: "DELETE", headers: { Accept: "application/json" } });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorDetail(result, `API request failed (${response.status})`));
      await loadKeywords();
      setNotice("News keyword berhasil dihapus. Berita yang sudah tersimpan tidak berubah.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "News keyword gagal dihapus.");
    } finally {
      setBusy(false);
    }
  };

  const activeCount = keywords.filter((keyword) => keyword.active).length;

  return <div aria-busy={loading}>
    {(notice || error) && <div className={`mx-5 mt-5 rounded-xl border p-3 text-xs ${error ? "border-red-200 bg-red-50 text-red-700" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>{error || notice}</div>}
    <div className="flex flex-col gap-4 border-b border-slate-200 px-5 py-5 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="max-w-3xl text-xs leading-5 text-slate-500">Keyword aktif dicocokkan dengan judul dan isi kandidat dari seluruh News Sources aktif. Perubahan berlaku mulai koleksi berikutnya.</p>
        <div className="mt-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">{keywords.length} keyword · {activeCount} active</div>
      </div>
      <button type="button" onClick={openAdd} className="flex shrink-0 items-center justify-center gap-2 rounded-lg bg-ink px-3 py-2.5 text-[10px] font-bold text-white"><Plus size={13} />Add keyword</button>
    </div>
    {loading ? <div className="space-y-3 p-5">{Array.from({ length: 4 }).map((_, index) => <div key={index} className="skeleton h-10" />)}</div> : keywords.length ? <div className="scroll-table">
      <table className="data-table">
        <thead><tr><th>Keyword</th><th>Status</th><th>Last Updated</th><th>Actions</th></tr></thead>
        <tbody>{keywords.map((keyword) => <tr key={keyword.id}>
          <td className="min-w-72 font-bold">{keyword.keyword}</td>
          <td><span className={`risk-badge ${keyword.active ? "risk-NORMAL" : "risk-WATCH"}`}>{keyword.active ? "Active" : "Inactive"}</span></td>
          <td className="whitespace-nowrap text-slate-500">{formatDate(keyword.updated_at, true)}</td>
          <td><div className="flex gap-1">
            <button type="button" disabled={busy} title="Edit keyword" aria-label={`Edit ${keyword.keyword}`} onClick={() => openEdit(keyword)} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-50"><Pencil size={14} /></button>
            <button type="button" disabled={busy} title="Delete keyword" aria-label={`Delete ${keyword.keyword}`} onClick={() => void deleteKeyword(keyword)} className="rounded-lg p-2 text-red-500 hover:bg-red-50 disabled:opacity-50"><Trash2 size={14} /></button>
          </div></td>
        </tr>)}</tbody>
      </table>
    </div> : <div className="p-12 text-center text-slate-400"><Search className="mx-auto mb-3" size={24} /><p>Belum ada News Keyword. Koleksi berita tidak akan berjalan tanpa keyword aktif.</p><button type="button" onClick={openAdd} className="mt-4 rounded-xl bg-ink px-4 py-2.5 text-xs font-bold text-white">Add first keyword</button></div>}

    {mode && <div className="fixed inset-0 z-[1000] grid place-items-center overflow-y-auto bg-slate-950/45 p-4" role="dialog" aria-modal="true" aria-labelledby="keyword-form-title">
      <form onSubmit={saveKeyword} className="w-full max-w-lg rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-200 px-6 py-5">
          <div><div className="eyebrow">News keyword</div><h2 id="keyword-form-title" className="mt-1 font-serif text-2xl">{mode === "add" ? "Add keyword" : "Edit keyword"}</h2></div>
          <button type="button" onClick={closeForm} aria-label="Close keyword form" className="rounded-lg p-2 text-slate-400 hover:bg-slate-100"><X size={18} /></button>
        </div>
        <div className="space-y-4 p-6">
          <label className="block text-[10px] font-bold uppercase tracking-wider text-slate-500">Keyword or phrase
            <input autoFocus required minLength={2} maxLength={180} value={draft.keyword} onChange={(event) => setDraft((current) => ({ ...current, keyword: event.target.value }))} placeholder="contoh: kelangkaan pertalite" className="mt-2 w-full border border-slate-300 px-3 py-3 text-sm normal-case tracking-normal" />
            <span className="mt-1 block text-[10px] font-normal normal-case leading-4 tracking-normal text-slate-400">Pencocokan tidak membedakan huruf besar/kecil dan menggunakan frasa utuh.</span>
          </label>
          <label className="flex items-center gap-3 rounded-xl border border-slate-200 px-4 py-3 text-xs font-bold text-slate-600">
            <input type="checkbox" checked={draft.active} onChange={(event) => setDraft((current) => ({ ...current, active: event.target.checked }))} className="h-4 w-4" />Active and included in collection
          </label>
          {error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs leading-5 text-red-700">{error}</div>}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-200 px-6 py-4">
          <button type="button" disabled={busy} onClick={closeForm} className="rounded-xl border border-slate-300 px-4 py-2.5 text-xs font-bold text-slate-600 disabled:opacity-50">Cancel</button>
          <button disabled={busy} className="flex items-center gap-2 rounded-xl bg-ink px-4 py-2.5 text-xs font-bold text-white disabled:opacity-50"><Plus size={14} />{busy ? "Saving…" : mode === "add" ? "Add keyword" : "Save changes"}</button>
        </div>
      </form>
    </div>}
  </div>;
}
