/** Types, labels and fetch helpers for the meeting workspace pages (browser). */

export type ActionItem = {
  description: string; assignee: string; due_date: string; priority?: "high" | "medium" | "low";
  citation_start?: number; citation_end?: number; citation_text: string;
  /** Resolved by the server from due_date (ISO date) — null when the text isn't a date. */
  due?: string | null;
  done?: boolean; done_by?: string | null; done_at?: string | null;
};

/** D-day label and tone for a resolved due date, relative to today (local). */
export function dueState(due?: string | null, done?: boolean): { label: string; tone: string } | null {
  if (!due || done) return null;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = Math.round((new Date(`${due}T00:00:00`).getTime() - today.getTime()) / 86_400_000);
  if (days < 0) return { label: `${-days}일 지남`, tone: "badge-danger" };
  if (days === 0) return { label: "오늘", tone: "badge-warning" };
  if (days === 1) return { label: "내일", tone: "badge-accent" };
  return { label: `D-${days}`, tone: "" };
}

export type ArtifactStatus = "queued" | "sent" | "failed" | null;
export type JiraDraft = {
  action: "create" | "comment"; existing_key: string; summary: string; description: string; priority: string;
  include: boolean; result?: { action: string; key: string; url: string } | null;
};
/** Jira / Confluence search results and drafts kept with the meeting (workflow 10·12·13). */
export type Drafts = {
  related: { source: "jira" | "confluence" | "slack"; id: string; title: string; url: string; snippet: string; status?: string }[];
  jira?: { drafts: JiraDraft[]; status: ArtifactStatus; error: string | null; generation_error: string | null };
  confluence?: { title: string; include: boolean; status: ArtifactStatus; error: string | null;
    result: { page_id: string; title: string; url: string } | null };
};
export type Integrations = { slack: boolean; jira: boolean; confluence: boolean };

/** Only links to the Atlassian site the server built — never javascript: or other schemes. */
export const safeUrl = (url?: string | null) => (url && /^https:\/\//.test(url) ? url : undefined);

export type Job = {
  id: string; title: string; status: "processing" | "review" | "approved" | "rejected" | "failed";
  uploaded_by?: string | null; decided_by?: string | null; decided_at?: string | null; created_at?: string;
  publish_status?: "queued" | "scheduled" | "sent" | "failed" | null; publish_at?: string | null;
  published_at?: string | null; publish_error?: string | null;
  error_code?: string | null; can_retry?: boolean;
  drafts?: Drafts | null;
  summary: null | {
    summary_ko: string; decisions: { text: string }[]; action_items: ActionItem[]; quality_flags: { message: string }[];
  };
};

export const FAILURE_REASONS: Record<string, string> = {
  LLM_BUSY: "AI 분석 서비스가 일시적으로 혼잡했습니다. 잠시 후 \"다시 분석\"을 눌러주세요.",
  ANALYSIS_FAILED: "AI 분석 결과를 처리하지 못했습니다. \"다시 분석\"을 눌러보고, 반복되면 관리자에게 알려주세요.",
  STT_FAILED: "음성을 텍스트로 바꾸지 못했습니다. 잠시 후 녹음을 다시 올려주세요.",
  NO_SPEECH: "녹음에서 말소리를 찾지 못했습니다. 다른 파일로 다시 올려주세요.",
  RESTARTED: "처리 중 서버가 다시 시작되었습니다. 녹음을 다시 올려주세요.",
};

export const SLACK_HINTS: Record<string, string> = {
  not_in_channel: "봇이 채널에 없습니다. 채널에서 /invite @앱이름 으로 초대한 뒤 다시 게시하세요.",
  channel_not_found: "채널을 찾지 못했습니다. SLACK_BRIEF_CHANNEL에 채널 ID(C0…)를 넣고, 비공개 채널이면 봇을 먼저 초대하세요.",
  invalid_auth: "Slack 토큰이 올바르지 않습니다. xoxb- 로 시작하는 Bot User OAuth Token인지 확인하세요.",
  not_authed: "Slack 토큰이 설정되지 않았습니다.",
  no_token: "Slack 토큰이 설정되지 않았습니다.",
  missing_scope: "앱에 chat:write 권한이 없습니다. 권한을 추가하고 앱을 다시 설치하세요.",
  account_inactive: "Slack 앱 또는 토큰이 비활성화되었습니다. 앱을 다시 설치하세요.",
  is_archived: "보관 처리된 채널입니다. 다른 채널을 지정하세요.",
  ratelimited: "Slack 요청 한도에 걸렸습니다. 잠시 후 다시 게시하세요.",
};

/** SQLite "YYYY-MM-DD HH:MM:SS" (UTC) or ISO string → local "10월 1일 14:36". */
export function formatWhen(value?: string | null): string {
  if (!value) return "";
  const iso = /Z$|[+-]\d\d:?\d\d$/.test(value) ? value : value.replace(" ", "T") + "Z";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}

export function displayActor(actor?: string | null): string {
  if (!actor) return "알 수 없음";
  return actor.startsWith("slack:") ? `Slack ${actor.slice(6)}` : actor;
}

/** fetch + JSON with the server's Korean error message surfaced as an Error. */
export async function api<T = unknown>(path: string, init?: RequestInit, fallback = "요청을 처리하지 못했습니다."): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : fallback);
  return body as T;
}

export const jsonInit = (method: string, body: unknown): RequestInit =>
  ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
