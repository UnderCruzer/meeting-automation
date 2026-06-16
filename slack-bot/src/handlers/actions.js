const { approve, skip, isApproved, getMeeting } = require("../services/sessionStore");

/**
 * Register Slack action handlers for recording approval buttons
 * @param {Object} app - Slack Bolt app instance
 */
function registerActionHandlers(app) {
  // No-op handler to silence Bolt warnings from Slack's link_button action event
  app.action("open_recording_page", async ({ ack }) => { await ack(); });

  app.action("approve_recording", handleAction("approve_recording", async ({ meetingId, userId, body, client }) => {
    // Idempotency guard: Slack retries can fire this handler twice
    if (isApproved(meetingId)) {
      console.warn(`[Action] approve_recording: meeting ${meetingId} already approved, skipping duplicate`);
      return;
    }

    approve(meetingId, userId);

    await updateMessage(client, body, {
      text: "녹음 세션이 준비되었습니다.",
      blockText: `✅ *녹음 준비 완료*\n잠시 후 녹음 페이지 링크를 전송해드립니다.`,
    });

    try {
      await sendRecordingLink(client, userId, meetingId);
      console.log(`[Action] Recording link sent to ${userId} for meeting ${meetingId}`);
    } catch (err) {
      console.error(`[Action] Failed to send recording link:`, err.message);
    }
    console.log(`[Action] User ${userId} approved recording for meeting ${meetingId}`);
  }));

  app.action("skip_recording", handleAction("skip_recording", async ({ meetingId, userId, body, client }) => {
    skip(meetingId, userId);

    await updateMessage(client, body, {
      text: "이번 회의 녹음을 건너뜁니다.",
      blockText: `⏭️ *이번 회의는 건너뜁니다.*`,
    });

    console.log(`[Action] User ${userId} skipped recording for meeting ${meetingId}`);
  }));
}

/**
 * Send Recording Web Page link as a DM to the user
 */
async function sendRecordingLink(client, userId, meetingId) {
  const base = process.env.RECORDING_PAGE_URL || "http://localhost:3001";
  const meeting = getMeeting(meetingId);
  const params = new URLSearchParams({ meetingId });
  if (meeting) {
    params.set("title", meeting.title ?? "");
    params.set("startTime", meeting.startTime ?? "");
    params.set("endTime", meeting.endTime ?? "");
    params.set("location", meeting.location ?? "");
  }
  const url = `${base}/record?${params}`;

  await client.chat.postMessage({
    channel: userId,
    text: `녹음 페이지: ${url}`,
    blocks: [
      {
        type: "section",
        text: {
          type: "mrkdwn",
          text: `*🎙️ 녹음 페이지*\n아래 링크를 열어 녹음을 시작하세요.\n회의 시작 시 자동으로 녹음이 시작됩니다.`,
        },
      },
      {
        type: "actions",
        elements: [
          {
            type: "button",
            text: { type: "plain_text", text: "녹음 페이지 열기", emoji: true },
            style: "primary",
            url,
            action_id: "open_recording_page",
          },
        ],
      },
    ],
  });
}

/**
 * Wrap action handler with ack, payload parsing, and error guard
 * Handles body.channel null (App Home / modal surfaces) and malformed JSON value
 */
function handleAction(actionId, handler) {
  return async ({ ack, body, client }) => {
    await ack();
    try {
      const action = body.actions?.[0];
      if (!action) {
        console.warn(`[Action] ${actionId}: empty actions array in payload`);
        return;
      }

      let parsed;
      try {
        parsed = JSON.parse(action.value);
      } catch {
        console.error(`[Action] ${actionId}: invalid JSON in action value:`, action.value);
        return;
      }

      await handler({ meetingId: parsed.meetingId, userId: body.user.id, body, client });
    } catch (err) {
      console.error(`[Action] ${actionId} handler error:`, err.message);
    }
  };
}

/**
 * Update the original DM message after action.
 * Falls back gracefully if channel is unavailable (App Home / modal contexts).
 */
async function updateMessage(client, body, { text, blockText }) {
  const channelId = body.channel?.id;
  if (!channelId) {
    console.warn("[Action] updateMessage: body.channel is null, skipping message update");
    return;
  }

  await client.chat.update({
    channel: channelId,
    ts: body.message.ts,
    text,
    blocks: [
      {
        type: "section",
        text: { type: "mrkdwn", text: blockText },
      },
    ],
  });
}

module.exports = { registerActionHandlers };
