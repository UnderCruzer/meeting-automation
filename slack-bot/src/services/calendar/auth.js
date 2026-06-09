const crypto = require("crypto");

const CLIENT_ID = process.env.AZURE_CLIENT_ID;
const REDIRECT_URI = process.env.AZURE_REDIRECT_URI || "http://localhost:3000/auth/callback";
const SCOPES = ["Calendars.Read", "User.Read", "offline_access"].join(" ");

// Personal account endpoint
const AUTHORITY = "https://login.microsoftonline.com/consumers";

// In-memory token store — replace with persistent store in production
let tokenStore = null;

/**
 * Build the OAuth2 authorization URL for user login
 * @returns {{ url: string, state: string }}
 */
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

/**
 * Exchange authorization code for access + refresh tokens
 * @param {string} code - auth code from redirect callback
 * @returns {Object} token response
 */
async function exchangeCode(code) {
  const body = new URLSearchParams({
    client_id: CLIENT_ID,
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

  console.log("[Auth] Tokens acquired and stored");
  return tokenStore;
}

// In-flight refresh promise — prevents concurrent refresh with stale refresh token
let refreshInFlight = null;

/**
 * Get a valid access token, refreshing if expired.
 * Concurrent callers share the same in-flight refresh promise.
 * @returns {string} access token
 */
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

  console.log("[Auth] Token refreshed");
  return tokenStore.accessToken;
}

function isAuthenticated() {
  return tokenStore !== null;
}

module.exports = { buildAuthUrl, exchangeCode, getAccessToken, isAuthenticated };
