const { fetchUpcomingEvents } = require("./graphClient");
const { parseOfflineMeetings } = require("./meetingParser");
const { isAuthenticated } = require("./auth");
const { resolveSlackIds } = require("./slackLookup");

/**
 * Get upcoming offline meetings from Microsoft Calendar.
 * Returns [] silently if not yet authenticated (avoids error-per-minute log spam).
 * @param {Object} slackClient - Slack WebClient for email → Slack ID lookup
 * @returns {Array} normalized meeting objects ready for scheduler
 */
async function getMeetings(slackClient) {
  if (!isAuthenticated()) return [];

  const events = await fetchUpcomingEvents(2);
  const meetings = parseOfflineMeetings(events);

  // Resolve attendee emails → Slack IDs so scheduler can send DMs
  await Promise.all(
    meetings.map(async (meeting) => {
      meeting.attendeeSlackIds = await resolveSlackIds(slackClient, meeting.attendeeEmails);
    })
  );

  if (meetings.length > 0) {
    console.log(
      `[Calendar] Found ${meetings.length} offline meeting(s):`,
      meetings.map((m) => `"${m.title}" @ ${m.startTime} (${m.attendeeSlackIds.length} Slack users)`)
    );
  }

  return meetings;
}

module.exports = { getMeetings };
