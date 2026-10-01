"use client";
import { useState } from "react";
import type { ActionItem } from "@/lib/workspace";
import { api, jsonInit } from "@/lib/workspace";
import { useToast } from "@/components/Toast";

/** Workflow 15 — fix what the AI extracted (owner, due date, priority) before approval. */
export default function ActionItemsEditor({ jobId, items, onSaved }: {
  jobId: string; items: ActionItem[]; onSaved: () => Promise<void> | void;
}) {
  const [draft, setDraft] = useState<ActionItem[]>(() => items.map(i => ({ ...i, priority: i.priority ?? "medium" })));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const update = (index: number, patch: Partial<ActionItem>) => {
    setDirty(true);
    setDraft(rows => rows.map((row, i) => i === index ? { ...row, ...patch } : row));
  };

  async function save() {
    setBusy(true);
    try {
      await api(`/api/workspace/jobs/${jobId}/action-items`,
        jsonInit("PUT", { items: draft.filter(i => i.description.trim()) }), "저장하지 못했습니다. 입력값을 확인해주세요.");
      setDirty(false); toast("할 일을 저장했습니다."); await onSaved();
    } catch (e) { toast(e instanceof Error ? e.message : "저장 실패", "error"); }
    finally { setBusy(false); }
  }

  return <div className="items">
    {!draft.length && <p className="subtle">할 일이 없습니다. 필요하면 추가하세요.</p>}
    {draft.map((item, i) => <div key={i} className="item">
      <div className="item-grid">
        <label className="field"><span>할 일</span>
          <input className="input" value={item.description} maxLength={500} onChange={e => update(i, { description: e.target.value })} /></label>
        <label className="field"><span>담당자</span>
          <input className="input" value={item.assignee} maxLength={100} placeholder="미정" onChange={e => update(i, { assignee: e.target.value })} /></label>
        <label className="field"><span>기한</span>
          <input className="input" value={item.due_date} maxLength={50} placeholder="예: 10/15" onChange={e => update(i, { due_date: e.target.value })} /></label>
        <label className="field"><span>우선순위</span>
          <select className="select" value={item.priority} onChange={e => update(i, { priority: e.target.value as ActionItem["priority"] })}>
            <option value="high">높음</option><option value="medium">보통</option><option value="low">낮음</option>
          </select></label>
        <button type="button" className="btn btn-ghost" disabled={busy} aria-label={`${i + 1}번째 할 일 삭제`}
          onClick={() => { setDirty(true); setDraft(rows => rows.filter((_, j) => j !== i)); }}>삭제</button>
      </div>
      <blockquote className={`quote${item.citation_text ? "" : " quote-missing"}`}>
        {item.citation_text || "근거 없음 — 직접 추가했거나 원문과 일치하는 부분을 찾지 못했습니다."}</blockquote>
    </div>)}
    <div className="row">
      <button type="button" className="btn" disabled={busy || draft.length >= 50}
        onClick={() => { setDirty(true); setDraft(rows => [...rows, { description: "", assignee: "", due_date: "", priority: "medium", citation_text: "" }]); }}>
        + 할 일 추가</button>
      <span className="spacer" />
      {dirty && <span className="subtle">저장하지 않은 변경이 있습니다</span>}
      <button type="button" className="btn btn-primary" disabled={busy || !dirty} onClick={save}>{busy ? "저장 중…" : "변경 저장"}</button>
    </div>
  </div>;
}
