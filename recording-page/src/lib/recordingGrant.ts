/**
 * Verify signed recording links issued by the Slack bot (slack-bot/src/services/recordingGrant.js).
 * A valid grant lets one Slack user open /record and upload for one meeting, without a web login.
 * Server-only: needs RECORDING_LINK_SECRET.
 */

export type RecordingGrant = {
  v: 1; m: string; u: string; t: string; s: string; e: string; l: string; exp: number;
};

function fromBase64Url(value: string): Uint8Array {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  const binary = atob(base64);
  return Uint8Array.from(binary, c => c.charCodeAt(0));
}

/** Decode without verifying — for display in the browser only. */
export function decodeGrant(token: string): RecordingGrant | null {
  try {
    const [body] = token.split(".");
    return JSON.parse(new TextDecoder().decode(fromBase64Url(body)));
  } catch {
    return null;
  }
}

export async function verifyGrant(
  token: string | null | undefined, secret = process.env.RECORDING_LINK_SECRET, now = Date.now(),
): Promise<RecordingGrant | null> {
  if (!token || !secret || token.length > 4096) return null;
  const [body, sig, extra] = token.split(".");
  if (!body || !sig || extra !== undefined) return null;
  try {
    const key = await crypto.subtle.importKey(
      "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["verify"],
    );
    // subtle.verify compares in constant time.
    const signature = fromBase64Url(sig);
    const valid = await crypto.subtle.verify("HMAC", key, signature as BufferSource, new TextEncoder().encode(body));
    if (!valid) return null;
    const grant = decodeGrant(token);
    if (!grant || grant.v !== 1 || typeof grant.m !== "string" || typeof grant.u !== "string") return null;
    if (!(grant.exp * 1000 > now)) return null;
    return grant;
  } catch {
    return null;
  }
}
