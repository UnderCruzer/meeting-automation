import { NextRequest, NextResponse } from "next/server";
import { check, secured, toResponse } from "@/lib/gate";

const PUBLIC_PATHS = new Set(["/login", "/api/auth/login"]);

export async function proxy(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (PUBLIC_PATHS.has(pathname)) return secured(NextResponse.next());

  const gate = await check(req.method, req.headers);
  if ("rejection" in gate) {
    if (gate.rejection.status === 401 && !pathname.startsWith("/api/") && req.method === "GET") {
      const login = new URL("/login", req.url);
      if (pathname !== "/") login.searchParams.set("next", pathname + search);
      return secured(NextResponse.redirect(login));
    }
    return toResponse(gate.rejection);
  }
  return secured(NextResponse.next());
}
// Excluded: static assets; api/healthz (public liveness probe);
// api/upload (checks the gate itself so the proxy does not buffer large bodies in memory).
export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico|api/healthz$|api/upload$).*)"] };
