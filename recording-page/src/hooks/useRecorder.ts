import { useCallback, useRef, useState } from "react";

export type RecorderStatus = "idle" | "requesting" | "ready" | "recording" | "stopped" | "error";

export interface UseRecorderReturn {
  status: RecorderStatus;
  error: string | null;
  audioBlob: Blob | null;
  requestMic: () => Promise<void>;
  startRecording: () => void;
  stopRecording: () => void;
}

export function useRecorder(): UseRecorderReturn {
  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const statusRef = useRef<RecorderStatus>("idle");

  const setStatusSync = (s: RecorderStatus) => {
    statusRef.current = s;
    setStatus(s);
  };

  const requestMic = useCallback(async () => {
    setStatusSync("requesting");
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      setStatusSync("ready");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "마이크 권한을 허용해주세요.";
      setError(msg);
      setStatusSync("error");
    }
  }, []);

  const startRecording = useCallback(() => {
    // Use ref to avoid stale closure on status
    if (!streamRef.current || statusRef.current !== "ready") return;

    chunksRef.current = [];
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/mp4";

    const recorder = new MediaRecorder(streamRef.current, { mimeType });
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    // Set status AFTER blob is ready so upload effect sees both atomically
    recorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: mimeType });
      streamRef.current?.getTracks().forEach((t) => t.stop());
      setAudioBlob(blob);
      setStatusSync("stopped");
    };

    recorder.start(1000);
    recorderRef.current = recorder;
    setStatusSync("recording");
  }, []); // no status dep — reads from statusRef

  const stopRecording = useCallback(() => {
    recorderRef.current?.stop();
    // status is set in onstop handler after blob is ready
  }, []);

  return { status, error, audioBlob, requestMic, startRecording, stopRecording };
}
