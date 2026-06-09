/**
 * Register Slack action handlers for recording approval buttons
 * @param {Object} app - Slack Bolt app instance
 */
function registerActionHandlers(app) {
  app.action("approve_recording", async ({ ack, body, client }) => {
    await ack();

    const { meetingId } = JSON.parse(body.actions[0].value);
    const userId = body.user.id;

    // Update button message to confirmed state
    await client.chat.update({
      channel: body.channel.id,
      ts: body.message.ts,
      text: "녹음 세션이 준비되었습니다.",
      blocks: [
        {
          type: "section",
          text: {
            type: "mrkdwn",
            text: `✅ *녹음 준비 완료*\n잠시 후 녹음 페이지 링크를 전송해드립니다.`,
          },
        },
      ],
    });

    console.log(`[Action] User ${userId} approved recording for meeting ${meetingId}`);

    // TODO(issue-03): trigger recording page link delivery
  });

  app.action("skip_recording", async ({ ack, body, client }) => {
    await ack();

    const { meetingId } = JSON.parse(body.actions[0].value);
    const userId = body.user.id;

    await client.chat.update({
      channel: body.channel.id,
      ts: body.message.ts,
      text: "이번 회의 녹음을 건너뜁니다.",
      blocks: [
        {
          type: "section",
          text: {
            type: "mrkdwn",
            text: `⏭️ *이번 회의는 건너뜁니다.*`,
          },
        },
      ],
    });

    console.log(`[Action] User ${userId} skipped recording for meeting ${meetingId}`);
  });
}

module.exports = { registerActionHandlers };
