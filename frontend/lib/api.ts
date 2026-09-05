const PUBLIC_API = process.env.NEXT_PUBLIC_API_URL || "/api";

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${PUBLIC_API}${path}`, { ...init, headers: { Accept: "application/json", ...init?.headers } });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail || `API request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function formatDate(value: string, withTime = false): string {
  return new Intl.DateTimeFormat("id-ID", { dateStyle: "medium", ...(withTime ? { timeStyle: "short" } : {}) }).format(new Date(value));
}

export function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
