/**
 * In-memory session store for recording approval state per meeting.
 * Tracks: pending | approved | skipped
 */

// meetingId → { status, userId, approvedAt, meeting }
const sessions = new Map();

// meetingId → meeting metadata (set by scheduler before sending DM)
const meetingMeta = new Map();

// meetingIds skipped by user — scheduler checks before sending DM
const skippedMeetings = new Set();

function storeMeeting(meeting) {
  meetingMeta.set(meeting.id, meeting);
}

function getMeeting(meetingId) {
  return meetingMeta.get(meetingId) ?? null;
}

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

module.exports = { approve, skip, isSkipped, isApproved, storeMeeting, getMeeting };
