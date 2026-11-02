// A draft's narration state, read once and polled while it runs (spec 2026-10-31).
import { useEffect, useRef, useState } from "react";

import { StudioImportRequestError, type ControlPlaneClient, type EditDocument, type NarrationState } from "@/api/control-plane";

import type { EditorAction } from "../editor_state";

const ACTIVE = new Set(["transcribing", "scripting", "awaiting_approval", "voicing", "writing"]);

/**
 * Adopt the revision a narration wrote. It is offered as a newer revision and then
 * reloaded, so edits queued while the draft was locked are dropped, never replayed onto
 * the retimed draft.
 */
export function adoptNarratedRevision(dispatch: (action: EditorAction) => void, latest: EditDocument): void {
  dispatch({ type: "save_conflicted", latest });
  dispatch({ type: "reload_latest" });
}

/** While a narration is in one of these states it owns the draft. */
export function isNarrationActive(state: NarrationState | null): boolean {
  return state !== null && ACTIVE.has(state.status);
}

/**
 * `[state, setState, known]`: null until a narration exists, and `known` once a read has told
 * "none yet" from "not read yet". While one runs the state is read every `intervalMs`; when a
 * running narration completes, `onCompleted` runs once so Studio can adopt the revision the
 * narration wrote.
 */
export function useNarration(
  client: Pick<ControlPlaneClient, "getNarration"> | undefined,
  projectId: string,
  documentId: string,
  enabled: boolean,
  onCompleted: () => void,
  intervalMs = 3000,
): [NarrationState | null, (state: NarrationState) => void, boolean] {
  const [state, setState] = useState<NarrationState | null>(null);
  const [known, setKnown] = useState(false);
  // A failed read changes no state, so it bumps this to schedule the next one.
  const [retry, setRetry] = useState(0);
  const wasActive = useRef(false);
  const completed = useRef(onCompleted);
  useEffect(() => {
    completed.current = onCompleted;
  }, [onCompleted]);

  useEffect(() => {
    if (!enabled || !client) return;
    let stopped = false;
    let again: ReturnType<typeof setTimeout> | undefined;
    const read = () =>
      void client.getNarration(projectId, documentId).then(
        (loaded) => {
          if (stopped) return;
          setState(loaded);
          setKnown(true);
        },
        (error) => {
          if (stopped) return;
          // No connection or a server fault says nothing about the draft, so it is asked again.
          // Any other refusal, like the 404 of a draft with no narration, is its answer.
          if (error instanceof StudioImportRequestError && (error.status === null || error.status >= 500)) again = setTimeout(read, intervalMs);
          else setKnown(true);
        },
      );
    read();
    return () => {
      stopped = true;
      clearTimeout(again);
    };
  }, [client, projectId, documentId, enabled, intervalMs]);

  const active = isNarrationActive(state);
  useEffect(() => {
    if (active) wasActive.current = true;
    else if (wasActive.current && state?.status === "completed") {
      wasActive.current = false;
      completed.current();
    }
    if (!active || !client) return;
    const timer = setTimeout(() => {
      void client.getNarration(projectId, documentId).then(setState, () => setRetry((value) => value + 1));
    }, intervalMs);
    return () => clearTimeout(timer);
  }, [active, state, retry, client, projectId, documentId, intervalMs]);

  return [state, setState, known];
}
