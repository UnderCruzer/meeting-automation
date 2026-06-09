const { buildAuthUrl, exchangeCode } = require("../services/calendar/auth");

/**
 * Register OAuth2 routes on the Express app
 * GET /auth/login  — redirect to Microsoft login
 * GET /auth/callback — exchange code for tokens
 */
function registerAuthRoutes(expressApp) {
  expressApp.get("/auth/login", (req, res) => {
    const { url } = buildAuthUrl();
    res.redirect(url);
  });

  expressApp.get("/auth/callback", async (req, res) => {
    const { code, error, error_description } = req.query;

    if (error) {
      console.error("[Auth] OAuth error:", error, error_description);
      return res.status(400).send(`Auth failed: ${error_description}`);
    }

    if (!code) {
      return res.status(400).send("Missing authorization code");
    }

    try {
      await exchangeCode(code);
      res.send("✅ 인증 완료! 창을 닫고 봇을 사용하세요.");
    } catch (err) {
      console.error("[Auth] Token exchange error:", err.message);
      res.status(500).send(`Token exchange failed: ${err.message}`);
    }
  });
}

module.exports = { registerAuthRoutes };
