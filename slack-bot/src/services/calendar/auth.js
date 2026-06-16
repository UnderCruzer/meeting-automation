const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const CLIENT_ID = process.env.AZURE_CLIENT_ID;
const REDIRECT_URI = process.env.AZURE_REDIRECT_URI || "http://localhost:3000/auth/callback";
const SCOPES = ["Calendars.Read", "User.Read", "offline_access"].join(" ");

const AUTHORITY = "https://login.microsoftonline.com/consumers";

const TOKEN_PATH = path.join(__dirname, "../../../../data/token.json");

let tokenStore = null;

function _loadToken() {
  try {
    if (fs.existsSync(TOKEN_PATH)) {
      tokenStore = JSON.parse(fs.readFileSync(TOKEN_PATH, "utf8"));
      console.log("[Auth] Token loaded from disk");
    }
  } catch {
    tokenStore = null;
  }
}

function _saveToken() {
  try {
    fs.mkdirSync(path.dirname(TOKEN_PATH), { recursive: true });
    fs.writeFileSync(TOKEN_PATH, JSON.stringify(tokenStore), "utf8");
  } catch (e) {
    console.error("[Auth] Failed to save token:", e.message);
  }
}

_loadToken();

function buildAuthUrl() {
  const state = crypto.randomBytes(16).toString("hex");
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    response_type: "code",
    redirect_uri: REDIRECT_URI,
    scope: SCOPES,
    response_mode: "query",
    state,
  });

  return {
    url: `${AUTHORITY}/oauth2/v2.0/authorize?${params}`,
    state,
  };
}

async function exchangeCode(code) {
  const body = new URLSearchParams({
    client_id: CLIENT_ID,
    client_secret: process.env.AZURE_CLIENT_SECRET || "",
    grant_type: "authorization_code",
    code,
    redirect_uri: REDIRECT_URI,
    scope: SCOPES,
  });

  const res = await fetch(`${AUTHORITY}/oauth2/v2.0/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Token exchange failed: ${err}`);
  }

  const tokens = await res.json();
  tokenStore = {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    expiresAt: Date.now() + tokens.expires_in * 1000,
  };

  _saveToken();
  console.log("[Auth] Tokens acquired and stored");
  return tokenStore;
}

let refreshInFlight = null;

async function getAccessToken() {
  if (!tokenStore) throw new Error("Not authenticated. Visit /auth/login first.");

  if (Date.now() < tokenStore.expiresAt - 60_000) {
    return tokenStore.accessToken;
  }

  if (!refreshInFlight) {
    refreshInFlight = doRefresh().finally(() => { refreshInFlight = null; });
  }

  return refreshInFlight;
}

async function doRefresh() {
  const body = new URLSearchParams({
    client_id: process.env.AZURE_CLIENT_ID,
    client_secret: process.env.AZURE_CLIENT_SECRET || "",
    grant_type: "refresh_token",
    refresh_token: tokenStore.refreshToken,
    scope: SCOPES,
  });

  const res = await fetch(`${AUTHORITY}/oauth2/v2.0/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Token refresh failed: ${err}`);
  }

  const tokens = await res.json();
  tokenStore = {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token ?? tokenStore.refreshToken,
    expiresAt: Date.now() + tokens.expires_in * 1000,
  };

  _saveToken();
  console.log("[Auth] Token refreshed");
  return tokenStore.accessToken;
}

function isAuthenticated() {
  return tokenStore !== null;
}

module.exports = { buildAuthUrl, exchangeCode, getAccessToken, isAuthenticated };
