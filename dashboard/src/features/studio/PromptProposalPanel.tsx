import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { isPromptStageId, type ControlPlaneClient } from "@/api/control-plane";
import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";
import {
  canApplyProposal,
  canGenerateProposal,
  createPromptProposalState,
  promptProposalReducer,
  type GenerateBlockReason,
} from "./prompt_proposal_state";

export type PromptProposalPanelClient = Pick<
  ControlPlaneClient,
  | "listPromptProviders"
  | "getPromptStarter"
  | "getPromptPreference"
  | "savePromptPreference"
  | "getPromptLocks"
  | "savePromptLock"
  | "createPromptProposal"
  | "listPromptProposals"
  | "getPromptProposal"
  | "applyPromptProposal"
  | "rejectPromptProposal"
  | "getPromptBinding"
>;

type Props = {
  client: PromptProposalPanelClient;
  projectId: string;
  stageId: string;
  savedTemplateId: string | null;
  savedTemplateRevision: number | null;
  savedBindingRevision: number | null;
  savedOverrideText: string;
  formDirty: boolean;
  online: boolean;
  hasBinding: boolean;
  onApplied: () => void;
  onUseStarter: (body: string, language: string) => void;
  onCreateScratch: () => void;
};

const toolbarButton =
  "rounded-md bg-raised px-3 py-1.5 text-sm text-ink transition-colors hover:bg-well focus-visible:outline-2 focus-visible:outline-copper disabled:cursor-not-allowed disabled:opacity-40 aria-[pressed=true]:bg-copper aria-[pressed=true]:text-primary-foreground";

const POLL_INTERVAL_MS = 1_500;

// Shared copy for a blocked generate gate's reason, computed once per button from
// that button's own gate result so the visible text can never diverge from the
// check that actually decided its disabled state.
function generateReasonKey(reason: GenerateBlockReason | undefined): MessageKey | null {
  switch (reason) {
    case "unsaved_changes":
    case "missing_saved_source":
      return "studio.prompt.reason.save";
    case "offline":
      return "studio.prompt.reason.offline";
    case "layer_locked":
      return "studio.prompt.reason.locked";
    case "proposal_in_flight":
      return "studio.prompt.reason.inFlight";
    case "no_provider":
    case "model_not_allowed":
      return "studio.prompt.reason.provider";
    case "resources_unavailable":
      return "studio.prompt.reason.reload";
    default:
      return null;
  }
}

function panelErrorKey(code: string): MessageKey {
  switch (code) {
    case "store_unavailable":
    case "unknown_stage_id":
    case "lock_conflict":
    case "preference_conflict":
      return `studio.prompt.error.${code}`;
    default:
      return "studio.prompt.error.unknown";
  }
}

export function PromptProposalPanel(props: Props) {
  const { t } = useLocale();
  const generateReasonText = (reason: GenerateBlockReason | undefined) => {
    const key = generateReasonKey(reason);
    return key ? t(key) : null;
  };
  const { client, projectId, stageId, formDirty, online, onApplied, onUseStarter, onCreateScratch } =
    props;
  const [instructions, setInstructions] = useState("");
  const [targetLanguage, setTargetLanguage] = useState("en-US");
  const [improveLayer, setImproveLayer] = useState<"template" | "project_override">("template");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [pendingLocks, setPendingLocks] = useState<Set<"template" | "project_override">>(
    new Set(),
  );
  const [state, dispatch] = useReducer(
    promptProposalReducer,
    undefined,
    () =>
      createPromptProposalState({
        stageId,
        savedTemplateId: props.savedTemplateId,
        savedTemplateRevision: props.savedTemplateRevision,
        savedBindingRevision: props.savedBindingRevision,
        savedOverrideText: props.savedOverrideText,
      }),
  );
  useEffect(() => {
    dispatch({
      type: "saved_revisions_changed",
      templateId: props.savedTemplateId,
      templateRevision: props.savedTemplateRevision,
      bindingRevision: props.savedBindingRevision,
      overrideText: props.savedOverrideText,
    });
  }, [
    props.savedTemplateId,
    props.savedTemplateRevision,
    props.savedBindingRevision,
    props.savedOverrideText,
  ]);

  // One monotonically increasing generation counter shared by every stage-owned async
  // operation: loads AND mutation callbacks (preference save, lock save, generate,
  // apply, reject). Anything that settles after the stage has moved on to a newer
  // generation is discarded instead of dispatched, so a stale response from an older
  // project/stage/reconnect attempt can never mutate the current stage's state.
  const generationRef = useRef(0);

  // Bumping the generation on unmount reuses every generationRef check already
  // guarding generate/apply/reject/preference-save `.then()`/`.catch()` callbacks
  // above, so a response that settles after this panel is gone is discarded the
  // same way a stale stage's response is: no extra per-callback plumbing needed.
  useEffect(() => {
    return () => {
      generationRef.current += 1;
    };
  }, []);

  // A stage switch invalidates any lock request still in flight for the old stage
  // (its .finally() below can no longer own this layer's pending flag), so the new
  // stage's buttons must not stay stuck showing "pending" for a request that will
  // never touch them.
  useEffect(() => {
    setPendingLocks(new Set());
  }, [stageId]);

  // Loads one stage's owned resources strictly in order (catalog, then preference,
  // then locks, then history/active proposal) so a slower earlier call can never
  // land after a later one and clobber it. Used for both a stage switch and a
  // reconnect, always starting from a clean slate via stage_selected. A rejection
  // from any required call aborts the sequence fail-closed: no active proposal is
  // installed and polling never starts on incomplete state.
  const loadStage = useCallback(
    async (sid: string, generation: number) => {
      dispatch({ type: "stage_selected", stageId: sid });
      try {
        const providers = await client.listPromptProviders();
        if (generationRef.current !== generation) return;
        const preference = await client.getPromptPreference(projectId, sid);
        if (generationRef.current !== generation) return;
        const locks = await client.getPromptLocks(projectId, sid);
        if (generationRef.current !== generation) return;
        const page = await client.listPromptProposals(projectId, sid, undefined, 5);
        if (generationRef.current !== generation) return;
        const proposals = page?.proposals ?? [];
        const activeProposal =
          proposals.find((proposal) => proposal.status === "queued" || proposal.status === "running") ??
          proposals[0] ??
          null;
        dispatch({
          type: "stage_load_succeeded",
          providers,
          preference,
          locks,
          history: proposals,
          activeProposal,
        });
      } catch {
        if (generationRef.current === generation) dispatch({ type: "stage_load_failed" });
      }
    },
    [client, projectId],
  );

  useEffect(() => {
    const generation = ++generationRef.current;
    void loadStage(stageId, generation);
  }, [loadStage, stageId]);

  // Manual recovery from a failed load (no automatic retry loop, no new
  // dependency): bumps the generation so a stale in-flight attempt from before
  // the click can never land after this one.
  const retryLoad = () => {
    const generation = ++generationRef.current;
    void loadStage(stageId, generation);
  };

  const wasOnlineRef = useRef(online);
  const stageIdRef = useRef(stageId);
  stageIdRef.current = stageId;
  useEffect(() => {
    const wasOnline = wasOnlineRef.current;
    wasOnlineRef.current = online;
    if (wasOnline || !online) return;
    const generation = ++generationRef.current;
    void loadStage(stageIdRef.current, generation);
  }, [online, loadStage]);

  // Recursive, cancelled setTimeout: the next poll is scheduled only inside the
  // previous GET's .then()/.catch(), so a rejected poll reschedules a single bounded
  // retry instead of dying silently or hot-looping. Stops on a terminal status; the
  // effect itself only restarts on a genuinely new proposal, connectivity change, or
  // stage generation change (not on every dispatched proposal_loaded).
  useEffect(() => {
    if (!online) return;
    if (!state.activeProposal) return;
    if (state.activeProposal.status !== "queued" && state.activeProposal.status !== "running") {
      return;
    }
    const proposalId = state.activeProposal.proposal_id;
    const generation = generationRef.current;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;

    const poll = () => {
      timer = setTimeout(() => {
        void client
          .getPromptProposal(projectId, proposalId)
          .then((proposal) => {
            if (!active || generationRef.current !== generation) return;
            dispatch({ type: "proposal_loaded", proposal });
            if (proposal.status === "queued" || proposal.status === "running") poll();
          })
          .catch(() => {
            if (!active || generationRef.current !== generation) return;
            poll();
          });
      }, POLL_INTERVAL_MS);
    };
    poll();

    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [client, projectId, state.activeProposal?.proposal_id, online]);

  // `gate` is always the exact same canGenerateProposal(...) result already used to
  // compute the calling button's `disabled` attribute, so the click can never fire
  // on a check the UI didn't actually show. `layerOverride` lets Regenerate target
  // the proposal's own recorded layer instead of whatever the Improve dropdown
  // currently shows.
  const generate = (
    kind: "improve" | "translate",
    gate: { allowed: boolean },
    layerOverride?: "template" | "project_override",
  ) => {
    if (!gate.allowed) return;
    if (!isPromptStageId(stageId)) {
      dispatch({ type: "error", code: "unknown_stage_id" });
      return;
    }
    if (
      props.savedTemplateId === null ||
      props.savedTemplateRevision === null ||
      props.savedBindingRevision === null
    ) {
      return;
    }
    const idempotencyKey = `poll_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    const sourceIdentity = {
      source_template_id: props.savedTemplateId,
      source_template_revision: props.savedTemplateRevision,
      source_binding_revision: props.savedBindingRevision,
    };
    const layer = layerOverride ?? (kind === "improve" ? improveLayer : "template");
    const generation = generationRef.current;
    void client
      .createPromptProposal(
        projectId,
        idempotencyKey,
        kind === "improve"
          ? {
              kind,
              stage_id: stageId,
              provider_id: state.selectedProviderId ?? "",
              model_id: state.selectedModelId ?? "",
              target_layer: layer,
              improvement_instructions: instructions.trim() ? instructions : null,
              ...sourceIdentity,
            }
          : {
              kind,
              stage_id: stageId,
              provider_id: state.selectedProviderId ?? "",
              model_id: state.selectedModelId ?? "",
              target_language: targetLanguage,
              ...sourceIdentity,
            },
      )
      .then((proposal) => {
        if (generationRef.current !== generation) return;
        dispatch({ type: "proposal_loaded", proposal });
      })
      .catch(() => {
        if (generationRef.current !== generation) return;
        dispatch({ type: "error", code: "store_unavailable" });
      });
  };

  const apply = () => {
    const proposal = state.activeProposal;
    if (!proposal || proposal.status !== "succeeded") return;
    const generation = generationRef.current;
    void client
      .applyPromptProposal(projectId, proposal.proposal_id, {
        source_template_revision: proposal.source.template_revision,
        source_binding_revision: proposal.source.binding_revision,
        change_ids:
          proposal.kind === "improve"
            ? state.selectedChangeIds
            : [],
      })
      .then(() => {
        if (generationRef.current !== generation) return;
        dispatch({ type: "proposal_status_changed", status: "applied" });
        onApplied();
      })
      .catch(() => {
        if (generationRef.current !== generation) return;
        dispatch({ type: "error", code: "store_unavailable" });
      });
  };

  const reject = () => {
    const proposal = state.activeProposal;
    if (!proposal) return;
    const generation = generationRef.current;
    void client
      .rejectPromptProposal(projectId, proposal.proposal_id)
      .then((updated) => {
        if (generationRef.current !== generation) return;
        dispatch({ type: "proposal_status_changed", status: updated.status });
      })
      .catch(() => {
        if (generationRef.current !== generation) return;
        dispatch({ type: "error", code: "store_unavailable" });
      });
  };

  const improveGate = canGenerateProposal(state, { online, formDirty }, "improve", improveLayer);
  const translateGate = canGenerateProposal(state, { online, formDirty }, "translate", "template");
  const identityMissing =
    props.savedTemplateId === null ||
    props.savedTemplateRevision === null ||
    props.savedBindingRevision === null;
  const proposal = state.activeProposal;
  const regenerateGate = proposal
    ? canGenerateProposal(state, { online, formDirty }, proposal.kind, proposal.target_layers[0])
    : { allowed: false as const, reason: undefined };
  const applyCheck =
    proposal && props.savedTemplateRevision !== null && props.savedBindingRevision !== null
      ? canApplyProposal(state, {
          online,
          templateRevision: props.savedTemplateRevision,
          bindingRevision: props.savedBindingRevision,
        })
      : { allowed: false as const, reason: "not_succeeded" as const };
  const provider = state.providers.find((item) => item.provider_id === state.selectedProviderId);
  const lockedTemplate = state.locks.some((lock) => lock.layer === "template" && lock.locked);
  const lockedOverride = state.locks.some(
    (lock) => lock.layer === "project_override" && lock.locked,
  );

  const useStarter = () => {
    const generation = generationRef.current;
    void client
      .getPromptStarter(stageId)
      .then((starter) => {
        if (generationRef.current !== generation) return;
        onUseStarter(starter.body, starter.language);
      })
      .catch(() => undefined);
  };

  const toggleLock = (layer: "template" | "project_override", currentlyLocked: boolean) => {
    const baseRevision = state.locks.find((lock) => lock.layer === layer)?.revision ?? null;
    const generation = generationRef.current;
    setPendingLocks((prev) => new Set(prev).add(layer));
    void client
      .savePromptLock(projectId, stageId, layer, {
        locked: !currentlyLocked,
        base_revision: baseRevision,
      })
      .then((result) => {
        if (generationRef.current !== generation) return;
        dispatch(
          result.kind === "conflict"
            ? { type: "lock_conflict", latest: result.latest }
            : { type: "lock_saved", lock: result.value },
        );
      })
      .catch(() => {
        if (generationRef.current !== generation) return;
        dispatch({ type: "error", code: "store_unavailable" });
      })
      .finally(() => {
        if (generationRef.current !== generation) return;
        setPendingLocks((prev) => {
          const next = new Set(prev);
          next.delete(layer);
          return next;
        });
      });
  };

  return (
    <section aria-label={t("studio.prompt.ai.title")} className="flex flex-col gap-3 border-t border-hairline pt-3">
      <h3 className="text-sm font-semibold">{t("studio.prompt.ai.title")}</h3>

      {!state.resourcesReady && state.lastError === "stage_load_failed" && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 border-b border-destructive/50 bg-destructive/10 px-3 py-2 text-sm"
        >
          <p>{t("studio.prompt.ai.loadFailed")}</p>
          <button type="button" className={toolbarButton} onClick={retryLoad} disabled={!online}>
            {t("studio.prompt.ai.retryLoad")}
          </button>
        </div>
      )}

      {state.lastError && (state.resourcesReady || state.lastError !== "stage_load_failed") && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 border-b border-destructive/50 bg-destructive/10 px-3 py-2 text-sm"
        >
          <p>{t(panelErrorKey(state.lastError))}</p>
        </div>
      )}

      {!props.hasBinding && (
        <div className="flex flex-wrap gap-2">
          <button type="button" className={toolbarButton} onClick={useStarter}>
            {t("studio.prompt.ai.useStarter")}
          </button>
          <button type="button" className={toolbarButton} onClick={onCreateScratch}>
            {t("studio.prompt.ai.scratch")}
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label htmlFor="pp-provider">{t("studio.prompt.ai.provider")}</label>
        <select
          id="pp-provider"
          className="rounded-md border border-border bg-background px-2 py-1"
          value={state.selectedProviderId ?? ""}
          onChange={(event) => {
            const nextProvider = state.providers.find(
              (item) => item.provider_id === event.target.value,
            );
            dispatch({
              type: "select_provider",
              providerId: event.target.value,
              modelId: nextProvider?.models[0]?.model_id ?? "",
            });
          }}
        >
          {state.providers.map((item) => (
            <option key={item.provider_id} value={item.provider_id}>
              {item.label}
            </option>
          ))}
        </select>
        <label htmlFor="pp-model">{t("studio.prompt.ai.model")}</label>
        <select
          id="pp-model"
          className="rounded-md border border-border bg-background px-2 py-1"
          value={state.selectedModelId ?? ""}
          onChange={(event) =>
            state.selectedProviderId &&
            dispatch({
              type: "select_provider",
              providerId: state.selectedProviderId,
              modelId: event.target.value,
            })
          }
        >
          {(provider?.models ?? []).map((model) => (
            <option key={model.model_id} value={model.model_id}>
              {model.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={toolbarButton}
          disabled={!online || !state.resourcesReady}
          onClick={() => {
            if (state.selectedProviderId && state.selectedModelId) {
              const generation = generationRef.current;
              void client
                .savePromptPreference(projectId, stageId, {
                  provider_id: state.selectedProviderId,
                  model_id: state.selectedModelId,
                  base_revision: state.preference?.revision ?? null,
                })
                .then((result) => {
                  if (generationRef.current !== generation) return;
                  dispatch(
                    result.kind === "conflict"
                      ? { type: "preference_conflict", latest: result.latest }
                      : { type: "preference_saved", preference: result.value },
                  );
                })
                .catch(() => {
                  if (generationRef.current !== generation) return;
                  dispatch({ type: "error", code: "store_unavailable" });
                });
            }
          }}
        >
          {t("studio.prompt.ai.savePreference")}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <button
          type="button"
          className={toolbarButton}
          disabled={
            !online || !state.resourcesReady || pendingLocks.has("template")
          }
          onClick={() => toggleLock("template", lockedTemplate)}
        >
          {t(lockedTemplate ? "studio.prompt.ai.unlockTemplate" : "studio.prompt.ai.lockTemplate")}
        </button>
        <button
          type="button"
          className={toolbarButton}
          disabled={
            !online ||
            !state.resourcesReady ||
            pendingLocks.has("project_override")
          }
          onClick={() => toggleLock("project_override", lockedOverride)}
        >
          {t(lockedOverride ? "studio.prompt.ai.unlockOverride" : "studio.prompt.ai.lockOverride")}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label htmlFor="pp-improve-layer">{t("studio.prompt.ai.target")}</label>
        <select
          id="pp-improve-layer"
          className="rounded-md border border-border bg-background px-2 py-1"
          value={improveLayer}
          onChange={(event) =>
            setImproveLayer(event.target.value as "template" | "project_override")
          }
        >
          <option value="template">{t("studio.prompt.ai.targetTemplate")}</option>
          <option value="project_override">{t("studio.prompt.ai.targetOverride")}</option>
        </select>
        <label htmlFor="pp-instructions">{t("studio.prompt.ai.instructions")}</label>
        <input
          id="pp-instructions"
          className="min-w-48 rounded-md border border-border bg-background px-2 py-1"
          maxLength={2000}
          value={instructions}
          onChange={(event) => setInstructions(event.target.value)}
        />
        <label htmlFor="pp-language">{t("studio.prompt.ai.language")}</label>
        <input
          id="pp-language"
          className="w-24 rounded-md border border-border bg-background px-2 py-1"
          value={targetLanguage}
          onChange={(event) => setTargetLanguage(event.target.value)}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <button
          type="button"
          className={toolbarButton}
          disabled={!improveGate.allowed || identityMissing}
          onClick={() => generate("improve", improveGate)}
        >
          {t("studio.prompt.ai.improve")}
        </button>
        <button
          type="button"
          className={toolbarButton}
          disabled={!translateGate.allowed || identityMissing}
          onClick={() => generate("translate", translateGate)}
        >
          {t("studio.prompt.ai.translate")}
        </button>
        {!improveGate.allowed && generateReasonText(improveGate.reason) && (
          <p className="text-xs text-muted-foreground">
            {generateReasonText(improveGate.reason)}
          </p>
        )}
        {!translateGate.allowed && generateReasonText(translateGate.reason) && (
          <p className="text-xs text-muted-foreground">
            {generateReasonText(translateGate.reason)}
          </p>
        )}
      </div>

      {proposal && (
        <div className="flex flex-col gap-2 text-sm" aria-label={t("studio.prompt.ai.review")}>
          <div role="status" aria-atomic="true">
            {proposal.status === "queued" || proposal.status === "running"
              ? t("studio.prompt.ai.running")
              : proposal.status === "succeeded"
                ? t("studio.prompt.ai.ready")
                : proposal.status === "failed"
                  ? t("studio.prompt.ai.failed", { code: proposal.failure_code ?? t("studio.prompt.ai.unknown") })
                  : t("studio.prompt.ai.status", { status: proposal.status })}
          </div>
          {proposal.kind === "translate" && (
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <p className="font-semibold">{t("studio.prompt.ai.sourceTemplate")}</p>
                <pre className="whitespace-pre-wrap rounded-md border border-border bg-card p-2">
                  {proposal.source.template_body}
                </pre>
              </div>
              <div>
                <p className="font-semibold">{t("studio.prompt.ai.proposedTemplate")}</p>
                <pre className="whitespace-pre-wrap rounded-md border border-border bg-card p-2">
                  {proposal.translated_template_body ?? ""}
                </pre>
              </div>
              {proposal.source.project_override !== null && (
                <>
                  <div>
                    <p className="font-semibold">{t("studio.prompt.ai.sourceOverride")}</p>
                    <pre className="whitespace-pre-wrap rounded-md border border-border bg-card p-2">
                      {proposal.source.project_override}
                    </pre>
                  </div>
                  <div>
                    <p className="font-semibold">{t("studio.prompt.ai.proposedOverride")}</p>
                    <pre className="whitespace-pre-wrap rounded-md border border-border bg-card p-2">
                      {proposal.translated_project_override ?? ""}
                    </pre>
                  </div>
                </>
              )}
            </div>
          )}
          {proposal.kind === "improve" &&
            proposal.changes.map((change) => (
              <label key={change.change_id} className="flex items-start gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={state.selectedChangeIds.includes(change.change_id)}
                  onChange={() =>
                    dispatch({ type: "toggle_change", changeId: change.change_id })
                  }
                />
                <span>
                  {change.before_text} → {change.after_text}
                </span>
              </label>
            ))}
          <div className="flex flex-wrap gap-2">
            {proposal.kind === "improve" && (
              <button
                type="button"
                className={toolbarButton}
                disabled={!applyCheck.allowed}
                onClick={apply}
              >
                {t("studio.prompt.ai.applySelected")}
              </button>
            )}
            {proposal.kind === "translate" && (
              <button
                type="button"
                className={toolbarButton}
                disabled={!applyCheck.allowed}
                onClick={apply}
              >
                {t("studio.prompt.ai.applyTranslation")}
              </button>
            )}
            <button
              type="button"
              className={toolbarButton}
              disabled={!online || proposal.status !== "succeeded"}
              onClick={reject}
            >
              {t("studio.prompt.ai.reject")}
            </button>
            <button
              type="button"
              className={toolbarButton}
              disabled={!regenerateGate.allowed || props.savedTemplateId === null}
              onClick={() => generate(proposal.kind, regenerateGate, proposal.target_layers[0])}
            >
              {t("studio.prompt.ai.regenerate")}
            </button>
          </div>
          {!applyCheck.allowed && applyCheck.reason === "source_changed" && (
            <p className="text-xs text-status-failed">{t("studio.prompt.ai.sourceChanged")}</p>
          )}
          {!regenerateGate.allowed && generateReasonText(regenerateGate.reason) && (
            <p className="text-xs text-muted-foreground">
              {generateReasonText(regenerateGate.reason)}
            </p>
          )}
          {props.hasBinding === false && formDirty && <p className="sr-only">draft</p>}
        </div>
      )}

      {formDirty && !proposal && (
        <p className="text-xs text-muted-ink">{t("studio.prompt.reason.save")}</p>
      )}

      <details
        open={historyOpen}
        onToggle={(event) => setHistoryOpen((event.target as HTMLDetailsElement).open)}
      >
        <summary className="cursor-pointer text-sm font-semibold">{t("studio.prompt.ai.history")}</summary>
        <ul className="mt-1 flex flex-col gap-1 text-xs">
          {state.history.map((item) => (
            <li key={item.proposal_id}>
              <button
                type="button"
                className={toolbarButton}
                onClick={() => dispatch({ type: "proposal_loaded", proposal: item })}
              >
                {`${item.kind} · ${item.status} · ${item.created_at}`}
              </button>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
