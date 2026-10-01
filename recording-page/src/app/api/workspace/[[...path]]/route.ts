import { NextRequest, NextResponse } from "next/server";
import { clientIp } from "@/lib/clientIp";
import { backendHeaders, backendUrl, readSessionToken } from "@/lib/session";

async function forward(req: NextRequest, { params }: { params: Promise<{ path?: string[] }> }) {
  const path = (await params).path ?? [];
  if (path.length === 1 && path[0] === "config" && req.method === "GET") {
    const backend = await fetch(backendUrl("/workspace/config"), {
      cache: "no-store", headers: backendHeaders(readSessionToken(req.headers)),
    }).then(r => r.ok ? r.json() : {}).catch(() => ({}));
    return NextResponse.json({ ephemeral: process.env.WORKSPACE_STORAGE === "ephemeral", ...backend });
  }
  if (!(path.length === 1 && path[0] === "jobs" && req.method === "GET") &&
      !(path.length === 3 && path[0] === "jobs" && /^[a-f0-9]{32}$/.test(path[1]) && ["decision", "publish", "retry"].includes(path[2]) && req.method === "POST") &&
      !(path.length === 2 && path[0] === "jobs" && /^[a-f0-9]{32}$/.test(path[1]) && req.method === "DELETE") &&
      !(path.length === 3 && path[0] === "jobs" && /^[a-f0-9]{32}$/.test(path[1]) && path[2] === "action-items" && req.method === "PUT")) {
    return NextResponse.json({ detail: "Not found" }, { status: 404 });
  }
  try {
    const res = await fetch(backendUrl(`/workspace/${path.join("/")}`), {
      method: req.method, cache: "no-store",
      headers: backendHeaders(readSessionToken(req.headers), { "Content-Type": "application/json", "X-Client-IP": clientIp(req.headers) }),
      body: req.method === "POST" || req.method === "PUT" ? await req.text() : undefined,
    });
    return new NextResponse(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
  } catch {
    return NextResponse.json({ detail: "서버에 연결할 수 없습니다." }, { status: 502 });
  }
}
export const GET = forward;
export const POST = forward;
export const DELETE = forward;
export const PUT = forward;
