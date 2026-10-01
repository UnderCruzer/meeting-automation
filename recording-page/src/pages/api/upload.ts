import http from "node:http";
import type { NextApiRequest, NextApiResponse } from "next";
import { clientIp } from "@/lib/clientIp";
import { check } from "@/lib/gate";
import { backendHeaders, backendUrl } from "@/lib/session";
import { verifyGrant } from "@/lib/recordingGrant";
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

  const gate = await check(req.method ?? "GET", headers);
  // No web session: a signed Slack recording link may still upload for its own meeting.
  const grant = "rejection" in gate && gate.rejection.status === 401
    ? await verifyGrant(headers.get("x-recording-grant")) : null;
  if ("rejection" in gate && !grant)
    return send(res, gate.rejection.status, gate.rejection.message, gate.rejection.headers);
  if (req.method !== "POST") return send(res, 405, "Method Not Allowed", { Allow: "POST" });

  const contentType = headers.get("content-type") ?? "";
  if (!contentType.startsWith("multipart/form-data"))
    return send(res, 415, JSON.stringify({ detail: "multipart/form-data required" }), { "Content-Type": "application/json" });

  const target = new URL(backendUrl("/upload"));
  const forwardHeaders: http.OutgoingHttpHeaders = backendHeaders("token" in gate ? gate.token : "", {
    "Content-Type": contentType,
    // Backend rate-limits per client; every proxied request would otherwise look like 127.0.0.1.
    "X-Client-IP": clientIp(headers),
  });
  if (grant) {
    // Trusted by the backend only together with the API key.
    forwardHeaders["X-Upload-Actor"] = `slack:${grant.u}`;
    forwardHeaders["X-Upload-Meeting"] = encodeURIComponent(grant.m);
  }
  const length = headers.get("content-length");
  if (length) forwardHeaders["Content-Length"] = length;

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
