import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const origin = request.headers.get("origin");
  const expectedHost = request.headers.get("x-forwarded-host") || request.headers.get("host");
  try {
    if (origin && expectedHost && new URL(origin).host !== expectedHost) {
      return NextResponse.json({ detail: "Permintaan lintas-origin ditolak." }, { status: 403 });
    }
  } catch {
    return NextResponse.json({ detail: "Origin tidak valid." }, { status: 403 });
  }
  const internalToken = process.env.INTERNAL_API_TOKEN;
  const internalApi = process.env.API_INTERNAL_URL || "http://api:8000/api";
  if (!internalToken) return NextResponse.json({ detail: "Credential internal server belum dikonfigurasi." }, { status: 503 });
  try {
    const response = await fetch(`${internalApi}/tbbm`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-Internal-Token": internalToken },
      body: await request.text(),
      cache: "no-store",
    });
    const result = await response.json().catch(() => ({ detail: "Respons backend tidak valid." }));
    return NextResponse.json(result, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ detail: "Server tidak dapat menghubungi layanan Master TBBM." }, { status: 502 });
  }
}
