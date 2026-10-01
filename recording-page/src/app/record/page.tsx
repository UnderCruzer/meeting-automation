"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useRecorder } from "@/hooks/useRecorder";
import { useCountdown } from "@/hooks/useCountdown";
import { useWaveform } from "@/hooks/useWaveform";
import { MeetingInfo } from "@/components/MeetingInfo";
import { RecordButton } from "@/components/RecordButton";
import { formatTime } from "@/lib/meetingTime";
import { decodeGrant } from "@/lib/recordingGrant";

interface MeetingMeta {
  id: string;
  title: string;
  startTime: string;
  endTime: string;
  location: string;
}

// useSearchParams() must be inside a Suspense boundary (Next.js 14 requirement)
export default function RecordPageWrapper() {
  return (
    <Suspense fallback={<main className="center-page"><span className="spin" aria-label="로딩 중" /></main>}>
      <RecordPage />
    </Suspense>
  );
}

function RecordPage() {
  const params = useSearchParams();
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadDone, setUploadDone] = useState(false);

  // Signed link from the Slack DM (verified by the server before this page loads).
  const grant = params?.get("grant") ?? null;

  const meta = useMemo<MeetingMeta | null>(() => {
    // Typed nullable once a pages/ directory exists; always set under the App Router.
    if (!params) return null;
    const signed = grant ? decodeGrant(grant) : null;
    if (signed) return { id: signed.m, title: signed.t || "(제목 없음)", startTime: signed.s, endTime: signed.e, location: signed.l };
    const id = params.get("meetingId");
    const startTime = params.get("startTime");
    const endTime = params.get("endTime");
    if (!id || !startTime || !endTime) return null;
    return {
      id,
      title: params.get("title") ?? "(제목 없음)",
      startTime,
      endTime,
      location: params.get("location") ?? "",
    };
  }, [params, grant]);

  const { status, error, audioBlob, stream, requestMic, startRecording, stopRecording } = useRecorder();
  const startedRef = useRef(false);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useWaveform(canvasRef, stream, status === "recording");

  const handleCountdownZero = useCallback(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    startRecording();
  }, [startRecording]);

  const secondsLeft = useCountdown(
    status === "ready" ? meta?.startTime ?? null : null,
    handleCountdownZero,
  );

  const endTime = meta?.endTime ?? null;
  useEffect(() => {
    if (!endTime || status !== "recording") return;
    const msLeft = new Date(endTime).getTime() - Date.now();
    if (msLeft <= 0) { stopRecording(); return; }
    const id = setTimeout(stopRecording, msLeft);
    return () => clearTimeout(id);
  }, [endTime, status, stopRecording]);

  useEffect(() => {
    if (status !== "stopped" || !audioBlob || !meta) return;
    uploadAudio(audioBlob, meta, grant)
      .then(() => setUploadDone(true))
      .catch((err) => {
        setUploadError(err instanceof Error ? err.message : "업로드 실패");
      });
  }, [status, audioBlob, meta, grant]);

  if (!meta) {
    return (
      <main className="center-page">
        <div className="card record-card">
          <div className="alert alert-danger" role="alert"><div className="alert-body">잘못된 접근이거나 만료된 링크입니다. Slack DM의 최신 링크로 접속해주세요.</div></div>
        </div>
      </main>
    );
  }

  return (
    <main className="center-page">
      <div className="card record-card">
        <div className="row">
          <span className="brand-mark" aria-hidden>◆</span>
          <h1 style={{ fontSize: 18 }}>회의 녹음</h1>
          <span className="spacer" />
          {status === "recording" && <span className="badge badge-danger badge-plain"><span className="rec-dot" aria-hidden />REC</span>}
        </div>

        <MeetingInfo
          title={meta.title}
          startTime={meta.startTime}
          endTime={meta.endTime}
          location={meta.location}
        />

        <canvas ref={canvasRef} width={464} height={72} className="waveform" aria-label="오디오 파형" />

        <div role="status" aria-live="polite">
          {status === "idle" && <p className="muted">마이크 권한을 허용하면 회의 시작 시각에 자동으로 녹음을 시작하고, 종료 시각에 멈춘 뒤 업로드합니다.</p>}
          {status === "ready" && secondsLeft > 0 && (
            <div className="alert alert-info"><div className="alert-body">{formatTime(meta.startTime)} 시작까지 <strong>{secondsLeft}초</strong> — 이 창을 닫지 마세요.</div></div>
          )}
          {status === "recording" && <p className="muted">녹음 중입니다. 회의가 끝나면 자동으로 멈추고 업로드합니다.</p>}
          {status === "encoding" && <p className="muted">녹음을 변환하고 있습니다…</p>}
          {status === "stopped" && !uploadError && !uploadDone && (
            <div className="alert alert-info"><span className="spin" aria-hidden /><div className="alert-body">업로드 중… 창을 닫지 마세요.</div></div>
          )}
          {uploadDone && !uploadError && (
            <div className="alert alert-success"><div className="alert-body">✅ 업로드 완료. 분석이 끝나면 담당자가 검토 후 공유합니다. 이 창은 닫아도 됩니다.</div></div>
          )}
          {uploadError && (
            <div className="alert alert-danger" role="alert"><div className="alert-body">업로드 실패: {uploadError}</div></div>
          )}
        </div>

        {error && <div className="alert alert-danger" role="alert"><div className="alert-body">{error}</div></div>}

        <RecordButton
          status={status}
          onRequestMic={requestMic}
          onStop={stopRecording}
        />
      </div>
    </main>
  );
}

async function uploadAudio(blob: Blob, meta: MeetingMeta, grant: string | null): Promise<void> {
  const form = new FormData();
  form.append("audio", blob, "recording.wav");
  form.append("metadata", JSON.stringify({
    meetingId: meta.id,
    title: meta.title,
    startTime: meta.startTime,
    endTime: meta.endTime,
    location: meta.location,
  }));

  // Proxy via /api/upload so BACKEND_API_KEY never leaks to the browser bundle
  const MAX_RETRIES = 3;
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    let res: Response;
    try {
      res = await fetch("/api/upload", {
        method: "POST", body: form, headers: grant ? { "X-Recording-Grant": grant } : undefined,
      });
    } catch (networkErr) {
      // Network failure (offline, DNS, timeout) — always retry
      if (attempt === MAX_RETRIES) throw networkErr;
      await new Promise((r) => setTimeout(r, 1000 * 2 ** (attempt - 1)));
      continue;
    }
    if (res.ok) return;
    // 4xx = client error (bad metadata, too large) — no point retrying
    if (res.status < 500) throw new Error(`Upload failed: ${res.status}`);
    // 5xx = server error — retry
    if (attempt === MAX_RETRIES) throw new Error(`Upload failed: ${res.status}`);
    await new Promise((r) => setTimeout(r, 1000 * 2 ** (attempt - 1)));
  }
}
