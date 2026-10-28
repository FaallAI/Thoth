import { useCallback, useEffect, useId, useReducer, useRef, useState, type ReactNode } from "react";
import { CircleAlert, CircleCheck, Film, Info, X } from "lucide-react";

import {
  StudioImportRequestError,
  type ControlPlaneClient,
  type CreateRenderJobPayload,
  type RenderJob,
  type RenderJobStatus,
  type StudioImportInventory,
} from "@/api/control-plane";
import { StageStepper } from "@/components/RunProgress";
import { Button } from "@/components/ui/button";
import { formatDay, formatDuration, type MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";

import {
  canCancel,
  canCleanup,
  canDownload,
  canRetry,
  createRenderJobState,
  renderGate,
  renderJobReducer,
  selectedRenderJob,
  type ImportBlock,
  type RenderEditorFacts,
} from "./render_job_state";

/** Only the render half of the control plane: the panel can reach nothing else. */
export type RenderPanelClient = Pick<
  ControlPlaneClient,
  | "getRenderCapability"
  | "createRenderJob"
  | "listRenderJobs"
  | "getRenderJob"
  | "cancelRenderJob"
  | "retryRenderJob"
  | "downloadRenderOutput"
  | "cleanupRenderArtifacts"
> &
  // A draft opened from a source also answers whether every source item is decided.
  Partial<Pick<ControlPlaneClient, "getStudioImportInventory">>;


/**
 * What the editor knows about whether the saved version can be rendered: the
 * text rules and the structural timeline rules, each reported by the domain
 * validator that owns it. The panel derives validity, so a caller cannot claim
 * a document is renderable and blocked at the same time.
 */
export type RenderValidation = {
  textValid: boolean;
  blockingIssues: number;
};

type Props = {
  client: RenderPanelClient;
  projectId: string;
  /** The saved document and the exact revision a render would name. */
  documentId: string;
  documentRevision: number;
  documentTitle?: string;
  canvas?: { width: number; height: number; fps: number; duration_in_frames: number };
  templateId: RenderJob["template_id"];
  templateVersion: RenderJob["template_version"];
  facts: Omit<RenderEditorFacts, "documentValid" | "importBlock">;
  validation: RenderValidation;
  /** Scene ids of the saved revision in play order, to name a blocked item's scene. */
  sceneOrder?: readonly string[];
  /** Reopen the draft's source inventory to attach or exclude what blocks rendering. */
  onResolveImports?: () => void;
  /** Phone surface: status, history, and download only; every render mutation stays hidden. */
  monitorOnly?: boolean;
};

const POLL_INTERVAL_MS = 1_500;

/** The statuses the lifecycle can still move on, mirroring the state module. */
const RUNNING_STATUSES: ReadonlySet<RenderJobStatus> = new Set([
  "preparing",
  "rendering",
  "finalizing",
]);

/**
 * Read the fixed code off a rejection and nothing else: the reducer narrows
 * whatever this returns, so an arbitrary throw becomes the generic code.
 */
function codeOf(error: unknown): unknown {
  return (error as { code?: unknown } | null)?.code;
}

/** What a create or retry needs to be replayed under its original key. */
type RenderAttempt =
  | { kind: "create"; request: CreateRenderJobPayload }
  | { kind: "retry"; renderJobId: string };

/** The facts a render is confirmed against, frozen when the dialog opens. */
type RenderConfirmation = {
  projectId: string;
  documentId: string;
  documentRevision: number;
  templateId: string;
  templateVersion: number;
  presetId: string;
};

const FAILURES = new Set<string>([
  "render_asset_unavailable",
  "render_bundle_invalid",
  "render_deadline_exceeded",
  "render_dispatch_failed",
  "render_engine_failed",
  "render_output_invalid",
  "render_storage_failed",
  "renderer_unavailable",
]);

/** How a render ended, from its fixed code only; an unknown code reads as the generic line. */
const failureKey = (job: RenderJob): MessageKey =>
  job.failure_code && FAILURES.has(job.failure_code)
    ? (`studio.render.failure.${job.failure_code}` as MessageKey)
    : "studio.render.failure.generic";

/**
 * The render context is one identity, not five props: a different project,
 * document, revision, or template is a different render surface. Keying the
 * panel on it replaces the whole surface, so no confirmation, selection,
 * attempt, timer, or listener can outlive the context that owns it.
 */
export function RenderPanel(props: Props) {
  const { projectId, documentId, documentRevision, templateId, templateVersion } = props;
  return (
    <RenderSurface
      key={`${projectId}|${documentId}|${documentRevision}|${templateId}|${templateVersion}`}
      {...props}
    />
  );
}

function RenderSurface({
  client,
  projectId,
  documentId,
  documentRevision,
  documentTitle,
  templateId,
  templateVersion,
  facts,
  validation,
  sceneOrder = [],
  onResolveImports,
  monitorOnly = false,
}: Props) {
  const { t, plural, locale } = useLocale();
  const [state, dispatch] = useReducer(renderJobReducer, undefined, createRenderJobState);
  // undefined while loading; null when the draft was not opened from a source.
  const [imports, setImports] = useState<StudioImportInventory | null | "failed">();
  const [confirmCreate, setConfirmCreate] = useState<RenderConfirmation | null>(null);
  const [confirmCleanup, setConfirmCleanup] = useState<string | null>(null);
  const gateReasonId = useId();
  const confirmTitleId = useId();

  // Kept in lockstep with the reducer's own counter: every dispatch that moves
  // the generation moves this too, so an asynchronous callback can tell whether
  // the document it was started for is still the one on screen.
  const generationRef = useRef(0);
  // Set before a request leaves, so two clicks in one tick cannot both fire.
  const inFlightRef = useRef(false);
  const attemptRef = useRef<RenderAttempt | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  // Read by handlers that must answer for themselves rather than trust a
  // rendered attribute, and by the settlement path, which runs between renders.
  const offlineRef = useRef(!facts.online);
  offlineRef.current = state.isOffline || !facts.online;
  // At most one recovery is owed at a time: a reconnect during a request waits
  // for that request to settle instead of starting a second one.
  const recoveryOwedRef = useRef(false);
  const aliveRef = useRef(true);
  const recoverRef = useRef<() => Promise<void>>(async () => {});

  const load = useCallback(async () => {
    dispatch({ type: "load_started" });
    const generation = ++generationRef.current;
    try {
      const [capability, page, inventory] = await Promise.all([
        client.getRenderCapability(projectId),
        client.listRenderJobs(projectId),
        // Re-read with every load, so a refusal or a reconnect shows today's decisions.
        client.getStudioImportInventory
          ? client.getStudioImportInventory(projectId, documentId).then(
              (result) => result,
              (error: unknown) =>
                error instanceof StudioImportRequestError && error.status === 404 ? null : ("failed" as const),
            )
          : null,
      ]);
      // A superseded load answers for a context that has already moved on, so
      // it reaches the surface through nothing at all - not the history, not
      // the error, and not the selection, which the reducer does not guard.
      if (generation !== generationRef.current) return;
      // A page without records is an empty history, not a broken panel.
      const jobs = page.jobs ?? [];
      setImports(inventory);
      dispatch({ type: "loaded", generation, capability, jobs });
      // A reload lands on a render already running: the control plane names it,
      // so the panel resumes that one instead of inventing a rule of its own,
      // and it outranks a terminal render the person happened to be reading.
      const activeId = capability.active_render_job_id;
      if (activeId && jobs.some((entry) => entry.render_job_id === activeId)) {
        dispatch({ type: "job_selected", renderJobId: activeId });
      }
    } catch (error) {
      if (generation !== generationRef.current) return;
      dispatch({ type: "load_failed", generation, code: codeOf(error) });
    }
  }, [client, projectId, documentId]);

  /**
   * Land the outcome of a mutation. Every outcome ends in authoritative state
   * while the panel is online; offline, exactly one refresh or replay is owed
   * to the reconnect instead, and an attempt still unaccounted for stays whole
   * so the replay can reuse its original key.
   */
  const land = useCallback(
    async (outcome: { ok: true; job?: RenderJob } | { ok: false; code: unknown }) => {
      if (!aliveRef.current) return;
      const owed = recoveryOwedRef.current;
      if (outcome.ok) {
        dispatch({
          type: "mutation_succeeded",
          generation: generationRef.current,
          job: outcome.job,
        });
      } else if (offlineRef.current || owed) {
        recoveryOwedRef.current = true;
        return;
      } else {
        // Re-read first: a reload clears the last error, so the reason a person
        // needs is dispatched afterwards, under the generation the reload left.
        await load();
        if (!aliveRef.current) return;
        dispatch({
          type: "mutation_failed",
          generation: generationRef.current,
          code: outcome.code,
        });
        return;
      }
      if (offlineRef.current || owed) {
        recoveryOwedRef.current = true;
        return;
      }
      await load();
    },
    [load],
  );

  /** Run a create or retry under a key the caller owns, then re-read the truth. */
  const runAttempt = useCallback(
    async (attempt: RenderAttempt, attemptKey: string) => {
      if (inFlightRef.current || offlineRef.current) return;
      inFlightRef.current = true;
      try {
        const job =
          attempt.kind === "create"
            ? await client.createRenderJob(projectId, attemptKey, attempt.request)
            : await client.retryRenderJob(projectId, attempt.renderJobId, attemptKey);
        await land({ ok: true, job });
      } catch (error) {
        await land({ ok: false, code: codeOf(error) });
      } finally {
        inFlightRef.current = false;
      }
      await recoverRef.current();
    },
    [client, projectId, land],
  );

  /** Run a mutation the server identifies by the job alone. */
  const runPlain = useCallback(
    async (mutation: "cancel" | "download" | "cleanup", work: () => Promise<RenderJob | void>) => {
      if (inFlightRef.current || stateRef.current.mutation !== null) return;
      // Offline is refused here, not only by a disabled attribute a synthetic
      // event can ignore: no request leaves this panel without a connection.
      if (offlineRef.current) return;
      inFlightRef.current = true;
      dispatch({ type: "mutation_started", mutation });
      try {
        const job = await work();
        await land({ ok: true, job: job ?? undefined });
      } catch (error) {
        await land({ ok: false, code: codeOf(error) });
      } finally {
        inFlightRef.current = false;
      }
      await recoverRef.current();
    },
    [land],
  );

  /**
   * Execute the one recovery that is owed, once nothing is in flight and the
   * connection is back: replay the attempt still unaccounted for under its own
   * key, or re-read authoritative state. The flag is cleared first, so a
   * recovery that fails becomes an ordinary failure rather than a retry loop.
   */
  const recover = useCallback(async () => {
    if (!aliveRef.current || !recoveryOwedRef.current) return;
    if (inFlightRef.current || offlineRef.current) return;
    recoveryOwedRef.current = false;
    const { mutation, attemptKey } = stateRef.current;
    const attempt = attemptRef.current;
    if (mutation !== null && attemptKey !== null && attempt !== null) {
      await runAttempt(attempt, attemptKey);
    } else {
      await load();
    }
  }, [load, runAttempt]);
  recoverRef.current = recover;

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const goOffline = () => {
      offlineRef.current = true;
      generationRef.current += 1;
      // Whatever was in flight settles into an unknown, so one recovery is owed.
      if (inFlightRef.current || stateRef.current.mutation !== null) {
        recoveryOwedRef.current = true;
      }
      dispatch({ type: "went_offline" });
    };
    const goOnline = () => {
      offlineRef.current = false;
      dispatch({ type: "went_online" });
      // A reconnect always owes one action; while a request is still outstanding
      // it waits for that request to settle instead of starting a second one.
      recoveryOwedRef.current = true;
      void recoverRef.current();
    };
    window.addEventListener("offline", goOffline);
    window.addEventListener("online", goOnline);
    return () => {
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", goOnline);
    };
  }, []);

  // Nothing here survives unmount: the last callbacks are answered by nobody.
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      generationRef.current += 1;
    };
  }, []);

  const selected = selectedRenderJob(state);
  const pollJobId = selected && RUNNING_STATUSES.has(selected.status) ? selected.render_job_id : null;
  const paused = state.isOffline || !facts.online;

  useEffect(() => {
    if (pollJobId === null || paused) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // The next poll is scheduled only once the current one has settled, so the
    // panel never has two status requests out or an unbounded timer chain.
    const tick = () => {
      const generation = generationRef.current;
      client
        .getRenderJob(projectId, pollJobId)
        .then((job) => {
          if (live) dispatch({ type: "job_refreshed", generation, job });
        })
        .catch(() => {})
        .finally(() => {
          if (live) timer = setTimeout(tick, POLL_INTERVAL_MS);
        });
    };
    timer = setTimeout(tick, POLL_INTERVAL_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [client, projectId, pollJobId, paused]);

  const blockingIssues = validation.blockingIssues;
  const unresolved =
    imports && imports !== "failed" ? imports.items.filter((item) => item.disposition === "unresolved") : [];
  // The server rechecks all of this when a render is created; this only explains it first.
  const importBlock: ImportBlock | undefined =
    imports === "failed"
      ? "import_unknown"
      : imports && imports.revision !== documentRevision
        ? "import_stale"
        : unresolved.length
          ? "import_unresolved"
          : undefined;
  const gate = renderGate(
    { ...facts, documentValid: validation.textValid && blockingIssues === 0, importBlock },
    state,
  );
  const itemName = (item: (typeof unresolved)[number]) => {
    const scene = item.scene_id ? sceneOrder.indexOf(item.scene_id) : -1;
    return scene < 0 ? item.label : t("studio.render.itemScene", { label: item.label, scene: scene + 1 });
  };
  // A structural problem is nameable, so the guidance says how many stand in
  // the way instead of repeating the generic invalid-document sentence.
  const gateText =
    gate.reason === "document_invalid" && blockingIssues > 0
      ? plural("studio.render.gate.issues", blockingIssues)
      : gate.reason
        ? t(`studio.render.gate.${gate.reason}`)
        : null;
  const offline = state.isOffline || !facts.online;

  const openConfirm = () => {
    if (!gate.allowed || state.capability === null) return;
    setConfirmCreate({
      projectId,
      documentId,
      documentRevision,
      templateId,
      templateVersion,
      presetId: state.capability.preset_id,
    });
  };

  const startCreate = () => {
    const confirmation = confirmCreate;
    setConfirmCreate(null);
    // The guard and the label read the same gate, so what is explained as
    // impossible is impossible.
    if (confirmation === null || !gate.allowed || inFlightRef.current) return;
    const attempt: RenderAttempt = {
      kind: "create",
      request: {
        document_id: confirmation.documentId,
        document_revision: confirmation.documentRevision,
      },
    };
    const attemptKey = crypto.randomUUID();
    attemptRef.current = attempt;
    dispatch({ type: "mutation_started", mutation: "create", attemptKey });
    void runAttempt(attempt, attemptKey);
  };

  const startRetry = (job: RenderJob) => {
    if (inFlightRef.current || state.mutation !== null) return;
    const attempt: RenderAttempt = { kind: "retry", renderJobId: job.render_job_id };
    const attemptKey = crypto.randomUUID();
    attemptRef.current = attempt;
    dispatch({ type: "mutation_started", mutation: "retry", attemptKey });
    void runAttempt(attempt, attemptKey);
  };

  const startCancel = (job: RenderJob) => {
    void runPlain("cancel", () => client.cancelRenderJob(projectId, job.render_job_id));
  };

  const startDownload = (job: RenderJob) => {
    void runPlain("download", async () => {
      const blob = await client.downloadRenderOutput(projectId, job.render_job_id);
      const url = URL.createObjectURL(blob);
      try {
        const anchor = window.document.createElement("a");
        anchor.href = url;
        // The name belongs to this panel: no server path is read or revealed.
        anchor.download = `render-${job.render_job_id}.mp4`;
        anchor.click();
      } finally {
        URL.revokeObjectURL(url);
      }
    });
  };

  const startCleanup = (renderJobId: string) => {
    // Offline or already busy, the request would never leave: the confirmation
    // stays up with its warning instead of closing on nothing.
    if (offlineRef.current || inFlightRef.current || stateRef.current.mutation !== null) return;
    setConfirmCleanup(null);
    void runPlain("cleanup", () => client.cleanupRenderArtifacts(projectId, renderJobId));
  };

  const running = selected !== null && RUNNING_STATUSES.has(selected.status);
  const now = useNow(1_000, running);
  const readinessId = useId();
  const outputsId = useId();
  const statusLabel = (status: RenderJobStatus) => t(`studio.render.status.${status}`);
  const tag = locale === "id" ? "id-ID" : "en-US";
  const size = (bytes: number) =>
    bytes >= 1_000_000
      ? new Intl.NumberFormat(tag, { style: "unit", unit: "megabyte", maximumFractionDigits: 1 }).format(bytes / 1_000_000)
      : new Intl.NumberFormat(tag, { style: "unit", unit: "kilobyte", maximumFractionDigits: 0 }).format(bytes / 1_000);
  const clock = (seconds: number) =>
    `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
  const outputMeta = (job: RenderJob) =>
    job.output
      ? t("studio.render.outputMeta", {
          width: job.output.width,
          height: job.output.height,
          size: size(job.output.size_bytes),
          duration: clock(job.output.duration_seconds),
        })
      : null;
  const when = (iso: string | null | undefined) => (iso && !Number.isNaN(Date.parse(iso)) ? formatDay(locale, iso) : "");
  // ponytail: average speed since the job started, so preparation time lowers it slightly; sample deltas if it misleads.
  const speed = (job: RenderJob) => {
    if (!job.started_at || !job.rendered_frames) return null;
    const seconds = (now.getTime() - Date.parse(job.started_at)) / 1_000;
    return seconds > 0 ? job.rendered_frames / seconds : null;
  };
  const fps = selected ? speed(selected) : null;
  const secondsLeft =
    selected && running && fps && selected.total_frames && selected.rendered_frames !== null && selected.rendered_frames !== undefined
      ? Math.max(0, (selected.total_frames - selected.rendered_frames) / fps)
      : null;
  // The renderer reports which stage it is in; a job that has not said yet is preparing.
  const STAGES = ["preparing", "rendering", "encoding", "uploading"] as const;
  const stageNames = {
    preparing: "studio.render.step.prepare",
    rendering: "studio.render.step.frames",
    encoding: "studio.render.step.encode",
    uploading: "studio.render.step.upload",
  } as const;
  const steps = (job: RenderJob) => {
    const at = STAGES.indexOf(job.render_stage ?? (job.status === "finalizing" ? "uploading" : job.status === "rendering" ? "rendering" : "preparing"));
    return STAGES.map((stage, index) => {
      const detail =
        stage === "rendering" && index <= at && job.rendered_frames != null && job.total_frames
          ? fps && index === at
            ? t("studio.render.step.framesLine", { done: job.rendered_frames, total: job.total_frames, fps: Math.round(fps) })
            : t("studio.render.step.framesCount", { done: job.rendered_frames, total: job.total_frames })
          : stage === "encoding" && index === at && job.encoded_frames != null && job.total_frames
            ? t("studio.render.step.framesCount", { done: job.encoded_frames, total: job.total_frames })
            : undefined;
      return {
        id: stage,
        label: t(stageNames[stage]),
        status: index < at ? ("completed" as const) : index === at ? ("running" as const) : ("queued" as const),
        started_at: index === at ? (job.started_at ?? null) : null,
        finished_at: null,
        detail,
      };
    });
  };
  const heading = (job: RenderJob) =>
    RUNNING_STATUSES.has(job.status)
      ? t("studio.render.heading.running", { revision: job.document_revision })
      : t(`studio.render.heading.${job.status as "completed" | "failed" | "cancelled"}`, { revision: job.document_revision });
  const card = "rounded-[10px] bg-surface p-6";
  const check = (ok: boolean, label: string, detail: string | null, extra?: ReactNode) => (
    <li className="flex gap-3 border-b border-hairline py-3 last:border-0">
      {ok ? (
        <CircleCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-status-done" />
      ) : (
        <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-status-failed" />
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-[15px] text-ink">{label}</p>
        {ok ? <p className="text-[13px] text-muted-ink">{t("studio.render.check.passed")}</p> : detail ? <p className="text-[13px] text-muted-ink">{detail}</p> : null}
        {extra}
      </div>
    </li>
  );

  return (
    <section
      className="studio-render-workspace grid min-w-0 grid-cols-[minmax(0,1fr)] gap-6 p-4 text-ink md:p-6 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]"
      aria-label={t("studio.render.title")}
    >
      <section aria-labelledby={readinessId} className={cn(card, "flex flex-col gap-4 self-start")}>
        <header>
          <h2 id={readinessId} className="text-lg font-semibold">
            {t("studio.render.readiness")}
          </h2>
          <p className="mt-1 text-sm text-muted-ink">{documentTitle ?? t("studio.render.readinessIntro", { revision: documentRevision })}</p>
        </header>
        <ul className="flex flex-col">
          {check(facts.saveStatus === "saved", t("studio.render.check.saved", { revision: documentRevision }), t("studio.render.check.savedNo"))}
          {check(
            !importBlock,
            t("studio.render.check.media"),
            null,
            importBlock ? (
              <div role="status" aria-label="Source import" className="mt-1 flex flex-col gap-2 text-sm">
                <p className="text-status-failed">
                  {importBlock === "import_unresolved"
                    ? plural("studio.render.resolveCount", unresolved.length)
                    : t(`studio.render.gate.${importBlock}`)}
                </p>
                {importBlock === "import_unresolved" ? (
                  <ul className="list-disc pl-5 text-[13px] text-muted-ink">
                    {unresolved.map((item) => (
                      <li key={item.item_id}>{itemName(item)}</li>
                    ))}
                  </ul>
                ) : null}
                <div>
                  {importBlock === "import_unknown" ? (
                    <Button variant="secondary" size="sm" disabled={offline} onClick={() => void load()}>
                      {t("studio.render.checkAgain")}
                    </Button>
                  ) : onResolveImports ? (
                    // Leaving remounts Studio from the server, so only a saved draft may go.
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={offline || facts.saveStatus !== "saved"}
                      onClick={onResolveImports}
                    >
                      {t(importBlock === "import_stale" ? "studio.render.reopen" : "studio.render.resolve")}
                    </Button>
                  ) : null}
                </div>
              </div>
            ) : undefined,
          )}
          {check(
            validation.textValid && blockingIssues === 0,
            t("studio.render.check.document"),
            t("studio.render.check.documentNo"),
          )}
          {check(
            state.capability?.available === true,
            t("studio.render.check.renderer"),
            null,
            state.capability === null ? (
              <p className="text-[13px] text-muted-ink">{t("studio.render.check.rendererLoading")}</p>
            ) : !state.capability.available && state.capability.reason ? (
              <p role="status" className="text-[13px] text-muted-ink">
                {t(`studio.render.unavailable.${state.capability.reason}`)}
              </p>
            ) : undefined,
          )}
        </ul>
        {monitorOnly ? (
          <p className="text-[13px] text-muted-ink">{t("studio.render.monitorOnly")}</p>
        ) : (
          <Button
            size="lg"
            className="w-full"
            disabled={!gate.allowed}
            aria-describedby={gateText !== null ? gateReasonId : undefined}
            onClick={openConfirm}
          >
            {t("studio.render.start", { revision: documentRevision })}
          </Button>
        )}
        {!monitorOnly && gateText !== null ? (
          <p className="flex items-start gap-2 text-[13px] text-muted-ink">
            <Info aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
            <span id={gateReasonId}>{gateText}</span>
          </p>
        ) : null}
        {monitorOnly && offline ? (
          <p role="status" className="text-sm text-muted-ink">
            {t("studio.render.monitorOffline")}
          </p>
        ) : null}
        {state.lastError !== null ? (
          <p role="alert" className="text-sm text-status-failed">
            {t(`studio.render.error.${state.lastError}`)}
          </p>
        ) : null}
        {state.lastError === "plan_limit_reached" ? (
          <a className="text-sm text-copper underline" href="/billing">
            {t("studio.render.openBilling")}
          </a>
        ) : null}
        {!monitorOnly && confirmCreate ? (
          <div role="group" aria-labelledby={confirmTitleId} className="flex flex-col gap-3 rounded-[10px] border border-hairline bg-raised p-4 text-sm">
            <h3 id={confirmTitleId} className="font-semibold">
              {t("studio.render.confirm.title")}
            </h3>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px] text-muted-ink">
              <dt>{t("studio.render.confirm.project")}</dt>
              <dd className="truncate font-mono">{confirmCreate.projectId}</dd>
              <dt>{t("studio.render.confirm.document")}</dt>
              <dd className="truncate font-mono">{confirmCreate.documentId}</dd>
              <dt>{t("studio.render.confirm.revision")}</dt>
              <dd className="font-mono">{confirmCreate.documentRevision}</dd>
              <dt>{t("studio.render.confirm.template")}</dt>
              <dd className="font-mono">
                {confirmCreate.templateId} v{confirmCreate.templateVersion}
              </dd>
              <dt>{t("studio.render.confirm.preset")}</dt>
              <dd className="font-mono">{confirmCreate.presetId}</dd>
            </dl>
            <p className="text-[13px] text-muted-ink">{t("studio.render.confirm.note")}</p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setConfirmCreate(null)}>
                {t("studio.render.confirm.keep")}
              </Button>
              <Button size="sm" onClick={startCreate}>
                {t("studio.render.confirm.start")}
              </Button>
            </div>
          </div>
        ) : null}
        <p className="flex items-start gap-2 text-[13px] text-faint">
          <Info aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          {t("studio.render.scope")}
        </p>
      </section>

      <div className="flex min-w-0 flex-col gap-8">
        {selected ? (
          <div className="flex flex-col gap-4" aria-label={t("studio.render.current")}>
            <header className="flex flex-wrap items-center gap-3">
              <h2 className="text-lg font-semibold">{heading(selected)}</h2>
              <p
                role="status"
                className="inline-flex h-6 items-center gap-1.5 rounded-full bg-raised px-2.5 text-[13px] font-medium text-ink"
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "size-2 rounded-full",
                    running
                      ? "animate-pulse bg-status-running"
                      : selected.status === "completed"
                        ? "bg-status-done"
                        : selected.status === "failed"
                          ? "bg-status-failed"
                          : "bg-status-idle",
                  )}
                />
                {statusLabel(selected.status)}
                {typeof selected.progress_percent === "number" ? ` · ${selected.progress_percent}%` : ""}
              </p>
              {secondsLeft !== null ? (
                <span className="ml-auto text-sm text-muted-ink">
                  {t("studio.render.left", { time: formatDuration(locale, secondsLeft) })}
                </span>
              ) : null}
            </header>
            {running && typeof selected.progress_percent === "number" ? (
              <div className="h-1 overflow-hidden rounded-full bg-raised" aria-hidden="true">
                <div className="h-full bg-status-running" style={{ width: `${selected.progress_percent}%` }} />
              </div>
            ) : null}
            {running ? <StageStepper label={t("studio.render.stepsLabel")} now={now} stages={steps(selected)} /> : null}
            {selected.status === "failed" ? (
              <p className="text-sm text-status-failed">{t(failureKey(selected))}</p>
            ) : null}
            {selected.status === "completed" && outputMeta(selected) ? (
              <p className="text-sm text-muted-ink">{outputMeta(selected)}</p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              {canDownload(selected) ? (
                <Button disabled={state.mutation !== null || offline} onClick={() => startDownload(selected)}>
                  {t("studio.render.download")}
                </Button>
              ) : null}
              {!monitorOnly && selected.status === "completed" ? (
                <Button variant="secondary" disabled={!gate.allowed} onClick={openConfirm}>
                  {t("studio.render.again")}
                </Button>
              ) : null}
              {!monitorOnly && canCancel(selected) ? (
                <Button variant="secondary" disabled={state.mutation !== null || offline} onClick={() => startCancel(selected)}>
                  {t("studio.render.cancel")}
                </Button>
              ) : null}
              {!monitorOnly && canRetry(selected) ? (
                <Button variant="secondary" disabled={!gate.allowed} onClick={() => startRetry(selected)}>
                  {t("studio.render.retry")}
                </Button>
              ) : null}
              {!monitorOnly && canCleanup(selected) ? (
                <Button
                  variant="ghost"
                  disabled={state.mutation !== null || offline}
                  onClick={() => {
                    if (offlineRef.current) return;
                    setConfirmCleanup(selected.render_job_id);
                  }}
                >
                  {t("studio.render.delete")}
                </Button>
              ) : null}
            </div>
            {!monitorOnly && confirmCleanup !== null ? (
              <div
                role="group"
                aria-label={t("studio.render.delete")}
                className="flex flex-col gap-3 rounded-[10px] bg-status-failed/10 p-4 text-sm"
              >
                <p>{t("studio.render.cleanup.note")}</p>
                <div className="flex gap-2">
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={state.mutation !== null || offline}
                    onClick={() => startCleanup(confirmCleanup)}
                  >
                    {t("studio.render.cleanup.delete")}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setConfirmCleanup(null)}>
                    {t("studio.render.cleanup.keep")}
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 rounded-[10px] bg-surface px-6 py-12 text-center">
            <Film aria-hidden="true" className="size-6 text-faint" />
            <p className="font-medium">{t("studio.render.noActive")}</p>
            <p className="text-sm text-muted-ink">{t("studio.render.noActiveHint")}</p>
          </div>
        )}

        <section aria-labelledby={outputsId} className="flex flex-col gap-2">
          <h3 id={outputsId} className="text-[13px] font-semibold tracking-[0.06em] text-muted-ink uppercase">
            {t("studio.render.outputs")}
          </h3>
          {!state.history.length ? <p className="text-sm text-muted-ink">{t("studio.render.noOutputs")}</p> : null}
          <ol className="flex flex-col divide-y divide-hairline" aria-label={t("studio.render.history")}>
            {state.history.map((entry) => {
              const output = entry.status === "completed" ? entry.output : null;
              return (
                <li key={entry.render_job_id}>
                  <button
                    type="button"
                    className={cn(
                      "flex w-full items-center gap-3 rounded-md px-2 py-3 text-left transition-colors hover:bg-surface focus-visible:outline-2 focus-visible:outline-copper",
                      entry.render_job_id === state.selectedJobId && "bg-surface",
                    )}
                    aria-label={t("studio.render.historyItem", { when: entry.created_at, status: statusLabel(entry.status) })}
                    aria-current={entry.render_job_id === state.selectedJobId}
                    onClick={() => dispatch({ type: "job_selected", renderJobId: entry.render_job_id })}
                  >
                    <span className="flex h-12 w-9 shrink-0 items-center justify-center rounded-md bg-raised">
                      {entry.status === "failed" ? (
                        <X aria-hidden="true" className="size-4 text-status-failed" />
                      ) : (
                        <Film aria-hidden="true" className="size-4 text-faint" />
                      )}
                    </span>
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate text-[15px] text-ink">
                        {output
                          ? t("studio.render.rowOutput", { revision: entry.document_revision, width: output.width, height: output.height })
                          : t("studio.render.rowTitle", { revision: entry.document_revision, status: statusLabel(entry.status) })}
                      </span>
                      <span className={cn("truncate text-[13px]", entry.status === "failed" ? "text-status-failed" : "text-muted-ink")}>
                        {[
                          output ? `${size(output.size_bytes)} · ${clock(output.duration_seconds)}` : null,
                          entry.status === "failed" ? t(failureKey(entry)) : null,
                          when(entry.created_at),
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </section>
      </div>
    </section>
  );
}
