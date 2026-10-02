import type { Job } from "@/lib/workspace";
import { formatWhen } from "@/lib/workspace";
import StatusBadge from "@/components/StatusBadge";

const GROUPS: Array<[string, Job["status"][]]> = [
  ["검토 대기", ["review"]],
  ["분석 중", ["processing"]],
  ["실패", ["failed"]],
  ["완료", ["approved", "rejected"]],
];

export default function MeetingList({ jobs, selected, onSelect }: {
  jobs: Job[]; selected: string; onSelect: (id: string) => void;
}) {
  if (!jobs.length) return <div className="empty" style={{ padding: "40px 16px" }}>
    <span>아직 올린 회의가 없습니다.</span></div>;
  return <div className="list" role="list">
    {GROUPS.map(([label, statuses]) => {
      const group = jobs.filter(j => statuses.includes(j.status));
      if (!group.length) return null;
      return <div key={label} role="group" aria-label={label}>
        <div className="list-group">{label}<span className="count">{group.length}</span></div>
        {group.map(job => <button key={job.id} role="listitem" className="list-item" aria-current={selected === job.id}
          onClick={() => onSelect(job.id)}>
          <span className="row"><span className="title" style={{ flex: 1 }}>{job.title}</span><StatusBadge status={job.status} /></span>
          <span className="subtle">{formatWhen(job.created_at)}{job.summary ? ` · 할 일 ${job.summary.action_items.length}개` : ""}</span>
        </button>)}
      </div>;
    })}
  </div>;
}
