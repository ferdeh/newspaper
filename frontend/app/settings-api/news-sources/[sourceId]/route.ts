import { proxyNewsSource } from "../proxy";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ sourceId: string }> };

async function proxy(request: Request, context: Context) {
  const { sourceId } = await context.params;
  return proxyNewsSource(request, sourceId);
}

export const PATCH = proxy;
export const DELETE = proxy;
