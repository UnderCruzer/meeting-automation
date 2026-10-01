/**
 * Signed recording links (workflow 4): the DM link lets one Slack user record and upload
 * for one meeting without a web login, until shortly after the meeting ends.
 *
 * Format: base64url(JSON payload) + "." + base64url(HMAC-SHA256(secret, payload part)).
 * Verified by recording-page/src/lib/recordingGrant.ts with the same RECORDING_LINK_SECRET.
 */
const crypto = require("crypto");

const GRACE_AFTER_END_SECONDS = 2 * 60 * 60;

function signGrant(meeting, slackUserId, secret, now = Date.now()) {
  const end = Date.parse(meeting.endTime);
  const exp = Math.floor((Number.isFinite(end) ? end : now) / 1000) + GRACE_AFTER_END_SECONDS;
  const payload = {
    v: 1,
    m: meeting.id,
    u: slackUserId,
    t: meeting.title ?? "",
    s: meeting.startTime,
    e: meeting.endTime,
    l: meeting.location ?? "",
    exp,
  };
  const body = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const sig = crypto.createHmac("sha256", secret).update(body).digest("base64url");
  return `${body}.${sig}`;
}

module.exports = { signGrant };
