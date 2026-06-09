const cron = require("node-cron");
const { minutesUntilMeetingSec, toLocalTime, getUserTimezone } = require("./timezone");
const { buildDmAlertMessage } = require("../messages/dmAlert");

const ALERT_BEFORE_MINUTES = 5; // 회의 시작 N분 전에 DM 발송
const CHECK_INTERVAL_MINUTES = 1; // 매 N분마다 회의 체크

/**
 * Start the meeting alert scheduler
 * Checks pending meetings every minute and sends DM when within alert window
 * @param {Object} app - Slack Bolt app instance
 * @param {Function} getMeetings - async fn returning upcoming meeting list
 */
function startScheduler(app, getMeetings) {
  // Track sent alerts to prevent duplicates
  const sentAlerts = new Set();

  cron.schedule(`*/${CHECK_INTERVAL_MINUTES} * * * *`, async () => {
    try {
      const meetings = await getMeetings();

      for (const meeting of meetings) {
        // Use seconds-precision diff to avoid integer truncation dropping boundary meetings.
        // e.g. 4m59s → minutesLeftSec=299, threshold=300 → still within window.
        const minutesLeftSec = minutesUntilMeetingSec(meeting.startTime);
        const windowUpperSec = ALERT_BEFORE_MINUTES * 60;
        const windowLowerSec = (ALERT_BEFORE_MINUTES - CHECK_INTERVAL_MINUTES) * 60;
        const inAlertWindow =
          Number.isFinite(minutesLeftSec) &&
          minutesLeftSec <= windowUpperSec &&
          minutesLeftSec > windowLowerSec;

        if (!inAlertWindow || sentAlerts.has(meeting.id)) continue;

        const results = await Promise.allSettled(
          meeting.attendeeSlackIds.map((id) => sendDmAlert(app, id, meeting))
        );

        const allFailed = results.every((r) => r.status === "rejected");
        if (!allFailed) {
          // Only mark as sent when at least one DM succeeded, allowing retry for full failures
          sentAlerts.add(meeting.id);
        }
      }
    } catch (err) {
      console.error("[Scheduler] Error checking meetings:", err.message);
    }
  });

  console.log(`[Scheduler] Started — checking every ${CHECK_INTERVAL_MINUTES}min, alert ${ALERT_BEFORE_MINUTES}min before`);
}

/**
 * Send DM alert to a single Slack user
 * @param {Object} app - Slack Bolt app instance
 * @param {string} slackUserId - Slack user ID
 * @param {Object} meeting - meeting metadata
 */
async function sendDmAlert(app, slackUserId, meeting) {
  try {
    const userInfo = await app.client.users.info({ user: slackUserId });
    const userTz = getUserTimezone(userInfo.user);
    const localTime = toLocalTime(meeting.startTime, userTz);

    const message = buildDmAlertMessage({ ...meeting, localTime });

    await app.client.chat.postMessage({
      channel: slackUserId, // DM: user ID를 channel로 사용
      ...message,
    });

    console.log(`[Scheduler] DM sent to ${slackUserId} for meeting "${meeting.title}"`);
  } catch (err) {
    console.error(`[Scheduler] Failed to send DM to ${slackUserId}:`, err.message);
  }
}

module.exports = { startScheduler, sendDmAlert };
