import { NextResponse } from "next/server";

/** Unauthenticated liveness probe for hosting platforms. Reports only up/down. */
export async function GET() {
  try {
    const res = await fetch(`${process.env.UPLOAD_API_URL ?? "http://localhost:8000"}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) return NextResponse.json({ status: "ok" });
  } catch {}
  return NextResponse.json({ status: "unavailable" }, { status: 503 });
}
