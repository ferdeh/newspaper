import { proxyNewsSource } from "./proxy";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  return proxyNewsSource(request);
}
