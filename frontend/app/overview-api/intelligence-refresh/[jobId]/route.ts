import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(_request: Request, context: { params: Promise<{ jobId: string }> }) {
  const internalToken = process.env.INTERNAL_API_TOKEN;
  const internalApi = process.env.API_INTERNAL_URL || "http://api:8000/api";
  if (!internalToken) {
    return NextResponse.json({ detail: "Credential internal server belum dikonfigurasi." }, { status: 503 });
  }

  const { jobId } = await context.params;
  if (!UUID_PATTERN.test(jobId)) {
    return NextResponse.json({ detail: "ID pembaruan intelligence tidak valid." }, { status: 400 });
  }

  try {
    const response = await fetch(`${internalApi}/internal/intelligence/refresh/${jobId}`, {
      headers: { Accept: "application/json", "X-Internal-Token": internalToken },
      cache: "no-store",
    });
    const result = await response.json().catch(() => ({ detail: "Respons backend tidak valid." }));
    return NextResponse.json(result, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ detail: "Server tidak dapat membaca status pembaruan intelligence." }, { status: 502 });
  }
}
