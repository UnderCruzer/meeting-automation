"use client";
import { useEffect, useState } from "react";

export type Me = { id: number; username: string; role: "admin" | "member"; mustChangePassword: boolean };

/** Signed-in user, logout and password change. Calls onUser once the session is known. */
export default function AccountBar({ onUser }: { onUser?: (me: Me | null) => void }) {
  const [me, setMe] = useState<Me | null>(null);
  const [changing, setChanging] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    fetch("/api/auth/me", { cache: "no-store" }).then(r => r.ok ? r.json() : { user: null })
      .then(d => { setMe(d.user); onUser?.(d.user); }).catch(() => {});
  }, [onUser]);
  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    window.location.assign("/login");
  }
  async function changePassword(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); setMessage("");
    const form = e.currentTarget; const data = new FormData(form);
    if (data.get("new") !== data.get("confirm")) { setMessage("새 비밀번호가 서로 다릅니다."); return; }
    const res = await fetch("/api/auth/password", { method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ current: data.get("current"), new: data.get("new") }) });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) { setMessage(body.detail ?? "변경하지 못했습니다."); return; }
    form.reset(); setChanging(false); setMessage("비밀번호를 변경했습니다. 다른 기기는 로그아웃됩니다.");
    if (me) setMe({ ...me, mustChangePassword: false });
  }
  if (!me) return null;
  return <div style={{display: "grid", gap: 8, marginBottom: 16}}>
    <div style={{display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end"}}>
      <span>{me.username}{me.role === "admin" ? " (관리자)" : ""}</span>
      {me.role === "admin" && <a href="/admin">사용자 관리</a>}
      <button onClick={() => setChanging(v => !v)}>비밀번호 변경</button>
      <button onClick={logout}>로그아웃</button>
    </div>
    {me.mustChangePassword && !changing && <p role="note" style={{padding: 12, background: "#fff4df", borderRadius: 8}}>초기 비밀번호를 사용 중입니다. 비밀번호를 변경해주세요.</p>}
    {changing && <form onSubmit={changePassword} style={{display: "grid", gap: 8, padding: 16, background: "#f0f4f8", borderRadius: 8}}>
      <label>현재 비밀번호 <input name="current" type="password" autoComplete="current-password" required /></label>
      <label>새 비밀번호 (10자 이상) <input name="new" type="password" autoComplete="new-password" minLength={10} required /></label>
      <label>새 비밀번호 확인 <input name="confirm" type="password" autoComplete="new-password" minLength={10} required /></label>
      <button>변경</button>
    </form>}
    {message && <p role="status">{message}</p>}
  </div>;
}
