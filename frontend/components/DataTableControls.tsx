"use client";

import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

export const TABLE_PAGE_SIZES = [10, 25, 50] as const;
export type TablePageSize = (typeof TABLE_PAGE_SIZES)[number];
export type TableSortDirection = "asc" | "desc";
export type TableSortValue = string | number | boolean | Date | null | undefined;

type UseDataTableOptions<T> = {
  rows: T[];
  searchText: (row: T) => string;
  sortValue: (row: T, key: string) => TableSortValue;
  initialSortKey: string;
  initialSortDirection?: TableSortDirection;
  defaultPageSize?: TablePageSize;
};

function comparable(value: TableSortValue): string | number {
  if (value == null) return "";
  if (value instanceof Date) return value.getTime();
  if (typeof value === "boolean") return value ? 1 : 0;
  return value;
}

export function useDataTable<T>({
  rows,
  searchText,
  sortValue,
  initialSortKey,
  initialSortDirection = "asc",
  defaultPageSize = 10,
}: UseDataTableOptions<T>) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState(initialSortKey);
  const [sortDirection, setSortDirection] = useState<TableSortDirection>(initialSortDirection);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<TablePageSize>(defaultPageSize);

  const filteredRows = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("id-ID");
    if (!query) return rows;
    return rows.filter((row) => searchText(row).toLocaleLowerCase("id-ID").includes(query));
  }, [rows, search, searchText]);

  const sortedRows = useMemo(() => filteredRows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      const a = comparable(sortValue(left.row, sortKey));
      const b = comparable(sortValue(right.row, sortKey));
      const result = typeof a === "number" && typeof b === "number"
        ? a - b
        : String(a).localeCompare(String(b), "id-ID", { numeric: true, sensitivity: "base" });
      if (result === 0) return left.index - right.index;
      return sortDirection === "asc" ? result : -result;
    })
    .map(({ row }) => row), [filteredRows, sortDirection, sortKey, sortValue]);

  const pageCount = Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const pageRows = useMemo(() => {
    const start = (page - 1) * pageSize;
    return sortedRows.slice(start, start + pageSize);
  }, [page, pageSize, sortedRows]);

  useEffect(() => setPage(1), [search, pageSize, sortKey, sortDirection]);
  useEffect(() => setPage((current) => Math.min(current, pageCount)), [pageCount]);

  const toggleSort = (key: string) => {
    if (sortKey === key) setSortDirection((current) => current === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDirection("asc");
    }
  };

  return {
    search,
    setSearch,
    sortKey,
    sortDirection,
    toggleSort,
    page,
    setPage,
    pageSize,
    setPageSize,
    pageCount,
    pageRows,
    filteredCount: sortedRows.length,
    totalCount: rows.length,
    firstRow: sortedRows.length ? (page - 1) * pageSize + 1 : 0,
    lastRow: Math.min(page * pageSize, sortedRows.length),
  };
}

export function TableToolbar({
  search,
  onSearchChange,
  pageSize,
  onPageSizeChange,
  placeholder = "Cari seluruh kolom…",
}: {
  search: string;
  onSearchChange: (value: string) => void;
  pageSize: TablePageSize;
  onPageSizeChange: (value: TablePageSize) => void;
  placeholder?: string;
}) {
  return <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
    <label className="relative block min-w-0 sm:w-72">
      <span className="sr-only">{placeholder}</span>
      <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={14}/>
      <input type="search" value={search} onChange={(event) => onSearchChange(event.target.value)} placeholder={placeholder} className="h-10 w-full rounded-xl border border-slate-200 bg-white pl-9 pr-9 text-xs text-slate-600 focus:border-lime focus:outline-none focus:ring-2 focus:ring-lime/20"/>
      {search && <button type="button" onClick={() => onSearchChange("")} aria-label="Hapus pencarian" className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-ink"><X size={13}/></button>}
    </label>
    <label className="flex items-center gap-2 whitespace-nowrap text-[10px] font-bold uppercase tracking-wider text-slate-400">
      Baris
      <select value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value) as TablePageSize)} className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold text-ink">
        {TABLE_PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
      </select>
    </label>
  </div>;
}

export function SortableHeader({
  column,
  label,
  sortKey,
  sortDirection,
  onSort,
  children,
}: {
  column: string;
  label: string;
  sortKey: string;
  sortDirection: TableSortDirection;
  onSort: (key: string) => void;
  children?: ReactNode;
}) {
  const active = sortKey === column;
  const Icon = active ? (sortDirection === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
  return <th aria-sort={active ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}>
    <button type="button" onClick={() => onSort(column)} aria-label={`Urutkan berdasarkan ${label}`} className={`inline-flex items-center gap-1.5 rounded-md py-1 text-left transition ${active ? "text-petrol" : "hover:text-ink"}`}>
      {children ?? label}<Icon size={11} aria-hidden="true"/>
    </button>
  </th>;
}

export function TablePagination({
  page,
  pageCount,
  firstRow,
  lastRow,
  filteredCount,
  totalCount,
  onPageChange,
}: {
  page: number;
  pageCount: number;
  firstRow: number;
  lastRow: number;
  filteredCount: number;
  totalCount: number;
  onPageChange: (page: number) => void;
}) {
  return <div className="flex flex-col gap-3 border-t border-slate-200 bg-slate-50/60 px-5 py-3 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between">
    <span>Menampilkan <strong className="text-ink">{firstRow}–{lastRow}</strong> dari <strong className="text-ink">{filteredCount}</strong> hasil{filteredCount !== totalCount ? ` (${totalCount} total)` : ""}</span>
    <div className="flex items-center gap-2">
      <button type="button" onClick={() => onPageChange(Math.max(1, page - 1))} disabled={page === 1} className="grid h-9 w-9 place-items-center rounded-lg border border-slate-200 bg-white text-ink disabled:cursor-not-allowed disabled:opacity-35" aria-label="Halaman sebelumnya"><ChevronLeft size={15}/></button>
      <span className="min-w-24 text-center font-semibold text-ink">Halaman {page} / {pageCount}</span>
      <button type="button" onClick={() => onPageChange(Math.min(pageCount, page + 1))} disabled={page === pageCount} className="grid h-9 w-9 place-items-center rounded-lg border border-slate-200 bg-white text-ink disabled:cursor-not-allowed disabled:opacity-35" aria-label="Halaman berikutnya"><ChevronRight size={15}/></button>
    </div>
  </div>;
}
