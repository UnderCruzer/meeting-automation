"use client";
import { useState } from "react";

export type ActionItem = {
  description: string; assignee: string; due_date: string; priority?: "high" | "medium" | "low";
  citation_start?: number; citation_end?: number; citation_text: string;
};

const PRIORITIES: Record<string, string> = { high: "높음", medium: "보통", low: "낮음" };

/** Workflow 15 — fix what the AI extracted (owner, due date, priority) before approval. */
export default function ActionItemsEditor({ jobId, items, onSaved }: {
  jobId: string; items: ActionItem[]; onSaved: () => Promise<void> | void;
}) {
  const [draft, setDraft] = useState<ActionItem[]>(() => items.map(i => ({ ...i, priority: i.priority ?? "medium" })));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const update = (index: number, patch: Partial<ActionItem>) =>
    setDraft(rows => rows.map((row, i) => i === index ? { ...row, ...patch } : row));

  async function save() {
    setBusy(true); setMessage("");
    try {
      const res = await fetch(`/api/workspace/jobs/${jobId}/action-items`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: draft.filter(i => i.description.trim()) }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "저장하지 못했습니다. 입력값을 확인해주세요.");
      setMessage("저장했습니다."); await onSaved();
    } catch (e) { setMessage(e instanceof Error ? e.message : "저장 실패"); }
    finally { setBusy(false); }
  }

  return <div style={{ display: "grid", gap: 12 }}>
    {draft.map((item, i) => <fieldset key={i} style={{ border: "1px solid #ccd5df", borderRadius: 8, padding: 12, display: "grid", gap: 8 }}>
      <label>할 일 <input value={item.description} maxLength={500} style={{ width: "100%" }}
        onChange={e => update(i, { description: e.target.value })} /></label>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <label>담당자 <input value={item.assignee} maxLength={100} placeholder="미정" onChange={e => update(i, { assignee: e.target.value })} /></label>
        <label>기한 <input value={item.due_date} maxLength={50} placeholder="예: 10/15" onChange={e => update(i, { due_date: e.target.value })} /></label>
        <label>우선순위 <select value={item.priority} onChange={e => update(i, { priority: e.target.value as ActionItem["priority"] })}>
          {Object.entries(PRIORITIES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <button type="button" disabled={busy} onClick={() => setDraft(rows => rows.filter((_, j) => j !== i))}>삭제</button>
      </div>
      <blockquote style={{ margin: 0, color: "#4a5868" }}>{item.citation_text || "근거 없음 (직접 추가하거나 원문과 일치하는 부분을 찾지 못함)"}</blockquote>
    </fieldset>)}
    <div style={{ display: "flex", gap: 8 }}>
      <button type="button" disabled={busy || draft.length >= 50}
        onClick={() => setDraft(rows => [...rows, { description: "", assignee: "", due_date: "", priority: "medium", citation_text: "" }])}>할 일 추가</button>
      <button type="button" disabled={busy} onClick={save}>{busy ? "저장 중…" : "수정 저장"}</button>
      {message && <span role="status">{message}</span>}
    </div>
  </div>;
}
