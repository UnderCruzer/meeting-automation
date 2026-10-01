import { NextRequest, NextResponse } from "next/server";
import { backendHeaders, backendUrl, readSessionToken } from "@/lib/session";

async function forward(req: NextRequest, { params }: { params: Promise<{ path?: string[] }> }) {
  const path = (await params).path ?? [];
  if (path.length === 1 && path[0] === "config" && req.method === "GET") {
    return NextResponse.json({ ephemeral: process.env.WORKSPACE_STORAGE === "ephemeral" });
  }
  if (!(path.length === 1 && path[0] === "jobs" && req.method === "GET") &&
      !(path.length === 3 && path[0] === "jobs" && /^[a-f0-9]{32}$/.test(path[1]) && path[2] === "decision" && req.method === "POST") &&
      !(path.length === 2 && path[0] === "jobs" && /^[a-f0-9]{32}$/.test(path[1]) && req.method === "DELETE")) {
    return NextResponse.json({ detail: "Not found" }, { status: 404 });
  }
  try {
    const res = await fetch(backendUrl(`/workspace/${path.join("/")}`), {
      method: req.method, cache: "no-store",
      headers: backendHeaders(readSessionToken(req.headers), { "Content-Type": "application/json" }),
      body: req.method === "POST" ? await req.text() : undefined,
    });
    return new NextResponse(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
  } catch {
    return NextResponse.json({ detail: "서버에 연결할 수 없습니다." }, { status: 502 });
  }
}
export const GET = forward;
export const POST = forward;
export const DELETE = forward;
