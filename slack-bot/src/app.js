require("dotenv").config();
const express = require("express");
const { App } = require("@slack/bolt");

process.on("unhandledRejection", (reason) => {
  console.error("[Process] Unhandled rejection:", reason);
});

const { registerActionHandlers } = require("./handlers/actions");
const { startScheduler } = require("./services/scheduler");
const { getMeetings } = require("./services/calendar");
const { registerAuthRoutes } = require("./routes/auth");
const { isAuthenticated } = require("./services/calendar/auth");

// Socket Mode: Slack events come over WebSocket, not HTTP.
// A separate Express server handles Microsoft OAuth callback routes.
const app = new App({
  token: process.env.SLACK_BOT_TOKEN,
  appToken: process.env.SLACK_APP_TOKEN,
  signingSecret: process.env.SLACK_SIGNING_SECRET,
  socketMode: true,
});

registerActionHandlers(app);

// Standalone Express server for Microsoft OAuth routes (/auth/login, /auth/callback)
const httpApp = express();
registerAuthRoutes(httpApp);

(async () => {
  await app.start();
  console.log("[App] Slack bot connected via Socket Mode");

  const port = process.env.PORT || 3000;
  httpApp.listen(port, () => {
    console.log("[App] HTTP server listening on port", port);
  });

  if (!isAuthenticated()) {
    console.log("[App] Microsoft 인증 필요 → 브라우저에서 http://localhost:" + port + "/auth/login 접속");
  }

  startScheduler(app, () => getMeetings(app.client));
})();
