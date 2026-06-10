const { buildAuthUrl, exchangeCode } = require("../services/calendar/auth");

// In-memory CSRF state store (single-user bot — one pending login at a time)
let pendingState = null;

/**
 * Register OAuth2 routes on the Express app
 * GET /auth/login    — redirect to Microsoft login
 * GET /auth/callback — verify state, exchange code for tokens
 */
function registerAuthRoutes(router) {
  router.get("/auth/login", (req, res) => {
    const { url, state } = buildAuthUrl();
    pendingState = state;
    res.redirect(url);
  });

  router.get("/auth/callback", async (req, res) => {
    const { code, state, error, error_description } = req.query;

    if (error) {
      console.error("[Auth] OAuth error:", error, error_description);
      return res.status(400).send(`Auth failed: ${error_description}`);
    }

    if (!code) {
      return res.status(400).send("Missing authorization code");
    }

    // CSRF guard: reject callbacks whose state doesn't match the login request
    if (!pendingState || state !== pendingState) {
      console.error("[Auth] State mismatch — possible CSRF attempt");
      pendingState = null;
      return res.status(403).send("Invalid state parameter");
    }
    pendingState = null;

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
