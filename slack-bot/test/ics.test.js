const test = require("node:test");
const assert = require("node:assert");
const ical = require("node-ical");
const { meetingsFromIcs, fetchIcsMeetings } = require("../src/services/calendar/ics");

const ICS = `BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:weekly-1
DTSTART;TZID=Asia/Seoul:20260928T150000
DTEND;TZID=Asia/Seoul:20260928T160000
RRULE:FREQ=WEEKLY;BYDAY=MO,TH
EXDATE;TZID=Asia/Seoul:20261005T150000
SUMMARY:주간 회의
LOCATION:회의실 A
ORGANIZER;CN=Kim:mailto:Kim@Example.com
ATTENDEE;CN=Park:mailto:park@example.com
ATTENDEE;CN=Kim:mailto:kim@example.com
END:VEVENT
BEGIN:VEVENT
UID:online-1
DTSTART:20261001T070000Z
DTEND:20261001T073000Z
SUMMARY:온라인 싱크
ATTENDEE:mailto:lee@example.com
END:VEVENT
BEGIN:VEVENT
UID:allday-1
DTSTART;VALUE=DATE:20261001
DTEND;VALUE=DATE:20261002
SUMMARY:개천절 준비
END:VEVENT
BEGIN:VEVENT
UID:cancelled-1
DTSTART:20261001T080000Z
DTEND:20261001T090000Z
STATUS:CANCELLED
SUMMARY:취소된 회의
END:VEVENT
END:VCALENDAR`;

const parse = () => ical.sync.parseICS(ICS);

test("recurring instance in window with attendees de-duplicated", () => {
  const meetings = meetingsFromIcs(parse(), new Date("2026-10-01T00:00:00Z"), new Date("2026-10-01T12:00:00Z"));
  const weekly = meetings.find((m) => m.title === "주간 회의");
  assert.strictEqual(weekly.startTime, "2026-10-01T06:00:00.000Z"); // Thu 15:00 KST
  assert.strictEqual(weekly.endTime, "2026-10-01T07:00:00.000Z");
  assert.strictEqual(weekly.location, "회의실 A");
  assert.strictEqual(weekly.timezone, "Asia/Seoul");
  assert.deepStrictEqual(weekly.attendeeEmails.sort(), ["kim@example.com", "park@example.com"]);
  assert.strictEqual(weekly.id, "ics:weekly-1:2026-10-01T06:00:00.000Z");
});

test("all-day and cancelled events are skipped, online kept for caller filtering", () => {
  const titles = meetingsFromIcs(parse(), new Date("2026-10-01T00:00:00Z"), new Date("2026-10-01T12:00:00Z"))
    .map((m) => m.title).sort();
  assert.deepStrictEqual(titles, ["온라인 싱크", "주간 회의"]);
});

test("EXDATE removes that occurrence", () => {
  const meetings = meetingsFromIcs(parse(), new Date("2026-10-05T00:00:00Z"), new Date("2026-10-05T12:00:00Z"));
  assert.strictEqual(meetings.filter((m) => m.title === "주간 회의").length, 0);
});

test("fetch failures are reported without the secret URL", async (t) => {
  process.env.CALENDAR_ICS_URLS = "https://calendar.example/private-SECRET/basic.ics";
  const errors = [];
  t.mock.method(console, "error", (...args) => errors.push(args.join(" ")));
  t.mock.method(globalThis, "fetch", async () => new Response("nope", { status: 404 }));
  const meetings = await fetchIcsMeetings(2, new Date("2026-10-01T05:00:00Z"));
  assert.deepStrictEqual(meetings, []);
  assert.ok(errors.length === 1 && !errors[0].includes("SECRET"));
  delete process.env.CALENDAR_ICS_URLS;
});

test("fetch success returns window meetings", async (t) => {
  process.env.CALENDAR_ICS_URLS = "https://calendar.example/a.ics";
  t.mock.method(globalThis, "fetch", async () => new Response(ICS, { status: 200 }));
  const meetings = await fetchIcsMeetings(2, new Date("2026-10-01T05:00:00Z"));
  assert.deepStrictEqual(meetings.map((m) => m.title).sort(), ["온라인 싱크", "주간 회의"]);
  delete process.env.CALENDAR_ICS_URLS;
});
