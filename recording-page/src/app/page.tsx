"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import MeetingList from "@/components/MeetingList";
import MeetingDetail from "@/components/MeetingDetail";
import UploadDialog, { type UploadDialogHandle } from "@/components/UploadDialog";
import { useToast } from "@/components/Toast";
import type { Job } from "@/lib/workspace";
import { api } from "@/lib/workspace";

export default function MeetingsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [selected, setSelected] = useState("");
  const [ephemeral, setEphemeral] = useState(false);
  const [slack, setSlack] = useState(false);
  const upload = useRef<UploadDialogHandle>(null);
  const toast = useToast();

  const refresh = useCallback(async () => {
    setJobs(await api<Job[]>("/api/workspace/jobs", undefined, "회의 목록을 불러오지 못했습니다."));
  }, []);

  useEffect(() => {
    let active = true;
    api<{ ephemeral: boolean; slackPublishing?: boolean }>("/api/workspace/config")
      .then(c => { if (active) { setEphemeral(c.ephemeral); setSlack(!!c.slackPublishing); } }).catch(() => {});
    let failed = false;
    const load = () => refresh().then(() => { failed = false; }).catch(e => {
      if (active && !failed) { failed = true; toast(e.message, "error"); }
    });
    load(); const timer = setInterval(load, 5000);
    return () => { active = false; clearInterval(timer); };
  }, [refresh, toast]);

  // Deep link (?meeting=…, e.g. from the 할 일 page) or, on desktop, the first meeting needing attention.
  useEffect(() => {
    if (selected || !jobs?.length) return;
    const linked = new URLSearchParams(window.location.search).get("meeting");
    if (linked && jobs.some(j => j.id === linked)) { setSelected(linked); return; }
    if (window.matchMedia("(max-width: 960px)").matches) return;
    setSelected((jobs.find(j => j.status === "review") ?? jobs[0]).id);
  }, [jobs, selected]);

  // On narrow screens the detail replaces the list, so bring its top into view.
  useEffect(() => {
    if (selected && window.matchMedia("(max-width: 960px)").matches)
      document.querySelector(".split")?.scrollIntoView({ block: "start" });
  }, [selected]);

  const current = jobs?.find(j => j.id === selected);
  const pending = jobs?.filter(j => j.status === "review").length ?? 0;

  return <AppShell section="meetings">
    <main className="page">
      <div className="page-head">
        <div><h1>회의</h1><p className="muted">녹음 → 요약·할 일 → 검토·승인 → 팀 공유</p></div>
        <button className="btn btn-primary btn-lg" onClick={() => upload.current?.open()}>+ 녹음 올리기</button>
      </div>
      {ephemeral && <div className="alert alert-warning"><div className="alert-body">
        <strong>체험용 서버</strong><span>재시작·재배포 시 회의 기록이 초기화됩니다. 보존할 자료는 올리지 마세요.</span></div></div>}

      <div className="split" data-view={current ? "detail" : "list"}>
        <aside className="sidebar card" aria-label="회의 목록">
          <div className="row sidebar-head">
            <h2>회의 기록</h2>
            {pending > 0 && <span className="badge badge-accent">검토 대기 {pending}</span>}
          </div>
          {jobs === null ? <div className="empty"><span className="spin" aria-hidden /></div>
            : <MeetingList jobs={jobs} selected={selected} onSelect={setSelected} />}
        </aside>
        <section className="detail-pane" aria-live="polite">
          {current
            ? <MeetingDetail key={current.id} job={current} slack={slack} onChanged={refresh}
                onDeleted={() => { setSelected(""); refresh().catch(() => {}); }} onBack={() => setSelected("")} />
            : <div className="card empty">
                <strong>{jobs?.length ? "왼쪽에서 회의를 선택하세요" : "첫 회의 녹음을 올려보세요"}</strong>
                <span>녹음 파일을 올리거나, 캘린더를 연결하면 회의 전에 Slack으로 녹음 링크가 옵니다.</span>
                {!jobs?.length && <button className="btn btn-primary" onClick={() => upload.current?.open()}>녹음 올리기</button>}
              </div>}
        </section>
      </div>
    </main>
    <UploadDialog ref={upload} onError={m => toast(m, "error")}
      onUploaded={id => { toast("업로드했습니다. 분석이 끝나면 검토할 수 있습니다."); setSelected(id); refresh().catch(() => {}); }} />
  </AppShell>;
}
