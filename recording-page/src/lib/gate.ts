import { NextRequest, NextResponse } from "next/server";
import { clientIp } from "@/lib/clientIp";
import { SECURITY_HEADERS, isCrossSiteWrite, isLockedOut, recordFailure } from "@/lib/security";

export type Rejection = { status: number; message: string; headers?: Record<string, string> };

export function secured(res: NextResponse): NextResponse {
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) res.headers.set(name, value);
  return res;
}

export function toResponse(rejection: Rejection): NextResponse {
  return secured(new NextResponse(rejection.message, { status: rejection.status, headers: rejection.headers }));
}

async function sameSecret(provided: string, expected: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const digest = (value: string) => crypto.subtle.digest("SHA-256", encoder.encode(value));
  const [a, b] = await Promise.all([digest(provided), digest(expected)]);
  const left = new Uint8Array(a), right = new Uint8Array(b);
  let difference = 0;
  for (let i = 0; i < left.length; i++) difference |= left[i] ^ right[i];
  return difference === 0;
}

/**
 * CSRF check, login lockout and Basic auth. Returns a rejection, or null to continue.
 * Used by proxy.ts and by routes excluded from the proxy (so their bodies are not buffered).
 */
export async function check(method: string, headers: Headers): Promise<Rejection | null> {
  if (isCrossSiteWrite(method, headers))
    return { status: 403, message: "다른 사이트에서 보낸 요청은 허용되지 않습니다." };

  const password = process.env.WORKSPACE_PASSWORD;
  if (!password) {
    if (process.env.WORKSPACE_MODE === "standalone")
      return { status: 503, message: "WORKSPACE_PASSWORD 설정이 필요합니다." };
    return null;
  }

  const ip = clientIp(headers);
  const retryAfter = isLockedOut(ip);
  if (retryAfter) return {
    status: 429, message: "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해주세요.",
    headers: { "Retry-After": String(retryAfter) },
  };

  const provided = headers.get("authorization");
  if (!provided || !(await sameSecret(provided, "Basic " + btoa("workspace:" + password)))) {
    // The browser's first credential-less request is a challenge, not a failed guess.
    if (provided) recordFailure(ip);
    return {
      status: 401, message: "인증이 필요합니다.",
      headers: { "WWW-Authenticate": 'Basic realm="Meeting workspace", charset="UTF-8"' },
    };
  }
  return null;
}

export async function gate(req: NextRequest): Promise<NextResponse | null> {
  const rejection = await check(req.method, req.headers);
  return rejection && toResponse(rejection);
}
