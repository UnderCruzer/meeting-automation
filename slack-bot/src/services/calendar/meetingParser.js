/**
 * Filter and normalize Graph API events into meeting objects
 * Only returns offline meetings (has location, no online meeting link)
 * @param {Array} events - raw Graph API event list
 * @returns {Array} normalized meeting objects
 */
function parseOfflineMeetings(events) {
  return events
    .filter(isOfflineMeeting)
    .map(normalize);
}

function isOfflineMeeting(event) {
  const hasLocation = !!event.location?.displayName?.trim();
  const isOnline = event.isOnlineMeeting === true;
  return hasLocation && !isOnline;
}

function normalize(event) {
  return {
    id: event.id,
    title: event.subject ?? "(제목 없음)",
    startTime: toUtcIso(event.start.dateTime),
    endTime: toUtcIso(event.end.dateTime),
    location: event.location?.displayName ?? "",
    timezone: event.start.timeZone ?? "UTC",
    attendeeEmails: (event.attendees ?? []).map((a) => a.emailAddress?.address).filter(Boolean),
    // Slack IDs resolved separately via email lookup
    attendeeSlackIds: [],
  };
}

// Append Z only if Graph returned dateTime without timezone suffix (non-UTC calendars)
function toUtcIso(dateTime) {
  if (!dateTime) return dateTime;
  return dateTime.endsWith("Z") ? dateTime : dateTime + "Z";
}

module.exports = { parseOfflineMeetings };
