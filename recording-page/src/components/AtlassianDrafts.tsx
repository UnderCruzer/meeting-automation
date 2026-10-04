"use client";
import { useState } from "react";
import type { Drafts, Job } from "@/lib/workspace";
import { api, jsonInit, safeUrl } from "@/lib/workspace";
import { useToast } from "@/components/Toast";

const GENERATION_ERRORS: Record<string, string> = {
  LLM_BUSY: "AI 서비스가 혼잡해 Jira 초안을 만들지 못했습니다. 회의 요약·할 일은 그대로 검토할 수 있습니다.",
  DRAFT_FAILED: "Jira 초안을 만들지 못했습니다.",
};
const SOURCE_LABEL = { jira: "Jira", confluence: "Confluence", slack: "Slack" } as const;

/** Workflow 10·12·13 on the review screen: related Jira/Confluence items and the drafts to create. */
export default function AtlassianDrafts({ job, onChanged }: { job: Job; onChanged: () => Promise<void> }) {
  const drafts = job.drafts!;
  const review = job.status === "review";
  return <section className="panel-section">
    <div className="section-title"><h2>Jira · Confluence</h2>
      {review && <span className="subtle">승인할 때 체크한 항목만 만듭니다</span>}</div>
    <Related related={drafts.related} />
    {review ? <DraftEditor key={job.id} job={job} drafts={drafts} onSaved={onChanged} />
      : job.status === "approved" ? <Results job={job} drafts={drafts} onChanged={onChanged} />
      : <p className="subtle">거절된 회의라 만들지 않았습니다.</p>}
  </section>;
}

function Related({ related }: { related: Drafts["related"] }) {
  if (!related.length) return <p className="subtle">지정한 프로젝트·스페이스에서 관련 항목을 찾지 못했습니다.</p>;
  return <details className="related">
    <summary>관련 항목 {related.length}건 (지정한 프로젝트·스페이스 검색)</summary>
    <ul className="bullets">{related.map(r => <li key={`${r.source}-${r.id}`}>
      <span className="badge">{SOURCE_LABEL[r.source]}</span>{" "}
      <a href={safeUrl(r.url)} target="_blank" rel="noopener noreferrer">{r.source === "jira" ? `${r.id} ` : ""}{r.title}</a>
      {r.status && <span className="subtle"> · {r.status}</span>}
    </li>)}</ul>
  </details>;
}

function DraftEditor({ job, drafts, onSaved }: { job: Job; drafts: Drafts; onSaved: () => Promise<void> }) {
  const [jira, setJira] = useState(() => (drafts.jira?.drafts ?? []).map(d => ({ ...d })));
  const [page, setPage] = useState(() => drafts.confluence && { ...drafts.confluence });
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const edit = (index: number, patch: Partial<(typeof jira)[number]>) => {
    setDirty(true); setJira(rows => rows.map((row, i) => i === index ? { ...row, ...patch } : row));
  };

  async function save() {
    setBusy(true);
    try {
      await api(`/api/workspace/jobs/${job.id}/drafts`, jsonInit("PUT", {
        ...(drafts.jira && { jira: jira.map(d => ({ include: d.include, summary: d.summary, description: d.description })) }),
        ...(page && { confluence: { include: page.include, title: page.title } }),
      }), "초안을 저장하지 못했습니다. 제목이 비어 있지 않은지 확인하세요.");
      setDirty(false); toast("초안을 저장했습니다."); await onSaved();
    } catch (e) { toast(e instanceof Error ? e.message : "저장 실패", "error"); }
    finally { setBusy(false); }
  }

  return <div className="items">
    {drafts.jira?.generation_error && <div className="alert alert-warning"><div className="alert-body">
      <strong>Jira 초안 없음</strong><span>{GENERATION_ERRORS[drafts.jira.generation_error] ?? GENERATION_ERRORS.DRAFT_FAILED}</span></div></div>}
    {jira.map((d, i) => <div key={i} className="item" style={d.include ? undefined : { opacity: 0.6 }}>
      <div className="row">
        <label className="check" style={{ flex: 1 }}><input type="checkbox" checked={d.include} onChange={e => edit(i, { include: e.target.checked })} />
          <span>{d.action === "comment" ? <>기존 이슈 <strong>{d.existing_key}</strong>에 댓글</> : "Jira 이슈 만들기"}</span></label>
        {d.action === "create" && <span className={`badge badge-${d.priority === "High" ? "high" : d.priority === "Low" ? "low" : "medium"}`}>{d.priority}</span>}
      </div>
      {d.action === "create" && <label className="field"><span>제목</span>
        <input className="input" value={d.summary} maxLength={250} onChange={e => edit(i, { summary: e.target.value })} /></label>}
      <label className="field"><span>{d.action === "comment" ? "댓글" : "설명"}</span>
        <textarea className="textarea" rows={3} value={d.description} maxLength={5000} onChange={e => edit(i, { description: e.target.value })} /></label>
    </div>)}
    {page && <div className="item" style={page.include ? undefined : { opacity: 0.6 }}>
      <label className="check"><input type="checkbox" checked={page.include}
        onChange={e => { setDirty(true); setPage({ ...page, include: e.target.checked }); }} />
        <span>Confluence 회의록 페이지 만들기 <span className="subtle">(요약·결정 사항·할 일 표, 승인 시점 내용으로)</span></span></label>
      <label className="field"><span>페이지 제목</span>
        <input className="input" value={page.title} maxLength={200} onChange={e => { setDirty(true); setPage({ ...page, title: e.target.value }); }} /></label>
    </div>}
    <div className="row">
      <span className="spacer" />
      {dirty && <span className="subtle">저장하지 않은 변경이 있습니다</span>}
      <button type="button" className="btn btn-primary" disabled={busy || !dirty} onClick={save}>{busy ? "저장 중…" : "초안 저장"}</button>
    </div>
  </div>;
}

function Results({ job, drafts, onChanged }: { job: Job; drafts: Drafts; onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const created = (drafts.jira?.drafts ?? []).filter(d => d.result);
  const missingJira = (drafts.jira?.drafts ?? []).some(d => d.include && !d.result);
  const page = drafts.confluence;

  async function retry(target: "jira" | "confluence") {
    setBusy(true);
    try {
      await api(`/api/workspace/jobs/${job.id}/publish`, jsonInit("POST", { target }), "다시 만들지 못했습니다.");
      toast("다시 만드는 중입니다."); await onChanged();
    } catch (e) { toast(e instanceof Error ? e.message : "다시 만들지 못했습니다.", "error"); }
    finally { setBusy(false); }
  }

  const status = (s: string | null | undefined, error?: string | null) => s === "queued" ? "만드는 중"
    : s === "failed" ? `실패 — ${error ?? "알 수 없는 오류"}` : s === "sent" ? "완료" : "만들지 않음";

  return <div className="items">
    {drafts.jira && <div className="item">
      <div className="row"><strong style={{ flex: 1 }}>Jira</strong><span className="subtle">{status(drafts.jira.status, drafts.jira.error)}</span>
        {missingJira && drafts.jira.status !== "queued" && <button className="btn btn-sm" disabled={busy} onClick={() => retry("jira")}>
          {created.length ? "남은 이슈 만들기" : "Jira에 만들기"}</button>}</div>
      {created.length > 0 && <ul className="bullets">{created.map(d => <li key={d.result!.key}>
        <a href={safeUrl(d.result!.url)} target="_blank" rel="noopener noreferrer">{d.result!.key}</a>{" "}
        {d.result!.action === "commented" ? "댓글 추가" : d.summary}</li>)}</ul>}
    </div>}
    {page && <div className="item">
      <div className="row"><strong style={{ flex: 1 }}>Confluence</strong><span className="subtle">{status(page.status, page.error)}</span>
        {page.include && !page.result && page.status !== "queued" && <button className="btn btn-sm" disabled={busy} onClick={() => retry("confluence")}>
          Confluence에 만들기</button>}</div>
      {page.result && <a href={safeUrl(page.result.url)} target="_blank" rel="noopener noreferrer">{page.result.title}</a>}
    </div>}
  </div>;
}
