"use client";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

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
  return <form onSubmit={submit} style={{display: "grid", gap: 12, padding: 24, background: "#f0f4f8", borderRadius: 12}}>
    <label>사용자 이름 <input name="username" autoComplete="username" required autoFocus /></label>
    <label>비밀번호 <input name="password" type="password" autoComplete="current-password" required /></label>
    <button disabled={busy}>{busy ? "확인 중…" : "로그인"}</button>
    {error && <p role="alert" style={{color: "#a52020"}}>{error}</p>}
  </form>;
}

export default function LoginPage() {
  return <main style={{maxWidth: 420, margin: "80px auto", padding: 24, fontFamily: "system-ui", color: "#182536"}}>
    <h1>회의에서 실행까지</h1><p>계정이 없으면 관리자에게 요청하세요.</p>
    <Suspense><LoginForm /></Suspense>
  </main>;
}
