"use client";

import { useCallback, useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { useRecorder } from "@/hooks/useRecorder";
import { useCountdown } from "@/hooks/useCountdown";
import { MeetingInfo } from "@/components/MeetingInfo";
import { RecordButton } from "@/components/RecordButton";
import { formatTime } from "@/lib/meetingTime";

// Meeting metadata passed via query string from Slack DM link
// Real data comes from the backend (issue-06) — for now parsed from URL
interface MeetingMeta {
  id: string;
  title: string;
  startTime: string;
  endTime: string;
  location: string;
}

function parseMeta(params: URLSearchParams): MeetingMeta | null {
  const id = params.get("meetingId");
  const title = params.get("title");
  const startTime = params.get("startTime");
  const endTime = params.get("endTime");
  if (!id || !startTime || !endTime) return null;
  return { id, title: title ?? "(제목 없음)", startTime, endTime, location: params.get("location") ?? "" };
}

export default function RecordPage() {
  const params = useSearchParams();
  const meta = parseMeta(params);
  const { status, error, audioBlob, requestMic, startRecording, stopRecording } = useRecorder();
  const startedRef = useRef(false);

  const handleCountdownZero = useCallback(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    startRecording();
  }, [startRecording]);

  const secondsLeft = useCountdown(
    status === "ready" ? meta?.startTime ?? null : null,
    handleCountdownZero,
  );

  // Auto-stop when meeting end time is reached
  useEffect(() => {
    if (!meta?.endTime || status !== "recording") return;
    const msLeft = new Date(meta.endTime).getTime() - Date.now();
    if (msLeft <= 0) { stopRecording(); return; }
    const id = setTimeout(stopRecording, msLeft);
    return () => clearTimeout(id);
  }, [meta?.endTime, status, stopRecording]);

  // Trigger upload when recording stops (issue-06)
  useEffect(() => {
    if (status === "stopped" && audioBlob && meta) {
      uploadAudio(audioBlob, meta);
    }
  }, [status, audioBlob, meta]);

  if (!meta) {
    return (
      <main style={styles.main}>
        <p style={{ color: "#fa5252" }}>잘못된 접근입니다. Slack DM의 링크를 통해 접속해주세요.</p>
      </main>
    );
  }

  return (
    <main style={styles.main}>
      <h1 style={styles.heading}>🎙️ 회의 녹음</h1>

      <MeetingInfo
        title={meta.title}
        startTime={meta.startTime}
        endTime={meta.endTime}
        location={meta.location}
      />

      {/* Status indicator */}
      <div style={styles.statusRow}>
        {status === "recording" && (
          <span style={styles.recBadge}>● REC</span>
        )}
        {status === "ready" && secondsLeft > 0 && (
          <span style={styles.countdown}>
            {formatTime(meta.startTime)} 시작까지 {secondsLeft}초
          </span>
        )}
        {status === "stopped" && (
          <span style={{ color: "#40c057", fontWeight: 600 }}>✅ 녹음 완료 — 업로드 중...</span>
        )}
      </div>

      {error && <p style={styles.error}>{error}</p>}

      <RecordButton
        status={status}
        onRequestMic={requestMic}
        onStop={stopRecording}
      />
    </main>
  );
}

async function uploadAudio(blob: Blob, meta: MeetingMeta) {
  const apiUrl = process.env.NEXT_PUBLIC_UPLOAD_API_URL ?? "http://localhost:8000";
  const form = new FormData();
  const ext = blob.type.includes("mp4") ? "mp4" : "webm";
  form.append("audio", blob, `recording.${ext}`);
  form.append("metadata", JSON.stringify({
    meetingId: meta.id,
    title: meta.title,
    startTime: meta.startTime,
    endTime: meta.endTime,
    location: meta.location,
  }));

  try {
    const res = await fetch(`${apiUrl}/upload`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
    console.log("[Upload] Success");
  } catch (err) {
    console.error("[Upload] Error:", err);
  }
}

const styles: Record<string, React.CSSProperties> = {
  main: {
    maxWidth: 480,
    margin: "48px auto",
    padding: "0 24px",
    fontFamily: "system-ui, sans-serif",
    color: "#212529",
  },
  heading: { fontSize: 24, fontWeight: 700, marginBottom: 24 },
  statusRow: { minHeight: 32, marginBottom: 20, display: "flex", alignItems: "center" },
  recBadge: {
    background: "#fa5252",
    color: "#fff",
    padding: "4px 12px",
    borderRadius: 20,
    fontSize: 13,
    fontWeight: 700,
    animation: "pulse 1.2s infinite",
  },
  countdown: { color: "#868e96", fontSize: 14 },
  error: { color: "#fa5252", fontSize: 14, marginBottom: 12 },
};
