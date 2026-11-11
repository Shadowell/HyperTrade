import { useEffect, useState } from "react";

/**
 * The current time, refreshed on an interval. `null` until the first tick, so a component never
 * reads the clock while rendering (which would make its output depend on when it happened to run).
 */
export function useNow(intervalMs = 30_000): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = window.setTimeout(tick, 0);
    const timer = window.setInterval(tick, intervalMs);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(timer);
    };
  }, [intervalMs]);
  return now;
}
