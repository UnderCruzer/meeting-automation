"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/workspace";
import { useToast } from "@/components/Toast";

type Count = { code: string; label: string; count: number };
type Metrics = {
  uploads: number; processing: number; succeeded: number; failed: number; success_rate: number | null;
  failures: Count[]; median_processing_minutes: number | null; pending_review: number; approved: number; rejected: number;
  approval_rate: number | null; median_minutes_to_decision: number | null; edited_before_decision_rate: number | null;
  action_items_per_meeting: number | null; task_completion_rate: number | null; tasks_overdue: number;
  avg_confidence: number | null; low_quality: number; feedback: number; positive_feedback_rate: number | null;
  feedback_categories: Count[]; slack_publish_rate: number | null;
};
type Response = { days: number; metrics: Metrics; alerts: { code: string; message: string }[]; alert_channel: boolean };

const pct = (v: number | null) => v === null ? "–" : `${Math.round(v * 100)}%`;
const minutes = (v: number | null) => v === null ? "–" : v >= 120 ? `${(v / 60).toFixed(1)}시간` : `${Math.round(v)}분`;

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return <div className="card tile"><span className="tile-label">{label}</span><span className="tile-value">{value}</span>
    {hint && <span className="tile-hint">{hint}</span>}</div>;
}

/** Single-series bar list: one accent hue, value always printed (no tooltip needed). */
function BarList({ title, rows, empty }: { title: string; rows: Count[]; empty: string }) {
  const max = Math.max(1, ...rows.map(r => r.count));
  return <section className="card card-pad section">
    <h3>{title}</h3>
    {rows.length ? <div className="barlist">{rows.map(r => <div key={r.code} className="barrow" title={`${r.label}: ${r.count}건`}>
      <span>{r.label}</span>
      <div className="bartrack" aria-hidden><div className="barfill" style={{ width: `${(r.count / max) * 100}%` }} /></div>
      <span className="barvalue">{r.count}건</span>
    </div>)}</div> : <p className="subtle">{empty}</p>}
  </section>;
}

/** Workflow 22 — quality metrics, anomalies and where alerts go (admin). */
export default function MetricsPanel() {
  const [days, setDays] = useState<7 | 30>(7);
  const [data, setData] = useState<Response | null>(null);
  const toast = useToast();
  useEffect(() => {
    api<Response>(`/api/workspace/metrics?days=${days}`, undefined, "지표를 불러오지 못했습니다.")
      .then(setData).catch(e => toast(e.message, "error"));
  }, [days, toast]);
  const m = data?.metrics;

  return <div className="stack">
    <div className="row">
      <span className="subtle" style={{ flex: 1 }}>업로드 시각 기준 · 승인·완료·피드백은 같은 기간에 올린 회의 대상</span>
      <div className="segmented" role="group" aria-label="기간">
        {([7, 30] as const).map(d => <button key={d} aria-pressed={days === d} onClick={() => setDays(d)}>최근 {d}일</button>)}
      </div>
    </div>

    {data && data.alerts.map(a => <div key={a.code} className="alert alert-warning" role="alert">
      <span aria-hidden>⚠️</span><div className="alert-body"><strong>품질 경고</strong><span>{a.message}</span></div></div>)}
    {data && !data.alert_channel && <div className="alert alert-info"><div className="alert-body">
      <span>경고와 주간 품질 리포트를 Slack으로 받으려면 관리자용 채널 ID를 <code>MONITOR_ALERT_CHANNEL</code>에 설정하세요.</span></div></div>}

    {!m ? <div className="card empty"><span className="spin" aria-hidden /></div> : <>
      <div className="tiles">
        <Tile label="업로드" value={`${m.uploads}건`} hint={m.processing ? `분석 중 ${m.processing}건` : undefined} />
        <Tile label="처리 성공률" value={pct(m.success_rate)} hint={`성공 ${m.succeeded} · 실패 ${m.failed}`} />
        <Tile label="처리 시간 (중앙값)" value={minutes(m.median_processing_minutes)} hint="업로드부터 검토 대기까지" />
        <Tile label="승인율" value={pct(m.approval_rate)} hint={`승인 ${m.approved} · 거절 ${m.rejected} · 대기 ${m.pending_review}`} />
        <Tile label="승인까지 걸린 시간" value={minutes(m.median_minutes_to_decision)} hint="분석 완료부터 결정까지 (중앙값)" />
        <Tile label="승인 전 수정 비율" value={pct(m.edited_before_decision_rate)} hint="높을수록 AI 결과를 많이 고침" />
        <Tile label="할 일 완료율" value={pct(m.task_completion_rate)} hint={`회의당 ${m.action_items_per_meeting ?? "–"}개 · 기한 지남 ${m.tasks_overdue}건`} />
        <Tile label="평균 AI 신뢰도" value={m.avg_confidence === null ? "–" : m.avg_confidence.toFixed(2)} hint={`품질 경고 ${m.low_quality}건`} />
        <Tile label="긍정 피드백" value={pct(m.positive_feedback_rate)} hint={`피드백 ${m.feedback}건`} />
        <Tile label="Slack 게시 성공률" value={pct(m.slack_publish_rate)} />
      </div>
      <div className="grid-2">
        <BarList title="실패 유형" rows={m.failures} empty="이 기간에 실패한 처리가 없습니다." />
        <BarList title="피드백에서 지적된 문제" rows={m.feedback_categories} empty="부정 피드백이 없습니다." />
      </div>
    </>}
  </div>;
}
