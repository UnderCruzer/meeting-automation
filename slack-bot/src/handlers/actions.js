/**
 * Register Slack action handlers for recording approval buttons
 * @param {Object} app - Slack Bolt app instance
 */
function registerActionHandlers(app) {
  app.action("approve_recording", handleAction("approve_recording", async ({ meetingId, userId, body, client }) => {
    await updateMessage(client, body, {
      text: "녹음 세션이 준비되었습니다.",
      blockText: `✅ *녹음 준비 완료*\n잠시 후 녹음 페이지 링크를 전송해드립니다.`,
    });
    console.log(`[Action] User ${userId} approved recording for meeting ${meetingId}`);
    // TODO(issue-03): trigger recording page link delivery
  }));

  app.action("skip_recording", handleAction("skip_recording", async ({ meetingId, userId, body, client }) => {
    await updateMessage(client, body, {
      text: "이번 회의 녹음을 건너뜁니다.",
      blockText: `⏭️ *이번 회의는 건너뜁니다.*`,
    });
    console.log(`[Action] User ${userId} skipped recording for meeting ${meetingId}`);
  }));
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
