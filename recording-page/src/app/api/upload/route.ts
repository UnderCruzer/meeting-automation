import { NextRequest, NextResponse } from "next/server";
import { clientIp } from "@/lib/clientIp";
import { gate, secured } from "@/lib/gate";

/**
 * Server-side upload proxy.
 * Streams the multipart body to the backend without buffering it, and injects the
 * API key from a server-only env var — never exposed to the browser bundle.
 * Excluded from proxy.ts, so auth/CSRF run here via gate().
 */
export async function POST(req: NextRequest) {
  const rejected = await gate(req);
  if (rejected) return rejected;

  const contentType = req.headers.get("content-type") ?? "";
  if (!contentType.startsWith("multipart/form-data") || !req.body)
    return secured(NextResponse.json({ detail: "multipart/form-data required" }, { status: 415 }));

  const backendUrl = process.env.UPLOAD_API_URL ?? "http://localhost:8000";
  const apiKey = process.env.BACKEND_API_KEY ?? "";
  const headers: Record<string, string> = {
    "Content-Type": contentType,
    // Backend rate-limits per client; every proxied request would otherwise look like 127.0.0.1.
    "X-Client-IP": clientIp(req.headers),
  };
  if (apiKey) headers["X-API-Key"] = apiKey;

  let res: Response;
  try {
    res = await fetch(`${backendUrl}/upload`, {
      method: "POST",
      body: req.body,
      headers,
      // Required by Node fetch to send a ReadableStream body.
      duplex: "half",
    } as RequestInit & { duplex: "half" });
  } catch {
    return secured(NextResponse.json({ detail: "Backend unreachable" }, { status: 502 }));
  }

  return secured(new NextResponse(await res.text(), {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  }));
}
