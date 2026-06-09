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

  const requestMic = useCallback(async () => {
    setStatus("requesting");
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      setStatus("ready");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "마이크 권한을 허용해주세요.";
      setError(msg);
      setStatus("error");
    }
  }, []);

  const startRecording = useCallback(() => {
    if (!streamRef.current || status !== "ready") return;

    chunksRef.current = [];
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/mp4";

    const recorder = new MediaRecorder(streamRef.current, { mimeType });
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    recorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: mimeType });
      setAudioBlob(blob);
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };

    recorder.start(1000); // collect chunks every 1s
    recorderRef.current = recorder;
    setStatus("recording");
  }, [status]);

  const stopRecording = useCallback(() => {
    recorderRef.current?.stop();
    setStatus("stopped");
  }, []);

  return { status, error, audioBlob, requestMic, startRecording, stopRecording };
}
