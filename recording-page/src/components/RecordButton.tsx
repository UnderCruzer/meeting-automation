import { RecorderStatus } from "@/hooks/useRecorder";

interface RecordButtonProps {
  status: RecorderStatus;
  onRequestMic: () => void;
  onStop: () => void;
}

export function RecordButton({ status, onRequestMic, onStop }: RecordButtonProps) {
  const cls = "btn btn-lg btn-block";
  if (status === "idle") return <button className={`${cls} btn-primary`} onClick={onRequestMic}>🎙️ 마이크 권한 허용</button>;
  if (status === "requesting") return <button className={cls} disabled><span className="spin" aria-hidden />권한 요청 중…</button>;
  if (status === "ready") return <button className={cls} disabled>⏳ 회의 시작 대기 중…</button>;
  if (status === "recording") return <button className={`${cls} btn-danger`} onClick={onStop}>⏹ 녹음 중지</button>;
  if (status === "encoding") return <button className={cls} disabled><span className="spin" aria-hidden />WAV 변환 중…</button>;
  if (status === "stopped") return <button className={cls} disabled>✅ 녹음 완료</button>;
  return null;
}
