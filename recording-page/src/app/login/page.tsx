"use client";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import BrandMark from "@/components/BrandMark";

function LoginForm() {
  const params = useSearchParams();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); setBusy(true); setError("");
    const data = new FormData(e.currentTarget);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: data.get("username"), password: data.get("password") }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail ?? "로그인에 실패했습니다.");
      // Only same-site relative paths are accepted as a redirect target.
      const next = params?.get("next") ?? "/";
      window.location.assign(next.startsWith("/") && !next.startsWith("//") ? next : "/");
    } catch (err) { setError(err instanceof Error ? err.message : "로그인에 실패했습니다."); }
    finally { setBusy(false); }
  }
  return <form onSubmit={submit} className="stack">
    <label className="field"><span>사용자 이름</span><input className="input" name="username" autoComplete="username" required autoFocus /></label>
    <label className="field"><span>비밀번호</span><input className="input" name="password" type="password" autoComplete="current-password" required /></label>
    {error && <div className="alert alert-danger" role="alert"><div className="alert-body">{error}</div></div>}
    <button className="btn btn-primary btn-lg btn-block" disabled={busy}>{busy ? "확인 중…" : "로그인"}</button>
  </form>;
}

export default function LoginPage() {
  return <main className="center-page">
    <div className="card auth-card">
      <div className="stack" style={{ gap: 10 }}>
        <BrandMark size={28} />
        <h1>회의에서 실행까지</h1>
        <p className="muted">회의 녹음 요약 · 할 일 검토 · 팀 공유</p>
      </div>
      <Suspense><LoginForm /></Suspense>
      <p className="subtle">계정이 없으면 관리자에게 요청하세요.</p>
    </div>
  </main>;
}
