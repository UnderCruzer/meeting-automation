"use client";
import { useEffect, useState } from "react";
import { encodeToWav } from "@/lib/audioEncoder";

type Action = { description: string; assignee: string; due_date: string; citation_text: string };
type Job = { id: string; title: string; status: string; summary: null | { summary_ko: string; decisions: {text: string}[]; action_items: Action[]; quality_flags: {message: string}[] } };
// Backend MAX_FILE_BYTES is 500 MB (~4.5 h of 16kHz mono WAV).
const MAX_WAV_BYTES = 500 * 1024 * 1024;
const labels: Record<string, string> = { processing: "분석 중", review: "검토 대기", approved: "승인 완료", rejected: "거절됨", failed: "처리 실패 — 파일을 다시 올려주세요" };

export default function Home() {
  const [ephemeral, setEphemeral] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string>("");
  const [consent, setConsent] = useState(false);
  async function refresh() {
    const res = await fetch("/api/workspace/jobs", { cache: "no-store" });
    if (!res.ok) throw new Error("회의 목록을 불러오지 못했습니다.");
    setJobs(await res.json());
  }
  useEffect(() => {
    let active = true;
    fetch("/api/workspace/config").then(res => res.ok ? res.json() : Promise.reject())
      .then(config => { if (active) setEphemeral(config.ephemeral); }).catch(() => {});
    const load = () => { if (active) refresh().catch(e => { if (active) setError(e.message); }); };
    load(); const timer = setInterval(load, 5000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  async function upload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); const form = e.currentTarget;
    const data = new FormData(form); const file = data.get("audio") as File;
    if (!file?.size || file.size > 100 * 1024 * 1024) { setError("100MB 이하의 음성 파일을 선택해주세요."); return; }
    setBusy(true); setError("");
    try {
      const wav = await encodeToWav(file); const now = new Date().toISOString();
      if (wav.size > MAX_WAV_BYTES) throw new Error("녹음이 너무 깁니다. 4시간 이하로 나눠서 올려주세요.");
      const payload = new FormData(); payload.set("audio", wav, "meeting.wav");
      payload.set("metadata", JSON.stringify({ meetingId: crypto.randomUUID(), title: data.get("title"), startTime: now, endTime: now }));
      const res = await fetch("/api/upload", { method: "POST", body: payload });
      if (!res.ok) throw new Error("업로드하지 못했습니다. 파일 크기와 서버 설정을 확인해주세요.");
      const job = await res.json(); setSelected(job.jobId); await refresh(); form.reset(); setConsent(false);
    } catch (e) { setError(e instanceof Error ? e.message : "음성 처리에 실패했습니다."); }
    finally { setBusy(false); }
  }
  async function decide(id: string, status: string) {
    setBusy(true); setError("");
    try {
      const res = await fetch(`/api/workspace/jobs/${id}/decision`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({status}) });
      if (!res.ok) throw new Error("이미 처리된 회의이거나 저장하지 못했습니다. 목록을 새로 확인해주세요.");
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "저장 실패"); }
    finally { setBusy(false); }
  }
  async function remove(id: string, title: string) {
    if (!window.confirm(`"${title}" 회의와 분석 결과를 삭제할까요? 되돌릴 수 없습니다.`)) return;
    setBusy(true); setError("");
    try {
      const res = await fetch(`/api/workspace/jobs/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(res.status === 409 ? "분석이 끝난 뒤 삭제할 수 있습니다." : "삭제하지 못했습니다. 목록을 새로 확인해주세요.");
      if (selected === id) setSelected("");
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "삭제 실패"); }
    finally { setBusy(false); }
  }
  const current = jobs.find(j => j.id === selected);
  return <main style={{maxWidth: 1040, margin: "40px auto", padding: 24, fontFamily: "system-ui", color: "#182536"}}>
    <h1>회의에서 실행까지</h1><p>녹음을 올리고 회의 내용을 검토한 뒤, 승인한 할 일을 한곳에서 확인하세요.</p>
    {ephemeral && <p role="note" style={{padding:16, background:"#fff4df", borderRadius:8}}>체험용 서버입니다. 재시작·재배포 시 녹음과 회의 기록이 초기화될 수 있습니다. 보존이 필요한 자료는 올리지 마세요.</p>}
    <form onSubmit={upload} style={{display: "grid", gap: 12, padding: 24, background: "#f0f4f8", borderRadius: 12}}>
      <label>회의 제목 <input name="title" required maxLength={200} placeholder="주간 프로젝트 회의" /></label>
      <label>녹음 파일 <input name="audio" type="file" accept="audio/*" required /></label>
      <small>100MB 이하 · 브라우저에서 WAV로 변환 · 업로드 시 전사 및 AI 분석이 실행됩니다.</small>
      <small>녹음은 전사 서비스(Groq 또는 OpenAI)로, 개인정보 패턴을 가린 전사문은 분석 서비스(Gemini 또는 Claude)로 전송됩니다. 원본 녹음은 처리 후 서버에서 삭제됩니다.</small>
      <label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} required /> 참석자에게 녹음과 외부 AI 처리를 안내하고 동의를 받았습니다.</label>
      <button disabled={busy || !consent}>{busy ? "처리 중…" : "회의 분석 시작"}</button>
    </form>
    {error && <p role="alert" style={{color: "#a52020"}}>{error}</p>}
    <h2>회의 기록</h2>{!jobs.length && <p>아직 등록한 회의가 없습니다.</p>}
    <div style={{display:"flex", flexWrap:"wrap", gap: 8}}>{jobs.map(j => <button key={j.id} onClick={() => setSelected(j.id)} aria-pressed={selected === j.id}>{j.title} · {labels[j.status]}</button>)}</div>
    {current && <section style={{padding: 24, border:"1px solid #ccd5df", borderRadius:12, marginTop:20}}>
      <h2>{current.title}</h2><p role="status">{labels[current.status]}</p>
      {current.status !== "processing" && <p><button disabled={busy} onClick={() => remove(current.id, current.title)}>회의 삭제</button></p>}
      {current.summary && <><p style={{whiteSpace:"pre-wrap"}}>{current.summary.summary_ko}</p>
        {current.summary.quality_flags.map((f,i) => <p key={i} style={{color:"#8a5000"}}>검토 필요: {f.message}</p>)}
        <h3>결정 사항</h3><ul>{current.summary.decisions.map((d,i) => <li key={i}>{d.text}</li>)}</ul>
        <h3>할 일</h3>{!current.summary.action_items.length && <p>추출된 할 일이 없습니다.</p>}
        {current.summary.action_items.map((a,i) => <article key={i}><h4>{a.description}</h4><p>{a.assignee || "담당자 미정"} · {a.due_date || "기한 미정"}</p><blockquote>{a.citation_text || "일치하는 원문을 찾지 못했습니다. 직접 확인해주세요."}</blockquote></article>)}
        <small>근거는 키워드로 연결한 후보이며, 개인정보 패턴은 가려져 표시됩니다. 승인 전 내용을 확인해주세요.</small>
        {current.status === "review" && <p><button disabled={busy} onClick={() => decide(current.id,"approved")}>승인하고 업무 목록에 보관</button> <button disabled={busy} onClick={() => decide(current.id,"rejected")}>거절</button></p>}
      </>}
    </section>}
    <h2>승인한 업무</h2><p>승인 결과는 내부 목록에 저장됩니다. 외부 서비스에는 발송되지 않습니다.</p>
    {jobs.filter(j => j.status === "approved").flatMap(j => j.summary?.action_items.map((a,i) => <article key={`${j.id}-${i}`}><strong>{a.description}</strong><p>{j.title} · {a.assignee || "담당자 미정"} · {a.due_date || "기한 미정"}</p></article>) ?? [])}
  </main>;
}
