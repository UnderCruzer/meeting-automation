import { useEffect, useState } from "react";
import { secondsUntil } from "@/lib/meetingTime";

/**
 * Returns seconds remaining until targetIso.
 * Fires onZero once when the countdown hits 0.
 */
export function useCountdown(targetIso: string | null, onZero?: () => void) {
  const [secondsLeft, setSecondsLeft] = useState<number>(
    targetIso ? secondsUntil(targetIso) : 0
  );

  useEffect(() => {
    if (!targetIso) return;

    const tick = () => {
      const s = secondsUntil(targetIso);
      setSecondsLeft(s);
      if (s <= 0) {
        clearInterval(id);
        onZero?.();
      }
    };

    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [targetIso, onZero]);

  return secondsLeft;
}
