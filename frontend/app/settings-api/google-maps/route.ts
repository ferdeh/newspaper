import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function requestIsSameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  const expectedHost = request.headers.get("x-forwarded-host") || request.headers.get("host");
  try {
    return !expectedHost || new URL(origin).host === expectedHost;
  } catch {
    return false;
  }
}

export async function PUT(request: Request) {
  if (!requestIsSameOrigin(request)) {
    return NextResponse.json({ detail: "Permintaan lintas-origin ditolak." }, { status: 403 });
  }

  const internalToken = process.env.INTERNAL_API_TOKEN;
  const internalApi = process.env.API_INTERNAL_URL || "http://api:8000/api";
  if (!internalToken) {
    return NextResponse.json({ detail: "Credential internal server belum dikonfigurasi." }, { status: 503 });
  }

  const payload = await request.json().catch(() => null) as { api_key?: unknown } | null;
  if (typeof payload?.api_key !== "string" || payload.api_key.trim().length < 20 || payload.api_key.length > 200) {
    return NextResponse.json({ detail: "Masukkan Google Maps API key yang valid." }, { status: 422 });
  }

  try {
    const response = await fetch(`${internalApi}/admin/provider-secrets/google-maps`, {
      method: "PUT",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Internal-Token": internalToken,
      },
      body: JSON.stringify({ api_key: payload.api_key.trim() }),
      cache: "no-store",
    });
    const result = await response.json().catch(() => ({ detail: "Respons backend tidak valid." }));
    return NextResponse.json(result, {
      status: response.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json({ detail: "Server tidak dapat menghubungi layanan konfigurasi." }, { status: 502 });
  }
}
