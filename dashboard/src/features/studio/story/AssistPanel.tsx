import { useState, type Dispatch } from "react";
import { Sparkles } from "lucide-react";

import {
  StudioImportRequestError,
  type EditDocumentV2,
  type StoryAssistProposal,
  type StoryAssistRequest,
} from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

import type { EditorAction } from "../editor_state";
import type { Beat } from "./story_beats";

type Props = {
  request: (body: StoryAssistRequest) => Promise<StoryAssistProposal>;
  baseRevision: number;
  beat: Beat;
  document: EditDocumentV2;
  /** The server reads the saved revision, so Assist waits until the draft is saved. */
  ready: boolean;
  dispatch: Dispatch<EditorAction>;
};

/** The route takes at most this many clip ids (StoryAssistRequest.clip_ids). */
const MAX_CLIPS = 20;

type Failure = "notConfigured" | "invalid" | "noText" | "conflict" | "unavailable";
const FAILURE_OF: Record<string, Failure> = {
  assist_not_configured: "notConfigured",
  assist_invalid_output: "invalid",
  assist_no_text: "noText",
  document_revision_conflict: "conflict",
};

/** Spec 2026-10-27 §7: one text proposal for the chosen beat; Apply or Dismiss. Never stored. */
export function AssistPanel({ request, baseRevision, beat, document, ready, dispatch }: Props) {
  const { t } = useLocale();
  const [thinking, setThinking] = useState(false);
  const [proposal, setProposal] = useState<StoryAssistProposal | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const beatName = t(`studio.story.beat.${beat.id}`);

  // Assist rewrites text; only the beat's text and caption clips are worth sending.
  const textIds = beat.clipIds
    .filter((id) => {
      const kind = (document.clips ?? []).find((clip) => clip.clip_id === id)?.kind;
      return kind === "text" || kind === "caption";
    })
    .slice(0, MAX_CLIPS);

  const suggest = async () => {
    setFailure(null);
    setProposal(null);
    if (!textIds.length) {
      setFailure("noText");
      return;
    }
    setThinking(true);
    try {
      setProposal(await request({ base_revision: baseRevision, beat: beat.id, clip_ids: textIds }));
    } catch (error) {
      const code = error instanceof StudioImportRequestError ? error.code : null;
      setFailure((code && FAILURE_OF[code]) || "unavailable");
    } finally {
      setThinking(false);
    }
  };
  const text = proposal?.operations
    .map((operation) => ("value" in operation ? operation.value : "text" in operation ? operation.text : ""))
    .join(" ");

  return (
    <section aria-label={t("studio.assist.title")} className="flex flex-col gap-3 border-t border-studio-ai/40 p-4">
      <h2 className="flex items-center gap-1.5 text-[15px] font-semibold text-studio-ai">
        <Sparkles aria-hidden="true" size={15} /> {t("studio.assist.title")}
      </h2>
      <p className="text-xs text-muted-ink">{t("studio.assist.intro")}</p>
      {proposal ? (
        <div className="flex flex-col gap-2 rounded-md border border-studio-ai/50 bg-studio-ai/10 p-3 text-sm text-ink">
          <p className="font-medium">{proposal.title}</p>
          <p className="text-xs text-muted-ink">{proposal.reason}</p>
          <p className="text-xs text-faint">{t("studio.assist.proposed")}</p>
          <p className="rounded bg-well px-2 py-1.5">{text}</p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                dispatch({ type: "commit_operations", operations: proposal.operations });
                setProposal(null);
              }}
              className="rounded-md bg-studio-ai px-3 py-1.5 text-[13px] font-medium text-bg focus-visible:outline-2 focus-visible:outline-copper"
            >
              {t("studio.assist.apply")}
            </button>
            <button
              type="button"
              onClick={() => setProposal(null)}
              className="rounded-md border border-hairline px-3 py-1.5 text-[13px] text-muted-ink hover:text-ink focus-visible:outline-2 focus-visible:outline-copper"
            >
              {t("studio.assist.dismiss")}
            </button>
          </div>
        </div>
      ) : thinking ? (
        <p role="status" className="flex items-center gap-2 text-sm text-studio-ai">
          <span aria-hidden="true" className="size-2 animate-pulse rounded-full bg-studio-ai" />
          {t("studio.assist.thinking")}
        </p>
      ) : (
        <>
          <button
            type="button"
            disabled={!ready}
            onClick={() => void suggest()}
            className="self-start rounded-md border border-studio-ai/60 px-3 py-1.5 text-[13px] text-studio-ai hover:bg-studio-ai/10 focus-visible:outline-2 focus-visible:outline-copper disabled:opacity-40"
          >
            {t("studio.assist.suggest", { beat: beatName })}
          </button>
          {ready ? null : <p className="text-xs text-muted-ink">{t("studio.assist.waitSave")}</p>}
        </>
      )}
      {failure ? (
        <p role="alert" className="text-xs text-status-failed">
          {failure === "notConfigured" ? (
            <>
              {t("studio.assist.notConfigured")}{" "}
              <a href="/studio/presets" className="text-copper underline">
                {t("studio.assist.presets")}
              </a>
            </>
          ) : (
            t(`studio.assist.${failure}`)
          )}
        </p>
      ) : null}
    </section>
  );
}
