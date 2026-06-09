require("dotenv").config();
const express = require("express");
const { App, ExpressReceiver } = require("@slack/bolt");

process.on("unhandledRejection", (reason) => {
  console.error("[Process] Unhandled rejection:", reason);
});

const { registerActionHandlers } = require("./handlers/actions");
const { startScheduler } = require("./services/scheduler");
const { getMeetings } = require("./services/calendar");
const { registerAuthRoutes } = require("./routes/auth");
const { isAuthenticated } = require("./services/calendar/auth");

// ExpressReceiver handles HTTP (OAuth routes).
// socketMode:true connects to Slack over WebSocket — no conflict when receiver is also provided.
const receiver = new ExpressReceiver({
  signingSecret: process.env.SLACK_SIGNING_SECRET,
});

const app = new App({
  token: process.env.SLACK_BOT_TOKEN,
  appToken: process.env.SLACK_APP_TOKEN,
  receiver,
  socketMode: true,
});

registerActionHandlers(app);
registerAuthRoutes(receiver.router);

(async () => {
  await app.start(process.env.PORT || 3000);
  console.log("[App] Slack bot started on port", process.env.PORT || 3000);

  if (!isAuthenticated()) {
    console.log("[App] Microsoft 인증 필요 → 브라우저에서 http://localhost:3000/auth/login 접속");
  }

  // Only start scheduler after auth is confirmed; otherwise guard inside getMeetings handles it
  startScheduler(app, () => getMeetings(app.client));
})();
