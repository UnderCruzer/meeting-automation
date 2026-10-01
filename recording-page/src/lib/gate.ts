import { NextResponse } from "next/server";
import { SECURITY_HEADERS, isCrossSiteWrite } from "@/lib/security";
import { readSessionToken, sessionUser, type SessionUser } from "@/lib/session";

export type Rejection = { status: number; message: string; headers?: Record<string, string> };
export type Gate = { rejection: Rejection } | { token: string; user: SessionUser | null };

export function secured(res: NextResponse): NextResponse {
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) res.headers.set(name, value);
  return res;
}

export function toResponse(rejection: Rejection): NextResponse {
  return secured(new NextResponse(rejection.message, { status: rejection.status, headers: rejection.headers }));
}

/** Accounts are enforced in standalone mode or once an admin password is configured. */
export function authEnabled(): boolean {
  return process.env.WORKSPACE_MODE === "standalone" || process.env.AUTH_ENABLED === "true";
}

/**
 * CSRF check + session check. Used by proxy.ts and by routes excluded from the proxy
 * (so their bodies are not buffered). Login attempts are rate-limited in the login route.
 */
export async function check(method: string, headers: Headers): Promise<Gate> {
  if (isCrossSiteWrite(method, headers))
    return { rejection: { status: 403, message: "다른 사이트에서 보낸 요청은 허용되지 않습니다." } };
  const token = readSessionToken(headers);
  let user: SessionUser | null;
  try {
    user = await sessionUser(token);
  } catch {
    return { rejection: { status: 503, message: "인증 서버에 연결할 수 없습니다." } };
  }
  if (!user && authEnabled()) return { rejection: { status: 401, message: "로그인이 필요합니다." } };
  return { token, user };
}
