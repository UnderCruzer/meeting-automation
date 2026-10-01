import { NextRequest, NextResponse } from "next/server";
import { check, secured, toResponse } from "@/lib/gate";
import { isCrossSiteWrite } from "@/lib/security";

const PUBLIC_PATHS = new Set(["/login", "/api/auth/login"]);

export async function proxy(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (PUBLIC_PATHS.has(pathname)) {
    // No session needed, but a cross-site login POST (login CSRF) is still refused.
    if (isCrossSiteWrite(req.method, req.headers))
      return toResponse({ status: 403, message: "다른 사이트에서 보낸 요청은 허용되지 않습니다." });
    return secured(NextResponse.next());
  }

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
