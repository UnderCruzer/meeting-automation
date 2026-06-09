const { fetchUpcomingEvents } = require("./graphClient");
const { parseOfflineMeetings } = require("./meetingParser");

/**
 * Get upcoming offline meetings from Microsoft Calendar
 * Used as the getMeetings() provider for the scheduler
 * @returns {Array} normalized meeting objects ready for scheduler
 */
async function getMeetings() {
  const events = await fetchUpcomingEvents(2);
  const meetings = parseOfflineMeetings(events);

  if (meetings.length > 0) {
    console.log(`[Calendar] Found ${meetings.length} offline meeting(s):`,
      meetings.map((m) => `"${m.title}" @ ${m.startTime}`)
    );
  }

  return meetings;
}

module.exports = { getMeetings };
