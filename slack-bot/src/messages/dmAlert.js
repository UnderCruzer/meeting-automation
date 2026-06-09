/**
 * Build Block Kit DM message for recording approval
 * @param {Object} meeting - { title, startTime, endTime, location, localTime }
 * @returns {Object} Slack Block Kit payload
 */
function buildDmAlertMessage(meeting) {
  const { title, startTime, endTime, location, localTime } = meeting;

  return {
    text: `📅 ${localTime}에 "${title}" 회의가 있습니다. 녹음 세션을 준비할까요?`,
    blocks: [
      {
        type: "section",
        text: {
          type: "mrkdwn",
          text: `*📅 회의 알림*\n곧 회의가 시작됩니다. 녹음 세션을 준비할까요?`,
        },
      },
      {
        type: "divider",
      },
      {
        type: "section",
        fields: [
          {
            type: "mrkdwn",
            text: `*회의명*\n${title}`,
          },
          {
            type: "mrkdwn",
            text: `*장소*\n${location || "미지정"}`,
          },
          {
            type: "mrkdwn",
            text: `*시간*\n${startTime} ~ ${endTime}`,
          },
          {
            type: "mrkdwn",
            text: `*현지 시간*\n${localTime}`,
          },
        ],
      },
      {
        type: "actions",
        block_id: "recording_approval",
        elements: [
          {
            type: "button",
            text: { type: "plain_text", text: "🔴 녹음 준비", emoji: true },
            style: "primary",
            action_id: "approve_recording",
            value: JSON.stringify({ meetingId: meeting.id }),
          },
          {
            type: "button",
            text: { type: "plain_text", text: "건너뛰기", emoji: true },
            action_id: "skip_recording",
            value: JSON.stringify({ meetingId: meeting.id }),
          },
        ],
      },
    ],
  };
}

module.exports = { buildDmAlertMessage };
