import { proxyNewsKeyword } from "../proxy";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ keywordId: string }> };

async function proxy(request: Request, context: Context) {
  const { keywordId } = await context.params;
  return proxyNewsKeyword(request, keywordId);
}

export const PATCH = proxy;
export const DELETE = proxy;
