const dayjs = require("dayjs");
const utc = require("dayjs/plugin/utc");
const timezone = require("dayjs/plugin/timezone");

dayjs.extend(utc);
dayjs.extend(timezone);

/**
 * Convert UTC datetime to user's local time string
 * @param {string} utcDatetime - ISO 8601 UTC datetime
 * @param {string} userTimezone - IANA timezone (e.g. "Asia/Seoul")
 * @returns {string} formatted local time "HH:mm (tz)"
 */
function toLocalTime(utcDatetime, userTimezone) {
  const local = dayjs.utc(utcDatetime).tz(userTimezone);
  const tzAbbr = local.format("z");
  return `${local.format("HH:mm")} (${tzAbbr})`;
}

/**
 * Get user's timezone from Slack API response.
 * Falls back to DEFAULT_TIMEZONE env var (default "Asia/Seoul") if tz is not set.
 * Logs a warning so non-Korean users with missing tz don't silently get KST.
 * @param {Object} slackUserInfo - result of users.info API
 * @returns {string} IANA timezone string
 */
function getUserTimezone(slackUserInfo) {
  if (slackUserInfo?.tz) return slackUserInfo.tz;
  const fallback = process.env.DEFAULT_TIMEZONE || "Asia/Seoul";
  const userId = slackUserInfo?.id || "unknown";
  console.warn(
    `[Timezone] User ${userId} has no tz set in Slack profile — falling back to ${fallback}. ` +
    "Set DEFAULT_TIMEZONE env var to change the fallback."
  );
  return fallback;
}

/**
 * Calculate minutes until meeting starts from now
 * @param {string} utcStartTime - ISO 8601 UTC datetime
 * @returns {number} minutes until start (negative if past)
 */
function minutesUntilMeeting(utcStartTime) {
  const now = dayjs.utc();
  const start = dayjs.utc(utcStartTime);
  return start.diff(now, "minute");
}

/**
 * Calculate seconds until meeting starts from now (prevents integer truncation at boundary).
 * Returns NaN for invalid/missing input so callers can guard with Number.isFinite().
 * @param {string} utcStartTime - ISO 8601 UTC datetime
 * @returns {number} seconds until start, or NaN if input is invalid
 */
function minutesUntilMeetingSec(utcStartTime) {
  if (!utcStartTime) return NaN;
  const start = dayjs.utc(utcStartTime);
  if (!start.isValid()) return NaN;
  return start.diff(dayjs.utc(), "second");
}

module.exports = { toLocalTime, getUserTimezone, minutesUntilMeeting, minutesUntilMeetingSec };
