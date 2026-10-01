const STATUS: Record<string, [string, string]> = {
  processing: ["분석 중", "badge-info"],
  review: ["검토 대기", "badge-accent"],
  approved: ["승인 완료", "badge-success"],
  rejected: ["거절됨", ""],
  failed: ["처리 실패", "badge-danger"],
};

export const STATUS_LABEL = Object.fromEntries(Object.entries(STATUS).map(([k, [label]]) => [k, label]));

export default function StatusBadge({ status }: { status: string }) {
  const [label, tone] = STATUS[status] ?? [status, ""];
  return <span className={`badge ${tone}`}>{label}</span>;
}

const PRIORITY: Record<string, string> = { high: "높음", medium: "보통", low: "낮음" };

export function PriorityBadge({ priority = "medium" }: { priority?: string }) {
  return <span className={`badge badge-plain badge-${priority}`}>{PRIORITY[priority] ?? priority}</span>;
}
