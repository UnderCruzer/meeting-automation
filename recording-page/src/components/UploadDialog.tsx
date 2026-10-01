"use client";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { encodeToWav } from "@/lib/audioEncoder";

// Backend MAX_FILE_BYTES is 500 MB (~4.5 h of 16kHz mono WAV).
const MAX_WAV_BYTES = 500 * 1024 * 1024;
const MAX_SOURCE_BYTES = 100 * 1024 * 1024;

export type UploadDialogHandle = { open: () => void };

/** Upload a recording: title, participants (for name pseudonymisation), file, consent. */
const UploadDialog = forwardRef<UploadDialogHandle, {
  onUploaded: (jobId: string) => void; onError: (message: string) => void;
}>(function UploadDialog({ onUploaded, onError }, ref) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  useImperativeHandle(ref, () => ({ open: () => dialog.current?.showModal() }));

  function pick(next: File | undefined) {
    if (!next) return;
    if (!next.type.startsWith("audio/") && !/\.(m4a|mp3|wav|webm|ogg|aac|flac)$/i.test(next.name)) {
      onError("음성 파일만 올릴 수 있습니다."); return;
    }
    if (next.size > MAX_SOURCE_BYTES) { onError("100MB 이하의 음성 파일을 선택해주세요."); return; }
    setFile(next);
  }

  function reset(form?: HTMLFormElement) {
    form?.reset(); setFile(null); setConsent(false);
  }

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!file) { onError("녹음 파일을 선택해주세요."); return; }
    const form = e.currentTarget; const data = new FormData(form);
    setBusy(true);
    try {
      const wav = await encodeToWav(file); const now = new Date().toISOString();
      if (wav.size > MAX_WAV_BYTES) throw new Error("녹음이 너무 깁니다. 4시간 이하로 나눠서 올려주세요.");
      const participants = String(data.get("participants") ?? "").split(",").map(n => n.trim()).filter(Boolean);
      const payload = new FormData();
      payload.set("audio", wav, "meeting.wav");
      payload.set("metadata", JSON.stringify({ meetingId: crypto.randomUUID(), title: data.get("title"), startTime: now, endTime: now, participants }));
      const res = await fetch("/api/upload", { method: "POST", body: payload });
      if (!res.ok) throw new Error("업로드하지 못했습니다. 파일 크기와 서버 설정을 확인해주세요.");
      const job = await res.json();
      reset(form); dialog.current?.close(); onUploaded(job.jobId);
    } catch (err) { onError(err instanceof Error ? err.message : "음성 처리에 실패했습니다."); }
    finally { setBusy(false); }
  }

  return <dialog ref={dialog} className="dialog" aria-labelledby="upload-title" onClose={() => !busy && reset()}>
    <form onSubmit={submit}>
      <div className="dialog-head"><h2 id="upload-title">녹음 올리기</h2>
        <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => dialog.current?.close()} aria-label="닫기">✕</button></div>
      <div className="dialog-body">
        <label className="field"><span>회의 제목</span><input className="input" name="title" required maxLength={200} placeholder="예: 주간 프로젝트 회의" /></label>
        <label className="field"><span>참석자 이름 <span className="subtle">(선택)</span></span>
          <input className="input" name="participants" maxLength={1000} placeholder="김민수, 박지은, Sarah Kim" />
          <span className="hint">입력한 이름과 "김민수 팀장"처럼 호칭이 붙은 이름은 AI로 보내기 전에 가명으로 바뀌고, 이 화면에서만 실명으로 보입니다.</span></label>
        <label className="dropzone" data-active={dragging}
          onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
          onDrop={e => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files[0]); }}>
          <input type="file" accept="audio/*" onChange={e => pick(e.target.files?.[0])} />
          <span style={{ fontSize: 26 }} aria-hidden>🎧</span>
          {file ? <><strong>{file.name}</strong><span className="subtle">{(file.size / 1024 / 1024).toFixed(1)}MB · 다른 파일을 고르려면 클릭</span></>
            : <><strong>녹음 파일을 끌어다 놓거나 클릭해서 선택</strong><span className="subtle">m4a·mp3·wav 등 100MB 이하</span></>}
        </label>
        <div className="alert alert-info"><div className="alert-body">
          녹음은 전사 서비스(Groq 또는 OpenAI)로, 개인정보 패턴과 이름을 가린 전사문은 분석 서비스(Gemini 또는 Claude)로 전송됩니다. 원본 녹음은 처리 후 서버에서 삭제됩니다.
        </div></div>
        <label className="check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} required />
          <span>참석자에게 녹음과 외부 AI 처리를 안내하고 동의를 받았습니다.</span></label>
      </div>
      <div className="dialog-foot">
        <button type="button" className="btn" disabled={busy} onClick={() => dialog.current?.close()}>취소</button>
        <button className="btn btn-primary" disabled={busy || !consent || !file}>
          {busy ? <><span className="spin" aria-hidden />변환·업로드 중…</> : "분석 시작"}</button>
      </div>
    </form>
  </dialog>;
});

export default UploadDialog;
