/**
 * ICS calendar subscriptions — Google "secret address in iCal format" or Outlook
 * "published calendar" links. No OAuth needed; recurring events, EXDATE and
 * per-instance overrides are expanded by node-ical.
 *
 * CALENDAR_ICS_URLS: comma-separated list. Each URL is a secret — never log it.
 */
const ical = require("node-ical");

const FETCH_TIMEOUT_MS = 15_000;

function icsUrls() {
  return (process.env.CALENDAR_ICS_URLS || "")
    .split(",")
    .map((u) => u.trim())
    .filter(Boolean);
}

function emailOf(person) {
  const value = typeof person === "string" ? person : person?.val;
  const match = /^mailto:(.+)$/i.exec(value || "");
  return match ? match[1].trim().toLowerCase() : null;
}

function asList(value) {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

function textOf(value) {
  return (typeof value === "string" ? value : value?.val ?? "").trim();
}

/**
 * Normalize ICS data into the scheduler's meeting shape for the [from, to] window.
 * @param {Object} data - node-ical parse result
 */
function meetingsFromIcs(data, from, to) {
  const meetings = [];
  for (const event of Object.values(data)) {
    if (event.type !== "VEVENT" || event.status === "CANCELLED") continue;
    for (const instance of ical.expandRecurringEvent(event, { from, to })) {
      if (instance.isFullDay) continue;  // all-day items are not meetings to record
      const source = instance.event || event;  // override instances carry their own fields
      const attendeeEmails = [...new Set(
        [source.organizer, ...asList(source.attendee)].map(emailOf).filter(Boolean),
      )];
      meetings.push({
        // Instance-specific id so each occurrence of a recurring meeting alerts once.
        id: `ics:${event.uid}:${instance.start.toISOString()}`,
        title: textOf(instance.summary) || "(제목 없음)",
        startTime: instance.start.toISOString(),
        endTime: instance.end.toISOString(),
        location: textOf(source.location),
        timezone: event.start?.tz || "UTC",
        attendeeEmails,
        attendeeSlackIds: [],
      });
    }
  }
  return meetings;
}

async function fetchIcsMeetings(hoursAhead = 2, now = new Date()) {
  const to = new Date(now.getTime() + hoursAhead * 60 * 60 * 1000);
  const results = await Promise.allSettled(
    icsUrls().map(async (url, index) => {
      const res = await fetch(url, { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) });
      if (!res.ok) throw new Error(`calendar #${index + 1} HTTP ${res.status}`);
      return meetingsFromIcs(ical.sync.parseICS(await res.text()), now, to);
    }),
  );
  const meetings = [];
  results.forEach((r, index) => {
    if (r.status === "fulfilled") meetings.push(...r.value);
    // Report by index only: the URL itself is a credential.
    else console.error(`[Calendar] ICS calendar #${index + 1} failed:`, r.reason?.message);
  });
  return meetings;
}

module.exports = { fetchIcsMeetings, meetingsFromIcs, icsUrls };
