import { useEffect, useState } from "react";

/** The current time, ticking every `ms` while `live`; a finished run stops its clock. */
export function useNow(ms = 1_000, live = true): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(timer);
  }, [ms, live]);
  return now;
}
