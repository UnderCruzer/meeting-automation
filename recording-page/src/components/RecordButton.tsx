import { RecorderStatus } from "@/hooks/useRecorder";

interface RecordButtonProps {
  status: RecorderStatus;
  onRequestMic: () => void;
  onStop: () => void;
}

export function RecordButton({ status, onRequestMic, onStop }: RecordButtonProps) {
  if (status === "idle") {
    return (
      <button style={{ ...styles.btn, background: "#228be6" }} onClick={onRequestMic}>
        🎙️ 마이크 권한 허용
      </button>
    );
  }
  if (status === "requesting") {
    return <button style={{ ...styles.btn, background: "#868e96" }} disabled>권한 요청 중...</button>;
  }
  if (status === "ready") {
    return <button style={{ ...styles.btn, background: "#868e96" }} disabled>⏳ 회의 시작 대기 중...</button>;
  }
  if (status === "recording") {
    return (
      <button style={{ ...styles.btn, background: "#fa5252" }} onClick={onStop}>
        ⏹ 녹음 중지
      </button>
    );
  }
  if (status === "stopped") {
    return <button style={{ ...styles.btn, background: "#40c057" }} disabled>✅ 녹음 완료</button>;
  }
  return null;
}

const styles: Record<string, React.CSSProperties> = {
  btn: {
    padding: "14px 32px",
    fontSize: 16,
    fontWeight: 600,
    color: "#fff",
    border: "none",
    borderRadius: 10,
    cursor: "pointer",
    transition: "opacity 0.2s",
  },
};
