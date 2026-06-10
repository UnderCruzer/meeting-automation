import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side upload proxy.
 * Forwards the multipart form to the backend and injects the API key
 * from a server-only env var — never exposed to the browser bundle.
 */
export async function POST(req: NextRequest) {
  const backendUrl = process.env.UPLOAD_API_URL ?? "http://localhost:8000";
  const apiKey = process.env.BACKEND_API_KEY ?? "";

  const formData = await req.formData();

  const headers: HeadersInit = {};
  if (apiKey) headers["X-API-Key"] = apiKey;

  let res: Response;
  try {
    res = await fetch(`${backendUrl}/upload`, {
      method: "POST",
      body: formData,
      headers,
    });
  } catch (err) {
    return NextResponse.json({ detail: "Backend unreachable" }, { status: 502 });
  }

  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
