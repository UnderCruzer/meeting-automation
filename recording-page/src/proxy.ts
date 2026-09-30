import { NextRequest, NextResponse } from "next/server";
import { clientIp } from "@/lib/clientIp";
import { SECURITY_HEADERS, isCrossSiteWrite, isLockedOut, recordFailure } from "@/lib/security";

function secured(res: NextResponse): NextResponse {
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) res.headers.set(name, value);
  return res;
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

export async function proxy(req: NextRequest) {
  if (isCrossSiteWrite(req.method, req.headers))
    return secured(new NextResponse("다른 사이트에서 보낸 요청은 허용되지 않습니다.", { status: 403 }));

  const password = process.env.WORKSPACE_PASSWORD;
  if (!password) {
    if (process.env.WORKSPACE_MODE === "standalone")
      return secured(new NextResponse("WORKSPACE_PASSWORD 설정이 필요합니다.", { status: 503 }));
    return secured(NextResponse.next());
  }

  const ip = clientIp(req.headers);
  const retryAfter = isLockedOut(ip);
  if (retryAfter) return secured(new NextResponse("로그인 시도가 너무 많습니다. 잠시 후 다시 시도해주세요.", {
    status: 429, headers: { "Retry-After": String(retryAfter) },
  }));

  const provided = req.headers.get("authorization");
  if (!provided || !(await sameSecret(provided, "Basic " + btoa("workspace:" + password)))) {
    // The browser's first credential-less request is a challenge, not a failed guess.
    if (provided) recordFailure(ip);
    return secured(new NextResponse("인증이 필요합니다.", {
      status: 401, headers: { "WWW-Authenticate": 'Basic realm="Meeting workspace", charset="UTF-8"' },
    }));
  }
  return secured(NextResponse.next());
}
// api/healthz stays public so hosting platforms can probe liveness.
export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico|api/healthz$).*)"] };
