/**
 * In-memory session store for recording approval state per meeting.
 * Tracks: pending | approved | skipped
 */

// meetingId → { status, userId, approvedAt }
const sessions = new Map();

// meetingIds skipped by user — scheduler checks before sending DM
const skippedMeetings = new Set();

function approve(meetingId, userId) {
  sessions.set(meetingId, { status: "approved", userId, approvedAt: Date.now() });
}

function skip(meetingId, userId) {
  sessions.set(meetingId, { status: "skipped", userId, skippedAt: Date.now() });
  skippedMeetings.add(meetingId);
}

function getSession(meetingId) {
  return sessions.get(meetingId) ?? null;
}

function isSkipped(meetingId) {
  return skippedMeetings.has(meetingId);
}

module.exports = { approve, skip, getSession, isSkipped };
