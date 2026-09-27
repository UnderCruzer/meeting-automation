import { NextRequest, NextResponse } from "next/server";

async function forward(req: NextRequest, { params }: { params: { path?: string[] } }) {
  const path = params.path ?? [];
  if (!(path.length === 1 && path[0] === "jobs" && req.method === "GET") &&
      !(path.length === 3 && path[0] === "jobs" && /^[a-f0-9]{32}$/.test(path[1]) && path[2] === "decision" && req.method === "POST")) {
    return NextResponse.json({ detail: "Not found" }, { status: 404 });
  }
  try {
    const res = await fetch(`${process.env.UPLOAD_API_URL ?? "http://localhost:8000"}/workspace/${path.join("/")}`, {
      method: req.method, cache: "no-store",
      headers: { "X-API-Key": process.env.BACKEND_API_KEY ?? "", "Content-Type": "application/json" },
      body: req.method === "POST" ? await req.text() : undefined,
    });
    return new NextResponse(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } });
  } catch {
    return NextResponse.json({ detail: "서버에 연결할 수 없습니다." }, { status: 502 });
  }
}
export const GET = forward;
export const POST = forward;
