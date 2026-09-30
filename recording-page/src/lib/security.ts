/** Browser-facing security policy shared by proxy.ts. */

const isDev = process.env.NODE_ENV !== "production";

// Next injects inline hydration scripts; nonces would force dynamic rendering, so
// 'unsafe-inline' stays for scripts. The main wins are frame-ancestors / object-src / form-action.
const CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "media-src 'self' blob:",
  "connect-src 'self'",
  "font-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

export const SECURITY_HEADERS: Record<string, string> = {
  "Content-Security-Policy": CSP,
  "X-Frame-Options": "DENY",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "same-origin",
  "Permissions-Policy": "microphone=(self), camera=(), geolocation=(), payment=()",
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "Cross-Origin-Opener-Policy": "same-origin",
};

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/**
 * Reject cross-site state-changing requests. Browsers attach cached Basic-auth
 * credentials even to cross-site requests, so auth alone does not stop CSRF.
 * Requests with neither header come from non-browser clients and cannot be CSRF.
 */
export function isCrossSiteWrite(method: string, headers: Headers): boolean {
  if (SAFE_METHODS.has(method)) return false;
  const fetchSite = headers.get("sec-fetch-site");
  if (fetchSite) return fetchSite !== "same-origin" && fetchSite !== "none";
  const origin = headers.get("origin");
  if (!origin) return false;
  const host = headers.get("x-forwarded-host") ?? headers.get("host");
  try {
    return new URL(origin).host !== host;
  } catch {
    return true;
  }
}

/** Fixed-window counter of failed logins per client IP (single process, in memory). */
const MAX_FAILURES = Number(process.env.AUTH_MAX_FAILURES ?? 20);
const FAILURE_WINDOW_MS = 15 * 60 * 1000;
const failures = new Map<string, { count: number; resetAt: number }>();

export function isLockedOut(ip: string, now = Date.now()): number {
  const entry = failures.get(ip);
  if (!entry || entry.resetAt <= now) return 0;
  return entry.count >= MAX_FAILURES ? Math.ceil((entry.resetAt - now) / 1000) : 0;
}

export function recordFailure(ip: string, now = Date.now()): void {
  const entry = failures.get(ip);
  if (!entry || entry.resetAt <= now) {
    if (failures.size > 10_000) {
      for (const [key, value] of failures) if (value.resetAt <= now) failures.delete(key);
    }
    failures.set(ip, { count: 1, resetAt: now + FAILURE_WINDOW_MS });
  } else {
    entry.count++;
  }
}
