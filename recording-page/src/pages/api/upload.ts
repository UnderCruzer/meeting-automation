import http from "node:http";
import type { NextApiRequest, NextApiResponse } from "next";
import { clientIp } from "@/lib/clientIp";
import { check } from "@/lib/gate";
import { SECURITY_HEADERS } from "@/lib/security";

/**
 * Server-side upload proxy.
 *
 * Pages Router on purpose: App Router exposes the body as a Web stream that Next fills
 * from 'data' events without backpressure, so a long recording ends up fully in memory.
 * Here the raw Node request is piped to the backend, keeping memory flat on 512 MB hosts.
 * The API key comes from a server-only env var and never reaches the browser.
 * Excluded from proxy.ts, so auth/CSRF run here via check().
 */
export const config = { api: { bodyParser: false, responseLimit: false } };

function send(res: NextApiResponse, status: number, body: string, headers: Record<string, string> = {}) {
  for (const [name, value] of Object.entries({ ...SECURITY_HEADERS, ...headers })) res.setHeader(name, value);
  res.status(status).send(body);
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const headers = new Headers();
  for (const [name, value] of Object.entries(req.headers))
    if (typeof value === "string") headers.set(name, value);
    else if (Array.isArray(value)) headers.set(name, value.join(", "));

  const rejection = await check(req.method ?? "GET", headers);
  if (rejection) return send(res, rejection.status, rejection.message, rejection.headers);
  if (req.method !== "POST") return send(res, 405, "Method Not Allowed", { Allow: "POST" });

  const contentType = headers.get("content-type") ?? "";
  if (!contentType.startsWith("multipart/form-data"))
    return send(res, 415, JSON.stringify({ detail: "multipart/form-data required" }), { "Content-Type": "application/json" });

  const target = new URL("/upload", process.env.UPLOAD_API_URL ?? "http://localhost:8000");
  const forwardHeaders: http.OutgoingHttpHeaders = {
    "Content-Type": contentType,
    // Backend rate-limits per client; every proxied request would otherwise look like 127.0.0.1.
    "X-Client-IP": clientIp(headers),
  };
  const length = headers.get("content-length");
  if (length) forwardHeaders["Content-Length"] = length;
  if (process.env.BACKEND_API_KEY) forwardHeaders["X-API-Key"] = process.env.BACKEND_API_KEY;

  await new Promise<void>(resolve => {
    const upstream = http.request(target, { method: "POST", headers: forwardHeaders }, backendRes => {
      const chunks: Buffer[] = [];
      backendRes.on("data", chunk => chunks.push(chunk));
      backendRes.on("end", () => {
        send(res, backendRes.statusCode ?? 502, Buffer.concat(chunks).toString(), {
          "Content-Type": backendRes.headers["content-type"] ?? "application/json",
        });
        resolve();
      });
    });
    upstream.on("error", () => {
      if (!res.headersSent) send(res, 502, JSON.stringify({ detail: "Backend unreachable" }), { "Content-Type": "application/json" });
      resolve();
    });
    req.on("aborted", () => upstream.destroy());
    // pipe() pauses the client stream whenever the backend is slower — memory stays bounded.
    req.pipe(upstream);
  });
}
