"use client";
import { useEffect, useMemo, useState } from "react";
import AppShell from "@/components/AppShell";
import { PriorityBadge } from "@/components/StatusBadge";
import { useToast } from "@/components/Toast";
import type { Job } from "@/lib/workspace";
import { api, displayActor, formatWhen } from "@/lib/workspace";

const ORDER = { high: 0, medium: 1, low: 2 } as const;

/** Approved action items across meetings — the team's to-do list. */
export default function TasksPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [query, setQuery] = useState("");
  const [owner, setOwner] = useState("");
  const toast = useToast();

  useEffect(() => {
    api<Job[]>("/api/workspace/jobs", undefined, "할 일을 불러오지 못했습니다.").then(setJobs)
      .catch(e => { setJobs([]); toast(e.message, "error"); });
  }, [toast]);

  const tasks = useMemo(() => (jobs ?? [])
    .filter(j => j.status === "approved" && j.summary)
    .flatMap(j => j.summary!.action_items.map((a, i) => ({ ...a, key: `${j.id}-${i}`, job: j })))
    .sort((a, b) => ORDER[a.priority ?? "medium"] - ORDER[b.priority ?? "medium"]), [jobs]);
  const owners = [...new Set(tasks.map(t => t.assignee || "미정"))].sort();
  const shown = tasks.filter(t => (!owner || (t.assignee || "미정") === owner)
    && (!query || `${t.description} ${t.job.title}`.toLowerCase().includes(query.toLowerCase())));

  return <AppShell section="tasks">
    <main className="page">
      <div className="page-head">
        <div><h1>할 일</h1><p className="muted">승인된 회의에서 나온 할 일을 모아 봅니다.</p></div>
        <div className="row">
          <input className="input" style={{ width: 220 }} placeholder="할 일·회의 검색" value={query} onChange={e => setQuery(e.target.value)} aria-label="검색" />
          <select className="select" style={{ width: 140 }} value={owner} onChange={e => setOwner(e.target.value)} aria-label="담당자">
            <option value="">모든 담당자</option>{owners.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
      </div>
      <div className="card">
        {jobs === null ? <div className="empty"><span className="spin" aria-hidden /></div>
          : !shown.length ? <div className="empty"><span className="empty-icon" aria-hidden>✅</span>
              <span>{tasks.length ? "조건에 맞는 할 일이 없습니다." : "아직 승인된 할 일이 없습니다. 회의를 검토·승인하면 여기에 모입니다."}</span></div>
          : <div className="table-wrap"><table className="table">
              <thead><tr><th>할 일</th><th>담당자</th><th>기한</th><th>우선순위</th><th>회의</th><th>승인</th></tr></thead>
              <tbody>{shown.map(t => <tr key={t.key}>
                <td style={{ fontWeight: 600 }}>{t.description}</td>
                <td>{t.assignee || <span className="subtle">미정</span>}</td>
                <td>{t.due_date || <span className="subtle">미정</span>}</td>
                <td><PriorityBadge priority={t.priority} /></td>
                <td><a href={`/?meeting=${t.job.id}`}>{t.job.title}</a></td>
                <td className="subtle">{displayActor(t.job.decided_by)} · {formatWhen(t.job.decided_at)}</td>
              </tr>)}</tbody>
            </table></div>}
      </div>
    </main>
  </AppShell>;
}
