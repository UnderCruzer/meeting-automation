const test = require("node:test");
const assert = require("node:assert");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { signGrant } = require("../src/services/recordingGrant");

// The web verifier (TypeScript, run via Node type stripping) must accept what the bot signs.
const webModule = () => import(pathToFileURL(path.join(__dirname, "../../recording-page/src/lib/recordingGrant.ts")).href);

const SECRET = "test-only-secret";
const MEETING = { id: "ics:weekly-1:2026-10-01T06:00:00.000Z", title: "주간 회의",
  startTime: "2026-10-01T06:00:00.000Z", endTime: "2026-10-01T07:00:00.000Z", location: "회의실 A" };

test("web verifies a bot-signed grant and reads the meeting", async () => {
  const { verifyGrant } = await webModule();
  const grant = await verifyGrant(signGrant(MEETING, "U0123ABC", SECRET), SECRET, Date.parse("2026-10-01T06:30:00Z"));
  assert.strictEqual(grant.m, MEETING.id);
  assert.strictEqual(grant.u, "U0123ABC");
  assert.strictEqual(grant.t, "주간 회의");
});

test("grant expires two hours after the meeting ends", async () => {
  const { verifyGrant } = await webModule();
  const token = signGrant(MEETING, "U0123ABC", SECRET);
  assert.ok(await verifyGrant(token, SECRET, Date.parse("2026-10-01T08:59:00Z")));
  assert.strictEqual(await verifyGrant(token, SECRET, Date.parse("2026-10-01T09:01:00Z")), null);
});

test("tampered payload, wrong secret or junk are rejected", async () => {
  const { verifyGrant } = await webModule();
  const now = Date.parse("2026-10-01T06:30:00Z");
  const token = signGrant(MEETING, "U0123ABC", SECRET);
  const [body, sig] = token.split(".");
  const forged = Buffer.from(JSON.stringify({ ...JSON.parse(Buffer.from(body, "base64url")), m: "other" })).toString("base64url");
  assert.strictEqual(await verifyGrant(`${forged}.${sig}`, SECRET, now), null);
  assert.strictEqual(await verifyGrant(token, "other-secret", now), null);
  assert.strictEqual(await verifyGrant("not-a-token", SECRET, now), null);
  assert.strictEqual(await verifyGrant(`${token}.extra`, SECRET, now), null);
  assert.strictEqual(await verifyGrant(token, undefined, now), null);
  // Same signature bytes spelled differently (unused low bits of the last base64 char): rejected too.
  const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  const variant = sig.slice(0, -1) + ALPHABET[ALPHABET.indexOf(sig.at(-1)) ^ 1];
  assert.ok(Buffer.from(variant, "base64url").equals(Buffer.from(sig, "base64url")));
  assert.strictEqual(await verifyGrant(`${body}.${variant}`, SECRET, now), null);
});
