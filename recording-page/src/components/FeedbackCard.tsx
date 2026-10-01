"use client";
import { useEffect, useState } from "react";
import { api, jsonInit } from "@/lib/workspace";
import { useToast } from "@/components/Toast";

const CATEGORIES: Array<[string, string]> = [
  ["summary_missing", "요약 누락·왜곡"], ["action_missing", "할 일 누락"], ["owner_wrong", "담당자·기한 오류"],
  ["citation_wrong", "근거 부정확"], ["other", "기타"],
];
type Feedback = { mine: null | { rating: "good" | "bad"; categories: string[]; note: string }; good: number; bad: number };

/** Workflow 22 — was this summary right? Feeds quality metrics and alerts. */
export default function FeedbackCard({ jobId }: { jobId: string }) {
  const [data, setData] = useState<Feedback | null>(null);
  const [rating, setRating] = useState<"good" | "bad" | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  useEffect(() => {
    api<Feedback>(`/api/workspace/jobs/${jobId}/feedback`).then(d => {
      setData(d);
      if (d.mine) { setRating(d.mine.rating); setCategories(d.mine.categories); setNote(d.mine.note); }
    }).catch(() => {});
  }, [jobId]);

  async function submit(next: "good" | "bad") {
    setBusy(true);
    try {
      await api(`/api/workspace/jobs/${jobId}/feedback`,
        jsonInit("POST", { rating: next, categories: next === "bad" ? categories : [], note }), "피드백을 저장하지 못했습니다.");
      setRating(next);
      setData(await api<Feedback>(`/api/workspace/jobs/${jobId}/feedback`));
      toast("피드백을 저장했습니다. 품질 개선에 사용됩니다.");
    } catch (e) { toast(e instanceof Error ? e.message : "저장 실패", "error"); }
    finally { setBusy(false); }
  }

  const toggle = (code: string) => setCategories(list => list.includes(code) ? list.filter(c => c !== code) : [...list, code]);

  return <section className="card card-pad section" aria-labelledby={`fb-${jobId}`}>
    <div className="section-title"><h2 id={`fb-${jobId}`}>요약이 정확했나요?</h2>
      {data && (data.good + data.bad > 0) && <span className="subtle">팀 피드백 👍 {data.good} · 👎 {data.bad}</span>}</div>
    <div className="row">
      <button className="btn" aria-pressed={rating === "good"} disabled={busy}
        style={rating === "good" ? { borderColor: "var(--success)", color: "var(--success)" } : undefined}
        onClick={() => submit("good")}>👍 정확해요</button>
      <button className="btn" aria-pressed={rating === "bad"} disabled={busy}
        style={rating === "bad" ? { borderColor: "var(--danger)", color: "var(--danger)" } : undefined}
        onClick={() => setRating("bad")}>👎 고칠 점이 있어요</button>
    </div>
    {rating === "bad" && <div className="stack" style={{ gap: 10 }}>
      <div className="chips" role="group" aria-label="문제 유형">
        {CATEGORIES.map(([code, label]) => <button key={code} type="button" className="chip"
          aria-pressed={categories.includes(code)} onClick={() => toggle(code)}>{label}</button>)}
      </div>
      <textarea className="textarea" rows={2} maxLength={1000} placeholder="무엇이 틀렸는지 적어주면 개선에 도움이 됩니다 (선택)"
        value={note} onChange={e => setNote(e.target.value)} aria-label="메모" />
      <div className="row"><span className="spacer" />
        <button className="btn btn-primary" disabled={busy} onClick={() => submit("bad")}>피드백 보내기</button></div>
    </div>}
  </section>;
}
