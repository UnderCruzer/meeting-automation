import { useEffect, useRef, useState } from "react";
import { secondsUntil } from "@/lib/meetingTime";

/**
 * Returns seconds remaining until targetIso.
 * Fires onZero once when the countdown hits 0.
 * Uses a ref for onZero so the interval never restarts on callback identity changes.
 */
export function useCountdown(targetIso: string | null, onZero?: () => void) {
  const [secondsLeft, setSecondsLeft] = useState<number>(
    targetIso ? Math.max(0, secondsUntil(targetIso)) : 0
  );
  const onZeroRef = useRef(onZero);

  useEffect(() => {
    onZeroRef.current = onZero;
  });

  useEffect(() => {
    if (!targetIso) return;

    let id: ReturnType<typeof setInterval>;

    const tick = () => {
      const s = secondsUntil(targetIso);
      if (!Number.isFinite(s)) return; // guard against NaN on bad ISO
      setSecondsLeft(Math.max(0, s));
      if (s <= 0) {
        clearInterval(id);
        onZeroRef.current?.();
      }
    };

    tick();
    id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [targetIso]); // onZero intentionally excluded — accessed via ref

  return secondsLeft;
}
