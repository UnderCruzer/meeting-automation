const { fetchUpcomingEvents } = require("./graphClient");
const { parseOfflineMeetings } = require("./meetingParser");
const { isAuthenticated } = require("./auth");
const { resolveSlackIds } = require("./slackLookup");
const { fetchIcsMeetings, icsUrls } = require("./ics");

/**
 * Get upcoming meetings from ICS subscriptions (Google/Outlook) and, if signed in,
 * Microsoft Graph. Graph keeps its offline-only rule; ICS meetings need a location
 * unless CALENDAR_INCLUDE_ONLINE=true (online meetings usually have their own recording).
 * @param {Object} slackClient - Slack WebClient for email → Slack ID lookup
 * @returns {Array} normalized meeting objects ready for scheduler
 */
async function getMeetings(slackClient) {
  const meetings = [];
  if (isAuthenticated()) {
    meetings.push(...parseOfflineMeetings(await fetchUpcomingEvents(2)));
  }
  if (icsUrls().length) {
    const includeOnline = process.env.CALENDAR_INCLUDE_ONLINE === "true";
    meetings.push(...(await fetchIcsMeetings(2)).filter((m) => includeOnline || m.location));
  }

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
