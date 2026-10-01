import { NextRequest, NextResponse } from "next/server";
import { clientIp } from "@/lib/clientIp";
import { secured } from "@/lib/gate";
import { isLockedOut, recordFailure } from "@/lib/security";
import { backendHeaders, backendUrl, isHttps, readSessionToken, sessionCookie } from "@/lib/session";

type Params = { params: Promise<{ path: string[] }> };

const ALLOWED: Array<[string, RegExp]> = [
  ["POST", /^login$/], ["POST", /^logout$/], ["GET", /^me$/], ["POST", /^password$/],
  ["GET", /^users$/], ["POST", /^users$/], ["PATCH", /^users\/\d{1,9}$/],
];

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return secured(NextResponse.json(body, { status, headers }));
}

async function forward(req: NextRequest, { params }: Params) {
  const path = (await params).path.join("/");
  if (!ALLOWED.some(([method, pattern]) => method === req.method && pattern.test(path)))
    return json({ detail: "Not found" }, 404);

  const ip = clientIp(req.headers);
  if (path === "login") {
    const retryAfter = isLockedOut(ip);
    if (retryAfter) return json({ detail: "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해주세요." }, 429, { "Retry-After": String(retryAfter) });
  }

  const token = readSessionToken(req.headers);
  let res: Response;
  try {
    res = await fetch(backendUrl(`/auth/${path}`), {
      method: req.method, cache: "no-store",
      headers: backendHeaders(token, { "Content-Type": "application/json" }),
      body: req.method === "GET" ? undefined : await req.text(),
    });
  } catch {
    return json({ detail: "서버에 연결할 수 없습니다." }, 502);
  }
  const data = await res.json().catch(() => ({}));

  if (path === "login") {
    if (!res.ok) {
      if (res.status === 401) recordFailure(ip);
      return json({ detail: data.detail ?? "로그인에 실패했습니다." }, res.status);
    }
    // The token lives only in an HttpOnly cookie; the page never sees it.
    const out = json({ user: data.user });
    out.headers.append("Set-Cookie", sessionCookie(data.token, data.maxAge, isHttps(req.headers, req.url)));
    return out;
  }
  if (path === "logout") {
    const out = json({ ok: true });
    out.headers.append("Set-Cookie", sessionCookie("", 0, isHttps(req.headers, req.url)));
    return out;
  }
  return json(data, res.status);
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
