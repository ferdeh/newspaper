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

export async function POST(request: Request) {
  if (!requestIsSameOrigin(request)) {
    return NextResponse.json({ detail: "Permintaan lintas-origin ditolak." }, { status: 403 });
  }

  const internalToken = process.env.INTERNAL_API_TOKEN;
  const internalApi = process.env.API_INTERNAL_URL || "http://api:8000/api";
  if (!internalToken) {
    return NextResponse.json({ detail: "Credential internal server belum dikonfigurasi." }, { status: 503 });
  }

  try {
    const response = await fetch(`${internalApi}/internal/intelligence/refresh`, {
      method: "POST",
      headers: { Accept: "application/json", "X-Internal-Token": internalToken },
      cache: "no-store",
    });
    const result = await response.json().catch(() => ({ detail: "Respons backend tidak valid." }));
    return NextResponse.json(result, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ detail: "Server tidak dapat memulai pembaruan intelligence." }, { status: 502 });
  }
}
