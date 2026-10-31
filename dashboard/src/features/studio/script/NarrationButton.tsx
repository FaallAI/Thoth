// "Create narration" (spec 2026-10-31): the only way a draft's narration starts.
import { useState } from "react";

import { StudioImportRequestError, type ControlPlaneClient, type NarrationState } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

const ACTIVE = new Set(["transcribing", "scripting", "awaiting_approval", "voicing", "writing"]);

export function isNarrationActive(state: NarrationState | null): boolean {
  return state !== null && ACTIVE.has(state.status);
}

export function NarrationButton({
  client,
  projectId,
  documentId,
  state,
  onChange,
}: {
  client: Pick<ControlPlaneClient, "startNarration">;
  projectId: string;
  documentId: string;
  state: NarrationState | null;
  onChange: (state: NarrationState) => void;
}) {
  const { t } = useLocale();
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const start = async () => {
    setBusy(true);
    setRefused(null);
    try {
      onChange(await client.startNarration(projectId, documentId));
    } catch (error) {
      setRefused(error instanceof StudioImportRequestError ? (error.code ?? "narration_unavailable") : "narration_unavailable");
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        className="rounded-md bg-copper px-3 py-1.5 text-[13px] font-medium text-bg disabled:cursor-not-allowed disabled:opacity-40"
        disabled={busy || isNarrationActive(state)}
        onClick={start}
      >
        {t("studio.narration.create")}
      </button>
      {refused ? (
        <span role="status" className="text-xs text-danger">
          {t("studio.narration.refused", { code: refused })}
        </span>
      ) : null}
    </span>
  );
}
