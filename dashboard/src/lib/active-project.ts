import { useCallback, useState } from "react";

const KEY = "thoth.activeProject";

function stored(): string | null {
  try {
    return globalThis.localStorage?.getItem(KEY) ?? null;
  } catch {
    return null;
  }
}

/** The active project, remembered per browser; a blocked storage only forgets it on reload. */
export function useActiveProject(): [string | null, (id: string | null) => void] {
  const [projectId, setProjectId] = useState<string | null>(stored);
  const set = useCallback((id: string | null) => {
    setProjectId(id);
    try {
      if (id) localStorage.setItem(KEY, id);
      else localStorage.removeItem(KEY);
    } catch {
      // A per-viewer convenience only.
    }
  }, []);
  return [projectId, set];
}
