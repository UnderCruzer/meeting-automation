import { NextRequest, NextResponse } from "next/server";
import { gate, secured } from "@/lib/gate";

export async function proxy(req: NextRequest) {
  return (await gate(req)) ?? secured(NextResponse.next());
}
// Excluded: static assets; api/healthz (public liveness probe);
// api/upload (checks gate() itself so the proxy does not buffer large bodies in memory).
export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico|api/healthz$|api/upload$).*)"] };
