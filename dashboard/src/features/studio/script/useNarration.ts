// A draft's narration state, read once and polled while it runs (spec 2026-10-31).
import { useEffect, useRef, useState } from "react";

import type { ControlPlaneClient, NarrationState } from "@/api/control-plane";

const ACTIVE = new Set(["transcribing", "scripting", "awaiting_approval", "voicing", "writing"]);

/** While a narration is in one of these states it owns the draft. */
export function isNarrationActive(state: NarrationState | null): boolean {
  return state !== null && ACTIVE.has(state.status);
}

/**
 * `[state, setState]`: null until a narration exists. While one runs the state is read every
 * `intervalMs`; when a running narration completes, `onCompleted` runs once so Studio can
 * adopt the revision the narration wrote.
 */
export function useNarration(
  client: Pick<ControlPlaneClient, "getNarration"> | undefined,
  projectId: string,
  documentId: string,
  enabled: boolean,
  onCompleted: () => void,
  intervalMs = 3000,
): [NarrationState | null, (state: NarrationState) => void] {
  const [state, setState] = useState<NarrationState | null>(null);
  const wasActive = useRef(false);
  const completed = useRef(onCompleted);
  useEffect(() => {
    completed.current = onCompleted;
  }, [onCompleted]);

  useEffect(() => {
    if (!enabled || !client) return;
    let stopped = false;
    // A draft with no narration answers 404: it simply has none yet.
    void client.getNarration(projectId, documentId).then((loaded) => !stopped && setState(loaded), () => {});
    return () => {
      stopped = true;
    };
  }, [client, projectId, documentId, enabled]);

  const active = isNarrationActive(state);
  useEffect(() => {
    if (active) wasActive.current = true;
    else if (wasActive.current && state?.status === "completed") {
      wasActive.current = false;
      completed.current();
    }
    if (!active || !client) return;
    const timer = setTimeout(() => {
      void client.getNarration(projectId, documentId).then(setState, () => {});
    }, intervalMs);
    return () => clearTimeout(timer);
  }, [active, state, client, projectId, documentId, intervalMs]);

  return [state, setState];
}
