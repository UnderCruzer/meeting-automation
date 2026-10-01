"use client";
import { useCallback, useEffect, useState } from "react";
import AccountBar, { type Me } from "@/components/AccountBar";

type User = { id: number; username: string; role: "admin" | "member"; active: boolean; mustChangePassword: boolean };

export default function AdminPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const res = await fetch("/api/auth/users", { cache: "no-store" });
    if (res.status === 403) { setError("관리자만 사용할 수 있습니다."); return; }
    if (!res.ok) { setError("사용자 목록을 불러오지 못했습니다."); return; }
    setUsers(await res.json());
  }, []);
  useEffect(() => { load(); }, [load]);
  async function call(url: string, method: string, body: unknown) {
    setBusy(true); setError("");
    try {
      const res = await fetch(url, { method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail ?? "처리하지 못했습니다.");
      await load(); return true;
    } catch (e) { setError(e instanceof Error ? e.message : "처리하지 못했습니다."); return false; }
    finally { setBusy(false); }
  }
  async function create(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); const form = e.currentTarget; const data = new FormData(form);
    if (await call("/api/auth/users", "POST", { username: data.get("username"), password: data.get("password"), role: data.get("role") })) form.reset();
  }
  function resetPassword(u: User) {
    const password = window.prompt(`${u.username}의 새 초기 비밀번호 (10자 이상). 사용자는 로그인 후 변경해야 합니다.`);
    if (password) call(`/api/auth/users/${u.id}`, "PATCH", { password });
  }
  return <main style={{maxWidth: 1040, margin: "40px auto", padding: 24, fontFamily: "system-ui", color: "#182536"}}>
    <AccountBar onUser={setMe} />
    <p><a href="/">← 회의 목록</a></p>
    <h1>사용자 관리</h1>
    {error && <p role="alert" style={{color: "#a52020"}}>{error}</p>}
    <form onSubmit={create} style={{display: "grid", gap: 12, padding: 24, background: "#f0f4f8", borderRadius: 12}}>
      <h2 style={{margin: 0}}>사용자 추가</h2>
      <label>사용자 이름 (영문 소문자·숫자·._-) <input name="username" required minLength={3} maxLength={32} pattern="[A-Za-z0-9._\-]+" /></label>
      <label>초기 비밀번호 (10자 이상) <input name="password" type="text" required minLength={10} autoComplete="off" /></label>
      <label>역할 <select name="role" defaultValue="member"><option value="member">구성원</option><option value="admin">관리자</option></select></label>
      <small>초기 비밀번호는 사용자에게 안전한 방법으로 따로 전달하세요. 첫 로그인 후 변경 안내가 표시됩니다.</small>
      <button disabled={busy}>추가</button>
    </form>
    <h2>사용자 목록</h2>
    <table style={{width: "100%", borderCollapse: "collapse"}}>
      <thead><tr><th align="left">이름</th><th align="left">역할</th><th align="left">상태</th><th align="left">관리</th></tr></thead>
      <tbody>{users.map(u => <tr key={u.id} style={{borderTop: "1px solid #ccd5df"}}>
        <td>{u.username}{me?.id === u.id ? " (나)" : ""}</td>
        <td>{u.role === "admin" ? "관리자" : "구성원"}</td>
        <td>{u.active ? (u.mustChangePassword ? "초기 비밀번호" : "사용 중") : "비활성"}</td>
        <td style={{display: "flex", gap: 6, flexWrap: "wrap", padding: "6px 0"}}>
          <button disabled={busy || me?.id === u.id} onClick={() => call(`/api/auth/users/${u.id}`, "PATCH", { active: !u.active })}>{u.active ? "비활성화" : "다시 사용"}</button>
          <button disabled={busy || me?.id === u.id} onClick={() => call(`/api/auth/users/${u.id}`, "PATCH", { role: u.role === "admin" ? "member" : "admin" })}>{u.role === "admin" ? "구성원으로" : "관리자로"}</button>
          <button disabled={busy} onClick={() => resetPassword(u)}>비밀번호 재설정</button>
        </td>
      </tr>)}</tbody>
    </table>
    <p><small>비활성화하거나 비밀번호를 재설정하면 해당 사용자의 모든 세션이 즉시 로그아웃됩니다.</small></p>
  </main>;
}
