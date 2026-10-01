/** Session cookie + backend calls shared by proxy.ts and API routes (server-only). */

export const SESSION_COOKIE = "ma_session";

export type SessionUser = { id: number; username: string; role: "admin" | "member"; active: boolean; mustChangePassword: boolean };

export function readSessionToken(headers: Headers): string {
  for (const part of (headers.get("cookie") ?? "").split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === SESSION_COOKIE) return decodeURIComponent(rest.join("="));
  }
  return "";
}

export function backendUrl(path: string): string {
  return `${process.env.UPLOAD_API_URL ?? "http://localhost:8000"}${path}`;
}

/** Headers that authenticate this server to the backend and identify the signed-in user. */
export function backendHeaders(token: string, extra: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  if (process.env.BACKEND_API_KEY) headers["X-API-Key"] = process.env.BACKEND_API_KEY;
  if (token) headers["X-Session-Token"] = token;
  return headers;
}

/** Resolve the session with the backend. null = not signed in; throws if the backend is down. */
export async function sessionUser(token: string): Promise<SessionUser | null> {
  if (!token) return null;
  const res = await fetch(backendUrl("/auth/me"), { headers: backendHeaders(token), cache: "no-store" });
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`auth backend ${res.status}`);
  return (await res.json()).user ?? null;
}

export function sessionCookie(token: string, maxAge: number, secure: boolean): string {
  return [`${SESSION_COOKIE}=${encodeURIComponent(token)}`, "Path=/", "HttpOnly", "SameSite=Lax",
    `Max-Age=${maxAge}`, ...(secure ? ["Secure"] : [])].join("; ");
}

export function isHttps(headers: Headers, url: string): boolean {
  return (headers.get("x-forwarded-proto") ?? "").split(",")[0].trim() === "https" || url.startsWith("https:");
}
