// "Create narration" (spec 2026-10-31): the only way a draft's narration starts.
import { useState } from "react";

import { StudioImportRequestError, type ControlPlaneClient, type NarrationState } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

import { isNarrationActive } from "./useNarration";

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
        // Spec 5: for a draft with no narration yet; a finished one re-voices its lines.
        disabled={busy || isNarrationActive(state) || state?.status === "completed"}
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
