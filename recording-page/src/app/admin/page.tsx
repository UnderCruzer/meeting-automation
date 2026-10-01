"use client";
import { useCallback, useEffect, useState } from "react";
import AppShell, { type Me } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import MetricsPanel from "@/components/MetricsPanel";
import { api, displayActor, formatWhen, jsonInit } from "@/lib/workspace";

type User = { id: number; username: string; role: "admin" | "member"; active: boolean; mustChangePassword: boolean };
type AuditEvent = { id: number; at: string; username: string | null; action: string; title: string | null; detail: string | null; ip: string | null };

const ACTIONS: Record<string, string> = {
  login: "로그인", login_failed: "로그인 실패", logout: "로그아웃", password_change: "비밀번호 변경",
  user_create: "사용자 추가", user_update: "사용자 변경", upload: "업로드", approve: "승인", reject: "거절",
  delete: "회의 삭제", purge: "보존 기간 만료 삭제", publish_request: "Slack 게시 요청", publish: "Slack 게시 결과",
  retry: "다시 분석", edit: "할 일 수정", task_done: "할 일 완료", task_reopen: "할 일 다시 열기", briefing: "브리핑",
  feedback: "요약 피드백",
};
const WARN_ACTIONS = new Set(["login_failed", "delete", "purge"]);

export default function AdminPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [tab, setTab] = useState<"users" | "metrics" | "audit" | "briefing">("users");
  const [users, setUsers] = useState<User[] | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [forbidden, setForbidden] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const load = useCallback(async () => {
    const res = await fetch("/api/auth/users", { cache: "no-store" });
    if (res.status === 403) { setForbidden(true); return; }
    if (!res.ok) { toast("사용자 목록을 불러오지 못했습니다.", "error"); return; }
    setUsers(await res.json());
    setEvents(await api<AuditEvent[]>("/api/auth/audit").catch(() => []));
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  async function call(url: string, method: string, body: unknown, success: string) {
    setBusy(true);
    try { await api(url, jsonInit(method, body), "처리하지 못했습니다."); toast(success); await load(); return true; }
    catch (e) { toast(e instanceof Error ? e.message : "처리하지 못했습니다.", "error"); return false; }
    finally { setBusy(false); }
  }

  async function create(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); const form = e.currentTarget; const data = new FormData(form);
    if (await call("/api/auth/users", "POST", { username: data.get("username"), password: data.get("password"), role: data.get("role") },
      `${data.get("username")} 계정을 추가했습니다.`)) form.reset();
  }

  function resetPassword(u: User) {
    const password = window.prompt(`${u.username}의 새 초기 비밀번호 (10자 이상). 사용자는 로그인 후 변경해야 합니다.`);
    if (password) call(`/api/auth/users/${u.id}`, "PATCH", { password }, "비밀번호를 재설정했습니다. 해당 사용자는 로그아웃됩니다.");
  }

  return <AppShell section="admin" onUser={setMe}>
    <main className="page">
      <div className="page-head"><div><h1>관리</h1><p className="muted">계정, 품질 지표, 감사 기록, 브리핑을 관리합니다.</p></div></div>
      {forbidden ? <div className="alert alert-danger"><div className="alert-body">관리자만 사용할 수 있습니다.</div></div> : <>
        <div className="tabs" role="tablist">
          <button className="tab" role="tab" aria-selected={tab === "users"} onClick={() => setTab("users")}>사용자 {users ? `(${users.length})` : ""}</button>
          <button className="tab" role="tab" aria-selected={tab === "metrics"} onClick={() => setTab("metrics")}>품질 지표</button>
          <button className="tab" role="tab" aria-selected={tab === "audit"} onClick={() => setTab("audit")}>감사 기록</button>
          <button className="tab" role="tab" aria-selected={tab === "briefing"} onClick={() => setTab("briefing")}>브리핑</button>
        </div>

        {tab === "users" && <div className="grid-main-side">
          <div className="card">
            <div className="table-wrap"><table className="table">
              <thead><tr><th>사용자</th><th>역할</th><th>상태</th><th style={{ textAlign: "right" }}>관리</th></tr></thead>
              <tbody>{(users ?? []).map(u => <tr key={u.id}>
                <td><div className="row"><span className="avatar" aria-hidden>{u.username.slice(0, 1).toUpperCase()}</span>
                  <strong>{u.username}</strong>{me?.id === u.id && <span className="badge badge-plain">나</span>}</div></td>
                <td>{u.role === "admin" ? <span className="badge badge-plain badge-accent">관리자</span> : <span className="badge badge-plain">구성원</span>}</td>
                <td>{!u.active ? <span className="badge">비활성</span> : u.mustChangePassword
                  ? <span className="badge badge-warning">초기 비밀번호</span> : <span className="badge badge-success">사용 중</span>}</td>
                <td><div className="row" style={{ justifyContent: "flex-end" }}>
                  <button className="btn btn-sm" disabled={busy} onClick={() => resetPassword(u)}>비밀번호 재설정</button>
                  <button className="btn btn-sm" disabled={busy || me?.id === u.id}
                    onClick={() => call(`/api/auth/users/${u.id}`, "PATCH", { role: u.role === "admin" ? "member" : "admin" }, "역할을 변경했습니다.")}>
                    {u.role === "admin" ? "구성원으로" : "관리자로"}</button>
                  <button className={`btn btn-sm${u.active ? " btn-danger" : ""}`} disabled={busy || me?.id === u.id}
                    onClick={() => call(`/api/auth/users/${u.id}`, "PATCH", { active: !u.active }, u.active ? "비활성화했습니다. 즉시 로그아웃됩니다." : "다시 사용하도록 했습니다.")}>
                    {u.active ? "비활성화" : "다시 사용"}</button>
                </div></td>
              </tr>)}</tbody>
            </table></div>
          </div>
          <form className="card card-pad stack" onSubmit={create}>
            <h2>사용자 추가</h2>
            <label className="field"><span>사용자 이름</span><input className="input" name="username" required minLength={3} maxLength={32} pattern="[A-Za-z0-9._\-]+" autoComplete="off" />
              <span className="hint">영문 소문자·숫자·. _ - (3~32자)</span></label>
            <label className="field"><span>초기 비밀번호</span><input className="input" name="password" type="text" required minLength={10} autoComplete="off" />
              <span className="hint">10자 이상. 사용자에게 따로 전달하면 첫 로그인 후 변경 안내가 표시됩니다.</span></label>
            <label className="field"><span>역할</span><select className="select" name="role" defaultValue="member">
              <option value="member">구성원</option><option value="admin">관리자</option></select></label>
            <button className="btn btn-primary" disabled={busy}>추가</button>
          </form>
        </div>}

        {tab === "briefing" && <BriefingPanel />}
        {tab === "metrics" && <MetricsPanel />}

        {tab === "audit" && <div className="card">
          <div className="row" style={{ padding: "14px 16px" }}><span className="subtle">최근 200건 · 회의를 삭제해도 기록(제목만)은 남습니다.</span></div>
          <div className="table-wrap"><table className="table">
            <thead><tr><th>시각</th><th>사용자</th><th>동작</th><th>대상</th><th>IP</th></tr></thead>
            <tbody>{events.map(e => <tr key={e.id}>
              <td className="subtle" style={{ whiteSpace: "nowrap" }}>{formatWhen(e.at)}</td>
              <td>{e.username ? displayActor(e.username) : <span className="subtle">-</span>}</td>
              <td><span className={`badge badge-plain${WARN_ACTIONS.has(e.action) ? " badge-warning" : ""}`}>{ACTIONS[e.action] ?? e.action}</span></td>
              <td>{e.title ?? e.detail ?? <span className="subtle">-</span>}{e.title && e.detail && <div className="subtle">{e.detail}</div>}</td>
              <td className="subtle">{e.ip ?? "-"}</td>
            </tr>)}</tbody>
          </table></div>
        </div>}
      </>}
    </main>
  </AppShell>;
}

type Preview = { kind: "morning" | "weekly"; text: string | null; enabled: boolean; time: string; timezone: string };

/** Workflow 20–21 — see what the scheduled briefing will post and send it now. */
function BriefingPanel() {
  const [kind, setKind] = useState<"morning" | "weekly">("morning");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  useEffect(() => {
    setPreview(null);
    api<Preview>(`/api/workspace/briefing?kind=${kind}`, undefined, "미리 보기를 불러오지 못했습니다.")
      .then(setPreview).catch(e => toast(e.message, "error"));
  }, [kind, toast]);
  async function sendNow() {
    setBusy(true);
    try { await api("/api/workspace/briefing", jsonInit("POST", { kind }), "보내지 못했습니다."); toast("Slack 게시를 진행합니다."); }
    catch (e) { toast(e instanceof Error ? e.message : "보내지 못했습니다.", "error"); }
    finally { setBusy(false); }
  }
  return <div className="card card-pad stack">
    <div className="row">
      <div className="tabs" role="tablist" style={{ flex: 1, borderBottom: 0 }}>
        <button className="tab" role="tab" aria-selected={kind === "morning"} onClick={() => setKind("morning")}>Morning Brief</button>
        <button className="tab" role="tab" aria-selected={kind === "weekly"} onClick={() => setKind("weekly")}>Weekly Digest</button>
      </div>
      <button className="btn btn-primary" disabled={busy || !preview?.text} onClick={sendNow}>지금 Slack에 보내기</button>
    </div>
    {preview && <div className={`alert ${preview.enabled ? "alert-info" : "alert-warning"}`}><div className="alert-body">
      {preview.enabled
        ? `평일 ${preview.time} (${preview.timezone})에 자동 발송합니다. Weekly Digest는 월요일에 함께 보냅니다. 서버가 잠들어 있었다면 정오까지 보충 발송합니다.`
        : "자동 발송이 꺼져 있습니다. Slack 토큰이 설정되어 있는지, BRIEFING_ENABLED가 false가 아닌지 확인하세요."}
    </div></div>}
    {preview === null ? <div className="empty"><span className="spin" aria-hidden /></div>
      : preview.text ? <pre className="preview">{readable(preview.text)}</pre>
      : <p className="subtle">오늘 보낼 내용이 없습니다. 승인된 회의의 할 일에 기한이 있거나, 최근 승인된 회의가 있으면 표시됩니다.</p>}
  </div>;
}

/** Slack mrkdwn → plain preview: links show their title, mentions show the user ID, markers dropped. */
function readable(mrkdwn: string): string {
  return mrkdwn
    .replace(/<([^|>]+)\|([^>]+)>/g, "$2")
    .replace(/<@([A-Z0-9]+)>/g, "@$1")
    .replace(/(^|\s)[*_]([^*_\n]+)[*_](?=\s|$|[.,)])/g, "$1$2")
    .replace(/_\(([^)]*)\)_/g, "($1)");
}
