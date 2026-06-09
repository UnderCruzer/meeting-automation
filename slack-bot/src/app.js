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

const receiver = new ExpressReceiver({
  signingSecret: process.env.SLACK_SIGNING_SECRET,
  app: express(),
});

const app = new App({
  token: process.env.SLACK_BOT_TOKEN,
  appToken: process.env.SLACK_APP_TOKEN,
  receiver,
  socketMode: true,
});

registerActionHandlers(app);
registerAuthRoutes(receiver.app);

(async () => {
  await app.start(process.env.PORT || 3000);
  console.log("[App] Slack bot started (Socket Mode) on port", process.env.PORT || 3000);

  if (!isAuthenticated()) {
    console.log("[App] Microsoft 인증 필요 → 브라우저에서 http://localhost:3000/auth/login 접속");
  }

  startScheduler(app, getMeetings);
})();
