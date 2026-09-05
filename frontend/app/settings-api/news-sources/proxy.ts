import { NextResponse } from "next/server";

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

export async function proxyNewsSource(request: Request, sourceId?: string) {
  if (!requestIsSameOrigin(request)) {
    return NextResponse.json({ detail: "Permintaan lintas-origin ditolak." }, { status: 403 });
  }
  if (sourceId !== undefined && !/^\d+$/.test(sourceId)) {
    return NextResponse.json({ detail: "ID news source tidak valid." }, { status: 400 });
  }

  const internalToken = process.env.INTERNAL_API_TOKEN;
  const internalApi = process.env.API_INTERNAL_URL || "http://api:8000/api";
  if (!internalToken) {
    return NextResponse.json({ detail: "Credential internal server belum dikonfigurasi." }, { status: 503 });
  }

  const target = `${internalApi}/admin/news-sources${sourceId === undefined ? "" : `/${sourceId}`}`;
  const body = ["POST", "PUT", "PATCH"].includes(request.method) ? await request.text() : undefined;
  try {
    const response = await fetch(target, {
      method: request.method,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Internal-Token": internalToken,
      },
      body: body || undefined,
      cache: "no-store",
    });
    const result = await response.json().catch(() => ({ detail: "Respons backend tidak valid." }));
    return NextResponse.json(result, {
      status: response.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json({ detail: "Server tidak dapat menghubungi layanan News Sources." }, { status: 502 });
  }
}
