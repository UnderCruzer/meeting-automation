/**
 * Client IP for rate limiting.
 *
 * Default: rightmost X-Forwarded-For hop — appended by the platform's own proxy,
 * so clients cannot spoof it (worst case it is a shared edge IP and limits get coarser).
 * Set CLIENT_IP_HEADER (e.g. "true-client-ip") only when the platform's edge sets
 * and overwrites that header.
 */
export function clientIp(headers: Headers): string {
  const custom = process.env.CLIENT_IP_HEADER;
  if (custom) {
    const value = headers.get(custom)?.trim();
    if (value) return value;
  }
  const hops = (headers.get("x-forwarded-for") ?? "").split(",").map(h => h.trim()).filter(Boolean);
  return hops[hops.length - 1] ?? "unknown";
}
