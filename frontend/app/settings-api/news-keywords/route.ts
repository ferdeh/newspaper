import { proxyNewsKeyword } from "./proxy";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  return proxyNewsKeyword(request);
}
