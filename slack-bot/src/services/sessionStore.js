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
  // Clear skip state so scheduler can send the alert after re-approval
  skippedMeetings.delete(meetingId);
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

function isApproved(meetingId) {
  return sessions.get(meetingId)?.status === "approved";
}

module.exports = { approve, skip, isSkipped, isApproved };
