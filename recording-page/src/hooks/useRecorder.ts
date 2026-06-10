import { useCallback, useRef, useState } from "react";
import { encodeToWav } from "@/lib/audioEncoder";

export type RecorderStatus = "idle" | "requesting" | "ready" | "recording" | "encoding" | "stopped" | "error";

export interface UseRecorderReturn {
  status: RecorderStatus;
  error: string | null;
  audioBlob: Blob | null;
  stream: MediaStream | null;
  requestMic: () => Promise<void>;
  startRecording: () => void;
  stopRecording: () => void;
}

export function useRecorder(): UseRecorderReturn {
  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);

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
      // 16kHz mono preferred for STT compatibility
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16_000, channelCount: 1, echoCancellation: true },
      });
      streamRef.current = mediaStream;
      setStream(mediaStream);
      setStatusSync("ready");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "마이크 권한을 허용해주세요.";
      setError(msg);
      setStatusSync("error");
    }
  }, []);

  const startRecording = useCallback(() => {
    if (!streamRef.current || statusRef.current !== "ready") return;

    chunksRef.current = [];
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus"
      : "audio/mp4";

    const recorder = new MediaRecorder(streamRef.current, { mimeType });
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    recorder.onstop = () => {
      const rawBlob = new Blob(chunksRef.current, { type: mimeType });
      streamRef.current?.getTracks().forEach((t) => t.stop());
      setStream(null);

      // Re-encode to 16kHz mono WAV for STT compatibility
      setStatusSync("encoding");
      encodeToWav(rawBlob, 16_000)
        .then((wavBlob) => {
          setAudioBlob(wavBlob);
          setStatusSync("stopped");
        })
        .catch(() => {
          // Fallback: use raw blob if WAV encoding fails
          setAudioBlob(rawBlob);
          setStatusSync("stopped");
        });
    };

    recorder.start(1000);
    recorderRef.current = recorder;
    setStatusSync("recording");
  }, []);

  const stopRecording = useCallback(() => {
    recorderRef.current?.stop();
  }, []);

  return { status, error, audioBlob, stream, requestMic, startRecording, stopRecording };
}
