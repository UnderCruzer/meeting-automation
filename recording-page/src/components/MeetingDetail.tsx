"use client";
import { useState } from "react";
import type { Integrations, Job } from "@/lib/workspace";
import { FAILURE_REASONS, SLACK_HINTS, api, displayActor, dueState, formatWhen, jsonInit } from "@/lib/workspace";
import StatusBadge, { PriorityBadge } from "@/components/StatusBadge";
import ActionItemsEditor from "@/components/ActionItemsEditor";
import FeedbackCard from "@/components/FeedbackCard";
import AtlassianDrafts from "@/components/AtlassianDrafts";
import { useToast } from "@/components/Toast";

export default function MeetingDetail({ job, integrations, onChanged, onDeleted, onBack }: {
  job: Job; integrations: Integrations; onChanged: () => Promise<void>; onDeleted: () => void; onBack: () => void;
}) {
  const slack = integrations.slack;
  const [busy, setBusy] = useState(false);
  const [publishSlack, setPublishSlack] = useState(true);
  const [publishJira, setPublishJira] = useState(true);
  const [publishConfluence, setPublishConfluence] = useState(true);
  const [publishNow, setPublishNow] = useState(false);
  const toast = useToast();
  const summary = job.summary;

  async function run(action: () => Promise<unknown>, success?: string) {
    setBusy(true);
    try { await action(); if (success) toast(success); await onChanged(); }
    catch (e) { toast(e instanceof Error ? e.message : "처리하지 못했습니다.", "error"); }
    finally { setBusy(false); }
  }

  // Saved drafts decide what approval creates; unchecking here skips a whole product.
  const jiraCount = integrations.jira ? (job.drafts?.jira?.drafts ?? []).filter(d => d.include).length : 0;
  const confluenceOn = integrations.confluence && !!job.drafts?.confluence?.include;
  const outputs = [slack && publishSlack && "Slack", jiraCount > 0 && publishJira && "Jira",
    confluenceOn && publishConfluence && "Confluence"].filter(Boolean) as string[];

  const decide = (status: "approved" | "rejected") => run(
    () => api(`/api/workspace/jobs/${job.id}/decision`, jsonInit("POST", {
      status, publish_now: publishNow, publish_slack: publishSlack, publish_jira: publishJira, publish_confluence: publishConfluence,
    }), "이미 처리된 회의이거나 저장하지 못했습니다."),
    status === "approved" ? (outputs.length ? `승인했습니다. ${outputs.join("·")} 게시를 진행합니다.` : "승인했습니다.") : "거절했습니다.");

  async function remove() {
    if (!window.confirm(`"${job.title}" 회의와 분석 결과를 삭제할까요? 되돌릴 수 없습니다.`)) return;
    setBusy(true);
    try { await api(`/api/workspace/jobs/${job.id}`, { method: "DELETE" }, "삭제하지 못했습니다."); toast("회의를 삭제했습니다."); onDeleted(); }
    catch (e) { toast(e instanceof Error ? e.message : "삭제 실패", "error"); }
    finally { setBusy(false); }
  }

  const publish = job.status === "approved" && slack ? publishState(job) : null;

  return <article className="detail">
    <div className="card panel">
    <div className="panel-section detail-head">
      <button className="btn btn-ghost btn-sm only-mobile" style={{ justifySelf: "start" }} onClick={onBack}>← 목록</button>
      <div className="row"><h1 style={{ flex: 1, minWidth: 0 }}>{job.title}</h1><StatusBadge status={job.status} /></div>
      <div className="meta">
        <span>업로드 {displayActor(job.uploaded_by)} · {formatWhen(job.created_at)}</span>
        {job.decided_by && <span>{job.status === "approved" ? "승인" : "거절"} {displayActor(job.decided_by)} · {formatWhen(job.decided_at)}</span>}
      </div>
      {job.status === "processing" && <div className="alert alert-info"><span className="spin" aria-hidden /><div className="alert-body">
        <strong>분석 중</strong><span>전사와 AI 분석에 보통 1~3분 걸리며, 끝나면 자동으로 표시됩니다.</span></div></div>}
      {job.status === "failed" && <div className="alert alert-warning"><div className="alert-body">
        <strong>처리 실패</strong><span>{FAILURE_REASONS[job.error_code ?? ""] ?? "처리하지 못했습니다. 녹음을 다시 올려주세요."}</span></div>
        {job.can_retry && <button className="btn btn-sm" disabled={busy}
          onClick={() => run(() => api(`/api/workspace/jobs/${job.id}/retry`, { method: "POST" }, "다시 분석하지 못했습니다."), "다시 분석을 시작했습니다.")}>다시 분석</button>}
      </div>}
      {publish && <div className={`alert alert-${publish.tone}`}><div className="alert-body">
        <strong>Slack · {publish.label}</strong>{publish.detail && <span>{publish.detail}</span>}</div>
        {publish.canPublish && <button className="btn btn-sm" disabled={busy}
          onClick={() => run(() => api(`/api/workspace/jobs/${job.id}/publish`, jsonInit("POST", { now: true }), "게시하지 못했습니다."), "Slack 게시를 진행합니다.")}>지금 Slack에 게시</button>}
      </div>}
    </div>

    {summary && <>
      <section className="panel-section">
        <h2>요약</h2>
        <p className="summary-text">{summary.summary_ko}</p>
        {summary.quality_flags.map((f, i) => <div key={i} className="alert alert-warning"><div className="alert-body"><strong>검토 필요</strong><span>{f.message}</span></div></div>)}
      </section>

      <section className="panel-section">
        <h2>결정 사항</h2>
        {summary.decisions.length ? <ul className="bullets">{summary.decisions.map((d, i) => <li key={i}>{d.text}</li>)}</ul>
          : <p className="subtle">확정된 결정 사항이 없습니다.</p>}
      </section>

      <section className="panel-section">
        <div className="section-title"><h2>할 일 <span className="count">{summary.action_items.length}</span></h2>
          {job.status === "review" && <span className="subtle">승인 전 담당자·기한·우선순위를 확인하세요</span>}</div>
        {job.status === "review"
          ? <ActionItemsEditor key={job.id} jobId={job.id} items={summary.action_items} onSaved={onChanged} />
          : summary.action_items.length
            ? <div className="items">{summary.action_items.map((a, i) => { const due = dueState(a.due, a.done); return <div key={i} className="item" style={a.done ? { opacity: 0.65 } : undefined}>
                <div className="row">
                  {job.status === "approved" && <label className="check"><input type="checkbox" checked={!!a.done} disabled={busy}
                    aria-label={`${a.description} ${a.done ? "완료 취소" : "완료"}`}
                    onChange={() => run(() => api(`/api/workspace/jobs/${job.id}/action-items/${i}`, jsonInit("PATCH", { done: !a.done }), "상태를 바꾸지 못했습니다."),
                      a.done ? "다시 진행 중으로 바꿨습니다." : "완료했습니다.")} /></label>}
                  <strong style={{ flex: 1, textDecoration: a.done ? "line-through" : undefined }}>{a.description}</strong>
                  {due && <span className={`badge ${due.tone}`}>{due.label}</span>}<PriorityBadge priority={a.priority} /></div>
                <div className="meta"><span>담당 {a.assignee || "미정"}</span><span>기한 {a.due_date || "미정"}</span>
                  {a.done && <span>완료 {displayActor(a.done_by)} · {formatWhen(a.done_at)}</span>}</div>
                <blockquote className={`quote${a.citation_text ? "" : " quote-missing"}`}>{a.citation_text || "일치하는 원문을 찾지 못했습니다."}</blockquote>
              </div>; })}</div>
            : <p className="subtle">추출된 할 일이 없습니다.</p>}
        <p className="subtle">근거는 키워드로 연결한 후보이며, 개인정보 패턴은 가려져 표시됩니다.</p>
      </section>
    </>}

    {summary && job.drafts && <AtlassianDrafts job={job} onChanged={onChanged} />}

    {summary && <FeedbackCard key={`fb-${job.id}`} jobId={job.id} />}

    {job.status !== "processing" && <div className="panel-section danger-zone">
      <div><strong>회의 삭제</strong><div className="subtle">분석 결과와 파일을 지웁니다. 감사 기록에는 제목만 남습니다.</div></div>
      <button className="btn btn-danger btn-sm" disabled={busy} onClick={remove}>삭제</button>
    </div>}
    </div>

    {job.status === "review" && <div className="actionbar">
      {slack || jiraCount > 0 || confluenceOn ? <div style={{ display: "grid", gap: 6, flex: 1, minWidth: 240 }}>
        {slack && <>
          <label className="check"><input type="checkbox" checked={publishSlack} onChange={e => setPublishSlack(e.target.checked)} /><span>Slack 채널에 게시</span></label>
          <label className="check"><input type="checkbox" disabled={!publishSlack} checked={publishNow} onChange={e => setPublishNow(e.target.checked)} />
            <span>지금 바로 게시 <span className="subtle">(끄면 근무시간 외에는 다음 근무 시작에 게시)</span></span></label></>}
        {jiraCount > 0 && <label className="check"><input type="checkbox" checked={publishJira} onChange={e => setPublishJira(e.target.checked)} />
          <span>Jira에 {jiraCount}건 만들기</span></label>}
        {confluenceOn && <label className="check"><input type="checkbox" checked={publishConfluence} onChange={e => setPublishConfluence(e.target.checked)} />
          <span>Confluence 회의록 만들기</span></label>}
      </div> : <span className="subtle" style={{ flex: 1 }}>승인하면 할 일 목록에 보관됩니다.</span>}
      <button className="btn btn-danger" disabled={busy} onClick={() => decide("rejected")}>거절</button>
      <button className="btn btn-primary btn-lg" disabled={busy} onClick={() => decide("approved")}>
        {outputs.length ? `승인하고 ${outputs.join("·")}에 게시` : "승인"}</button>
    </div>}
  </article>;
}

function publishState(job: Job) {
  switch (job.publish_status) {
    case "queued": return { label: "게시 중", tone: "info", detail: "", canPublish: false };
    case "scheduled": return { label: "예약됨", tone: "info", detail: `${formatWhen(job.publish_at)}에 게시합니다 (근무시간 기준).`, canPublish: false };
    case "sent": return { label: "게시됨", tone: "success", detail: formatWhen(job.published_at), canPublish: false };
    case "failed": {
      const code = job.publish_error ?? "";
      const detail = SLACK_HINTS[code] ?? (code.includes("재시작") ? code : `오류 코드 ${code || "알 수 없음"} — 관리자에게 로그 확인을 요청하세요.`);
      return { label: `실패${SLACK_HINTS[code] ? ` (${code})` : ""}`, tone: "danger", detail, canPublish: true };
    }
    default: return { label: "게시 안 함", tone: "info", detail: "승인할 때 게시를 끄셨습니다.", canPublish: true };
  }
}
