/**
 * Persistent Alert Store — Issue #23
 *
 * sentAlerts가 in-memory Set이면 프로세스 재시작 시 초기화돼
 * 알림 윈도우 내 재시작 시 중복 DM이 발송됨.
 *
 * MVP 해결책: JSON 파일에 {meetingId → expiresAt} 맵을 저장.
 * TTL: 회의 시작 후 1시간 자동 만료.
 * Redis 도입 시 이 모듈만 교체하면 됨.
 */
const fs = require("fs");
const path = require("path");

const STORE_PATH = path.resolve(
  process.env.ALERT_STORE_PATH || path.join(__dirname, "../../../data/sent_alerts.json")
);
const TTL_MS = 60 * 60 * 1000; // 1시간

/** @returns {{ [meetingId: string]: number }} expiresAt (epoch ms) */
function _load() {
  try {
    if (!fs.existsSync(STORE_PATH)) return {};
    return JSON.parse(fs.readFileSync(STORE_PATH, "utf-8"));
  } catch (err) {
    console.warn("[AlertStore] Failed to load store — starting fresh:", err.message);
    return {};
  }
}

function _save(store) {
  try {
    fs.mkdirSync(path.dirname(STORE_PATH), { recursive: true });
    fs.writeFileSync(STORE_PATH, JSON.stringify(store, null, 2), "utf-8");
  } catch (err) {
    console.error("[AlertStore] Failed to persist store:", err.message);
  }
}

/**
 * Check whether an alert has already been sent for this meeting.
 * Automatically purges expired entries.
 * @param {string} meetingId
 * @returns {boolean}
 */
function hasSent(meetingId) {
  const store = _load();
  const now = Date.now();

  // Purge expired entries while we have the store loaded
  let dirty = false;
  for (const [id, expiresAt] of Object.entries(store)) {
    if (expiresAt < now) {
      delete store[id];
      dirty = true;
    }
  }
  if (dirty) _save(store);

  return Object.prototype.hasOwnProperty.call(store, meetingId) && store[meetingId] > now;
}

/**
 * Mark an alert as sent for this meeting.
 * TTL starts from now (regardless of meeting start time).
 * @param {string} meetingId
 */
function markSent(meetingId) {
  const store = _load();
  store[meetingId] = Date.now() + TTL_MS;
  _save(store);
}

module.exports = { hasSent, markSent };
