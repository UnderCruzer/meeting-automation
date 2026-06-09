const { getAccessToken } = require("./auth");

const GRAPH_BASE = "https://graph.microsoft.com/v1.0";

/**
 * Fetch upcoming calendar events within the next N hours
 * @param {number} hoursAhead - how many hours ahead to look
 * @returns {Array} raw Graph API event objects
 */
async function fetchUpcomingEvents(hoursAhead = 2) {
  const token = await getAccessToken();

  const now = new Date();
  const end = new Date(now.getTime() + hoursAhead * 60 * 60 * 1000);

  const params = new URLSearchParams({
    startDateTime: now.toISOString(),
    endDateTime: end.toISOString(),
    $select: "id,subject,start,end,location,attendees,isOnlineMeeting,onlineMeeting",
    $top: "20",
    // $orderby is not supported on calendarView — results are already ordered by start time
  });

  const res = await fetch(`${GRAPH_BASE}/me/calendarView?${params}`, {
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Prefer: `outlook.timezone="UTC"`,
    },
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Graph API error: ${res.status} ${err}`);
  }

  const data = await res.json();
  return data.value ?? [];
}

module.exports = { fetchUpcomingEvents };
