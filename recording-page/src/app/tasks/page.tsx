"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import AppShell from "@/components/AppShell";
import { PriorityBadge } from "@/components/StatusBadge";
import { useToast } from "@/components/Toast";
import type { Job } from "@/lib/workspace";
import { api, displayActor, dueState, formatWhen, jsonInit } from "@/lib/workspace";

const ORDER = { high: 0, medium: 1, low: 2 } as const;
type View = "open" | "done" | "all";

/** Approved action items across meetings — the team's to-do list (workflow 21). */
export default function TasksPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [query, setQuery] = useState("");
  const [owner, setOwner] = useState("");
  const [view, setView] = useState<View>("open");
  const [busyKey, setBusyKey] = useState("");
  const toast = useToast();

  const load = useCallback(() => api<Job[]>("/api/workspace/jobs", undefined, "할 일을 불러오지 못했습니다.").then(setJobs), []);
  useEffect(() => { load().catch(e => { setJobs([]); toast(e.message, "error"); }); }, [load, toast]);

  const tasks = useMemo(() => (jobs ?? [])
    .filter(j => j.status === "approved" && j.summary)
    .flatMap(j => j.summary!.action_items.map((a, index) => ({ ...a, index, key: `${j.id}-${index}`, job: j })))
    // Open first, then by due date (undated last), then priority.
    .sort((a, b) => Number(!!a.done) - Number(!!b.done)
      || (a.due ?? "9999").localeCompare(b.due ?? "9999")
      || ORDER[a.priority ?? "medium"] - ORDER[b.priority ?? "medium"]), [jobs]);
  const owners = [...new Set(tasks.map(t => t.assignee || "미정"))].sort();
  const counts = { open: tasks.filter(t => !t.done).length, done: tasks.filter(t => t.done).length, all: tasks.length };
  const overdue = tasks.filter(t => dueState(t.due, t.done)?.tone === "badge-danger").length;
  const shown = tasks.filter(t => (view === "all" || (view === "done") === !!t.done)
    && (!owner || (t.assignee || "미정") === owner)
    && (!query || `${t.description} ${t.job.title}`.toLowerCase().includes(query.toLowerCase())));

  async function toggle(task: (typeof tasks)[number]) {
    setBusyKey(task.key);
    try {
      await api(`/api/workspace/jobs/${task.job.id}/action-items/${task.index}`, jsonInit("PATCH", { done: !task.done }),
        "상태를 바꾸지 못했습니다.");
      await load();
      toast(task.done ? "다시 진행 중으로 바꿨습니다." : "완료했습니다.");
    } catch (e) { toast(e instanceof Error ? e.message : "상태를 바꾸지 못했습니다.", "error"); }
    finally { setBusyKey(""); }
  }

  return <AppShell section="tasks">
    <main className="page">
      <div className="page-head">
        <div><h1>할 일</h1><p className="muted">승인된 회의의 할 일 · 완료하면 아침 브리핑에서 빠집니다</p></div>
        <div className="row">
          <input className="input" style={{ width: 220 }} placeholder="할 일·회의 검색" value={query} onChange={e => setQuery(e.target.value)} aria-label="검색" />
          <select className="select" style={{ width: 140 }} value={owner} onChange={e => setOwner(e.target.value)} aria-label="담당자">
            <option value="">모든 담당자</option>{owners.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
      </div>
      <div className="row">
        <div className="tabs" role="tablist" style={{ flex: 1 }}>
          {([["open", "진행 중"], ["done", "완료"], ["all", "전체"]] as const).map(([key, label]) =>
            <button key={key} className="tab" role="tab" aria-selected={view === key} onClick={() => setView(key)}>
              {label} <span className="count">{counts[key]}</span></button>)}
        </div>
        {overdue > 0 && <span className="badge badge-danger">기한 지남 {overdue}</span>}
      </div>
      <div className="card">
        {jobs === null ? <div className="empty"><span className="spin" aria-hidden /></div>
          : !shown.length ? <div className="empty">
              <span>{tasks.length ? "조건에 맞는 할 일이 없습니다." : "아직 승인된 할 일이 없습니다. 회의를 검토·승인하면 여기에 모입니다."}</span></div>
          : <div className="table-wrap"><table className="table">
              <thead><tr><th style={{ width: 44 }}><span className="sr-only">완료</span></th><th>할 일</th><th>담당자</th><th>기한</th><th>우선순위</th><th>회의</th></tr></thead>
              <tbody>{shown.map(t => {
                const due = dueState(t.due, t.done);
                return <tr key={t.key} style={t.done ? { opacity: 0.6 } : undefined}>
                  <td><label className="check"><input type="checkbox" checked={!!t.done} disabled={busyKey === t.key}
                    onChange={() => toggle(t)} aria-label={`${t.description} ${t.done ? "완료 취소" : "완료"}`} /></label></td>
                  <td style={{ fontWeight: 600, textDecoration: t.done ? "line-through" : undefined }}>{t.description}
                    {t.done && <div className="subtle">완료 {displayActor(t.done_by)} · {formatWhen(t.done_at)}</div>}</td>
                  <td>{t.assignee || <span className="subtle">미정</span>}</td>
                  <td><div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                    <span>{t.due_date || <span className="subtle">미정</span>}</span>
                    {due && <span className={`badge ${due.tone}`}>{due.label}</span>}</div></td>
                  <td><PriorityBadge priority={t.priority} /></td>
                  <td><a href={`/?meeting=${t.job.id}`}>{t.job.title}</a></td>
                </tr>;
              })}</tbody>
            </table></div>}
      </div>
    </main>
  </AppShell>;
}
