"use client";
import { useEffect, useRef, useState } from "react";
import { useToast } from "@/components/Toast";
import BrandMark from "@/components/BrandMark";

export type Me = { id: number; username: string; role: "admin" | "member"; mustChangePassword: boolean };
type Section = "meetings" | "tasks" | "admin";

/** Top navigation, account menu and password change — shared by signed-in pages. */
export default function AppShell({ section, onUser, children }: {
  section: Section; onUser?: (me: Me | null) => void; children: React.ReactNode;
}) {
  const [me, setMe] = useState<Me | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const toast = useToast();

  useEffect(() => {
    fetch("/api/auth/me", { cache: "no-store" }).then(r => r.ok ? r.json() : { user: null })
      .then(d => { setMe(d.user); onUser?.(d.user); }).catch(() => {});
  }, [onUser]);

  useEffect(() => {
    if (!menuOpen) return;
    const close = () => setMenuOpen(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [menuOpen]);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    window.location.assign("/login");
  }

  async function changePassword(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget; const data = new FormData(form);
    if (data.get("new") !== data.get("confirm")) { toast("새 비밀번호가 서로 다릅니다.", "error"); return; }
    const res = await fetch("/api/auth/password", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current: data.get("current"), new: data.get("new") }) });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) { toast(body.detail ?? "비밀번호를 변경하지 못했습니다.", "error"); return; }
    form.reset(); dialog.current?.close();
    toast("비밀번호를 변경했습니다. 다른 기기는 로그아웃됩니다.");
    if (me) setMe({ ...me, mustChangePassword: false });
  }

  const nav: Array<[Section, string, string]> = [["meetings", "/", "회의"], ["tasks", "/tasks", "할 일"]];
  if (me?.role === "admin") nav.push(["admin", "/admin", "관리"]);

  return <>
    <header className="topbar">
      <a href="/" className="brand"><BrandMark /><span className="brand-name">회의에서 실행까지</span></a>
      <nav className="nav" aria-label="주요 메뉴">
        {nav.map(([key, href, label]) => <a key={key} href={href} aria-current={section === key ? "page" : undefined}>{label}</a>)}
      </nav>
      {me && <div className="account">
        <button className="btn btn-ghost" aria-haspopup="menu" aria-expanded={menuOpen}
          onClick={e => { e.stopPropagation(); setMenuOpen(v => !v); }}>
          <span className="avatar" aria-hidden>{me.username.slice(0, 1).toUpperCase()}</span>
          <span className="brand-name">{me.username}</span>
        </button>
        {menuOpen && <div className="menu" role="menu" onClick={e => e.stopPropagation()}>
          <div className="menu-head"><strong>{me.username}</strong><div className="subtle">{me.role === "admin" ? "관리자" : "구성원"}</div></div>
          <button role="menuitem" onClick={() => { setMenuOpen(false); dialog.current?.showModal(); }}>비밀번호 변경</button>
          <button role="menuitem" onClick={logout}>로그아웃</button>
        </div>}
      </div>}
    </header>
    {me?.mustChangePassword && <div className="page" style={{ paddingBottom: 0 }}>
      <div className="alert alert-warning"><div className="alert-body">초기 비밀번호를 사용 중입니다. 계정 메뉴에서 비밀번호를 변경해주세요.</div>
        <button className="btn btn-sm" onClick={() => dialog.current?.showModal()}>지금 변경</button></div>
    </div>}
    {children}
    <dialog ref={dialog} className="dialog" aria-labelledby="pw-title">
      <form onSubmit={changePassword}>
        <div className="dialog-head"><h2 id="pw-title">비밀번호 변경</h2>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => dialog.current?.close()} aria-label="닫기">닫기</button></div>
        <div className="dialog-body">
          <label className="field"><span>현재 비밀번호</span><input className="input" name="current" type="password" autoComplete="current-password" required /></label>
          <label className="field"><span>새 비밀번호</span><input className="input" name="new" type="password" autoComplete="new-password" minLength={10} required /><span className="hint">10자 이상</span></label>
          <label className="field"><span>새 비밀번호 확인</span><input className="input" name="confirm" type="password" autoComplete="new-password" minLength={10} required /></label>
        </div>
        <div className="dialog-foot">
          <button type="button" className="btn" onClick={() => dialog.current?.close()}>취소</button>
          <button className="btn btn-primary">변경</button>
        </div>
      </form>
    </dialog>
  </>;
}
