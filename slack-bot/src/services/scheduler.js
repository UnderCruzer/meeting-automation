const cron = require("node-cron");
const { minutesUntilMeeting, toLocalTime, getUserTimezone } = require("./timezone");
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
        const minutesLeft = minutesUntilMeeting(meeting.startTime);

        // Send alert in the window: ALERT_BEFORE_MINUTES to ALERT_BEFORE_MINUTES+1
        const inAlertWindow =
          minutesLeft <= ALERT_BEFORE_MINUTES &&
          minutesLeft > ALERT_BEFORE_MINUTES - CHECK_INTERVAL_MINUTES;

        if (!inAlertWindow || sentAlerts.has(meeting.id)) continue;

        for (const attendeeSlackId of meeting.attendeeSlackIds) {
          await sendDmAlert(app, attendeeSlackId, meeting);
        }

        sentAlerts.add(meeting.id);
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
