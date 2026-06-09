require("dotenv").config();
const { App } = require("@slack/bolt");

process.on("unhandledRejection", (reason) => {
  console.error("[Process] Unhandled rejection:", reason);
});
const { registerActionHandlers } = require("./handlers/actions");
const { startScheduler } = require("./services/scheduler");

const app = new App({
  token: process.env.SLACK_BOT_TOKEN,
  appToken: process.env.SLACK_APP_TOKEN,
  signingSecret: process.env.SLACK_SIGNING_SECRET,
  socketMode: true,
});

registerActionHandlers(app);

// Stub: replace with real calendar integration (issue-01)
async function getMeetings() {
  return [
    // {
    //   id: "meeting-001",
    //   title: "GPD2 주간 회의",
    //   startTime: "2026-06-09T06:00:00Z", // UTC
    //   endTime: "2026-06-09T07:00:00Z",
    //   location: "미팅룸 A",
    //   attendeeSlackIds: ["U_EXAMPLE_ID"],
    // },
  ];
}

(async () => {
  await app.start();
  console.log("[App] Slack bot started (Socket Mode)");

  startScheduler(app, getMeetings);
})();
