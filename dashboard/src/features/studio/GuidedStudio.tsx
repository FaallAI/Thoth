import { useEffect, useId, useMemo, useReducer, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Redo2, Sparkles, Undo2 } from "lucide-react";

import type {
  ControlPlaneClient,
  EditDocument,
  EditDocumentOperation,
  EditorAsset,
  StudioImportItem,
  StudioMaterials,
} from "@/api/control-plane";
import { useLocale } from "@/lib/locale";
import type { PreviewSources } from "./AdvancedTimelineComposition";
import { AssetLibrary } from "./AssetLibrary";
import { CaptionTextInspector } from "./CaptionTextInspector";
import { CompactStudioNav } from "./CompactStudioNav";
import {
  canStartUpgrade,
  createEditorState,
  editorReducer,
  sceneTextClip,
  hasValidText,
  toEditDocumentPatch,
  type EditorState,
} from "./editor_state";
import { Inspector } from "./Inspector";
import { IssuesBar } from "./IssuesPanel";
import { RenderPanel, type RenderPanelClient } from "./RenderPanel";
import { SceneAudioInspector } from "./SceneAudioInspector";
import { SceneBoard } from "./SceneBoard";
import { SceneMediaInspector } from "./SceneMediaInspector";
import { Timeline } from "./Timeline";
import { StudioHeader } from "./StudioHeader";
import { TimelineInspector } from "./TimelineInspector";
import { assetLabel, clipLabel, type LabelContext } from "./studio_labels";
import {
  createAddClipFromAssetOperation,
  isTimelineDocument,
  timelineIssues,
} from "./timeline_domain";
import { StudioPreview } from "./StudioPreview";
import { StudioJobNav } from "./StudioJobNav";
import { StudioReviewPanel, type StudioReviewClient } from "./StudioReviewPanel";
import { useStudioViewport, type StudioEditPane, type StudioJob } from "./studio_viewport";
import { usePlayerTimeline, type PlayerTimelineRef } from "./usePlayerTimeline";
import { AssistPanel } from "./story/AssistPanel";
import { BeatInspector } from "./story/BeatInspector";
import { BeatStrip } from "./story/BeatStrip";
import { MaterialsPanel } from "./story/MaterialsPanel";
import { NarrationStatus } from "./script/NarrationStatus";
import { ScriptPanel } from "./script/ScriptPanel";
import { SfxLibrary } from "./script/NarrationPresetForm";
import { adoptNarratedRevision, isNarrationActive, useNarration } from "./script/useNarration";
import { SafeZoneOverlay } from "./story/SafeZone";
import { ROLE_BEAT, computeBeats, type BeatId } from "./story/story_beats";
import { BEAT_ROLE, addHook, addMaterialToBeat, addOutro, creditLine } from "./story/story_edits";
import "./studio.css";

type Props = {
  client: Pick<ControlPlaneClient, "getEditDocument" | "patchEditDocument"> &
    // Advanced editing degrades to guided editing wherever these are absent.
    Partial<
      Pick<
        ControlPlaneClient,
        | "upgradeEditDocument"
        | "listEditorAssets"
        | "createEditorPreviewCapability"
        | "getRenderCapability"
        | "createRenderJob"
        | "listRenderJobs"
        | "getRenderJob"
        | "cancelRenderJob"
        | "retryRenderJob"
        | "downloadRenderOutput"
        | "cleanupRenderArtifacts"
        | "getStudioImportInventory"
        | "getStudioMaterials"
        | "attachStudioMaterial"
        | "resolveStudioImportItem"
        | "requestStoryAssist"
        | "startNarration"
        | "getNarration"
        | "decideNarration"
        | "editNarrationBeat"
        | "revoiceNarrationBeat"
        | "cancelNarration"
        | "restartNarration"
        | "listSfx"
        | "addSfxToProject"
        | "listStudioReviewComments"
        | "createStudioReviewComment"
        | "listStudioReviewDecisions"
        | "createStudioReviewDecision"
      >
    >;
  projectId: string;
  documentId: string;
  documentTitle?: string;
  projectName?: string;
  workspaceControls?: ReactNode;
  onBack: () => void;
  /** Reopen the source inventory of a draft opened from a Content Set. */
  onResolveImports?: () => void;
};

const toolbarButton =
  "rounded-md border border-border px-3 py-1.5 text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-40";

function Editor({ client, projectId, documentId, documentTitle, projectName, workspaceControls, onBack, onResolveImports, document }: Props & { document: EditDocument }) {
  const { t } = useLocale();
  const [state, dispatch] = useReducer(editorReducer, document, createEditorState);
  // The job is the destination at every width; compact screens also pick one
  // Edit pane at a time.
  const [job, setJob] = useState<StudioJob>("edit");
  const [editPane, setEditPane] = useState<StudioEditPane>("preview");
  const viewport = useStudioViewport();
  const compact = viewport === "phone" || viewport === "tablet";
  const [sceneBoardOpen, setSceneBoardOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const collapsible = viewport === "compact_desktop";
  const sceneRegionOpen = !collapsible || sceneBoardOpen;
  const inspectorRegionOpen = !collapsible || inspectorOpen;
  const sceneWidthId = useId();
  const inspectorWidthId = useId();
  const [sceneBoardWidth, setSceneBoardWidth] = useState(14);
  const [inspectorWidth, setInspectorWidth] = useState(22.25);
  const selectedScene = state.draft.scenes.find((scene) => scene.scene_id === state.selectedSceneId);
  const timeline = isTimelineDocument(state.draft) ? state.draft : undefined;
  // Both modes project the same draft; only version 2 can show the advanced one. Every width
  // edits Story or Timeline; compact screens show them one pane at a time (spec 2026-11-01).
  const advanced = Boolean(timeline) && state.mode === "advanced";
  const story = Boolean(timeline) && !advanced;
  // Below 1024 the Timeline is a view: its lanes show, edits happen on a larger screen.
  const timelineReadOnly = compact && advanced;
  const [safeZone, setSafeZone] = useState(false);
  const [selectedBeat, setSelectedBeat] = useState<BeatId | null>(null);
  const [inventory, setInventory] = useState<StudioImportItem[]>([]);
  const [materials, setMaterials] = useState<StudioMaterials | null>(null);
  const [commentFocusRequest, setCommentFocusRequest] = useState(0);
  const [assistOn, setAssistOn] = useState(false);
  const [refusalsSeen, setRefusalsSeen] = useState(0);
  const selectedClip = sceneTextClip(state.draft, selectedScene);
  const [previewSources, setPreviewSources] = useState<PreviewSources>({});
  const upgradeReasonId = useId();
  const modeGroupId = useId();
  // The Player lives in state, so replacing it re-binds the timeline listeners.
  const [attachedPlayer, setAttachedPlayer] = useState<PlayerTimelineRef | null>(null);
  const player = usePlayerTimeline(
    attachedPlayer,
    (frame) => dispatch({ type: "set_playhead", frame }),
    (playing) => dispatch({ type: "set_playing", playing }),
  );
  /** Bumped on upgrade and unmount so a response that outlives this document is dropped. */
  const generation = useRef(0);
  useEffect(() => () => {
    generation.current += 1;
  }, []);
  const { base, draft, pendingOperations, saveStatus } = state;
  const backDisabled = saveStatus !== "saved";
  // An upgrade replaces the document, so nothing may edit it until it settles.
  const upgrading = state.upgradeStatus === "running";
  const editing = job === "edit";
  // Simple desktop editing lays the scenes out as a strip under the preview.
  const stripLayout = editing && !compact && !advanced && !story;
  const workstationStyle = compact
    ? undefined
    : ({
        "--scene-board-width": `${sceneBoardWidth}rem`,
        "--inspector-width": `${inspectorWidth}rem`,
        gridTemplateRows: stripLayout ? "minmax(0,1fr) 228px" : story && editing ? "minmax(0,1fr) auto" : undefined,
        gridTemplateColumns: [
          editing && sceneRegionOpen && !stripLayout && (story ? "18rem" : "var(--scene-board-width)"),
          "minmax(0,1fr)",
          editing && inspectorRegionOpen && "var(--inspector-width)",
        ]
          .filter(Boolean)
          .join(" "),
      } as CSSProperties);
  const reviewing = job === "review";
  const previewVisible = reviewing || (editing && (!compact || editPane === "preview" || (advanced && editPane === "timeline")));
  const { pause } = player;
  // Kind and source, never an id (spec 2026-11-01, Studio shell v2).
  const labels: LabelContext | null = timeline ? { document: timeline, materials, t, inventory } : null;
  const labelOf = labels ? (clip: Parameters<typeof clipLabel>[0]) => clipLabel(clip, labels) : undefined;
  const describeAsset = labels
    ? (asset: EditorAsset) => {
        const named = assetLabel(asset.asset_id, labels, asset);
        const kind = t(`studio.label.kind.${asset.kind}`);
        return {
          label: named.label,
          detail: named.seconds == null ? kind : `${kind} · ${t("studio.story.seconds", { seconds: named.seconds.toFixed(1) })}`,
        };
      }
    : undefined;

  // A hidden preview must not keep playing; showing it again never resumes it.
  useEffect(() => {
    if (!previewVisible) pause();
  }, [pause, previewVisible]);

  const selectJob = (next: StudioJob) => setJob(next);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const handleOffline = () => dispatch({ type: "went_offline" });
    const handleOnline = () => dispatch({ type: "went_online" });
    if (window.navigator.onLine === false) dispatch({ type: "went_offline" });
    window.addEventListener("offline", handleOffline);
    window.addEventListener("online", handleOnline);
    return () => {
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("online", handleOnline);
    };
  }, []);

  useEffect(() => {
    if (saveStatus !== "dirty" || !pendingOperations.length || !hasValidText(draft)) return;
    const patch = toEditDocumentPatch({ base, pendingOperations });
    const operationIds = patch.operations.map((operation) => operation.operation_id);
    const timeoutId = setTimeout(() => {
      const requestGeneration = generation.current;
      dispatch({ type: "save_started", operationIds });
      void client
        .patchEditDocument(projectId, documentId, patch)
        .then((result) => {
          if (requestGeneration !== generation.current) return;
          dispatch(
            result.kind === "saved"
              ? { type: "save_succeeded", document: result.document, operationIds }
              : { type: "save_conflicted", latest: result.latest },
          );
        })
        .catch(() => {
          if (requestGeneration === generation.current) dispatch({ type: "save_failed" });
        });
    }, 500);
    return () => clearTimeout(timeoutId);
  }, [base, client, documentId, draft, pendingOperations, projectId, saveStatus]);

  const makeOperationId = () => `op_${crypto.randomUUID()}`;

  const { listEditorAssets, createEditorPreviewCapability } = client;
  // A stable slice: a fresh object per render would restart the library's paged load.
  const assetClient = useMemo(
    () =>
      listEditorAssets && createEditorPreviewCapability
        ? { listEditorAssets, createEditorPreviewCapability }
        : undefined,
    [listEditorAssets, createEditorPreviewCapability],
  );

  const {
    getRenderCapability,
    createRenderJob,
    listRenderJobs,
    getRenderJob,
    cancelRenderJob,
    retryRenderJob,
    downloadRenderOutput,
    cleanupRenderArtifacts,
    getStudioImportInventory,
  } = client;
  // Rendering appears only where the whole render API is present, and the slice
  // is stable so the panel does not reload on every keystroke in the draft.
  const renderClient = useMemo<RenderPanelClient | undefined>(
    () =>
      getRenderCapability &&
      createRenderJob &&
      listRenderJobs &&
      getRenderJob &&
      cancelRenderJob &&
      retryRenderJob &&
      downloadRenderOutput &&
      cleanupRenderArtifacts
        ? {
            getRenderCapability,
            createRenderJob,
            listRenderJobs,
            getRenderJob,
            cancelRenderJob,
            retryRenderJob,
            downloadRenderOutput,
            cleanupRenderArtifacts,
            getStudioImportInventory,
          }
        : undefined,
    [
      getRenderCapability,
      createRenderJob,
      listRenderJobs,
      getRenderJob,
      cancelRenderJob,
      retryRenderJob,
      downloadRenderOutput,
      cleanupRenderArtifacts,
      getStudioImportInventory,
    ],
  );

  const {
    listStudioReviewComments,
    createStudioReviewComment,
    listStudioReviewDecisions,
    createStudioReviewDecision,
  } = client;
  // Review appears only where the whole review API is present, as a stable slice.
  const reviewClient = useMemo<StudioReviewClient | undefined>(
    () =>
      listStudioReviewComments && createStudioReviewComment && listStudioReviewDecisions && createStudioReviewDecision
        ? { listStudioReviewComments, createStudioReviewComment, listStudioReviewDecisions, createStudioReviewDecision }
        : undefined,
    [listStudioReviewComments, createStudioReviewComment, listStudioReviewDecisions, createStudioReviewDecision],
  );

  // A stale review write names a newer saved revision; fetching it hands the
  // choice to the existing conflict banner, so no local draft is ever dropped.
  const loadNewerRevision = () => {
    const requestGeneration = generation.current;
    void client
      .getEditDocument(projectId, documentId)
      .then((latest) => {
        if (requestGeneration === generation.current && latest.revision > base.revision) {
          dispatch({ type: "save_conflicted", latest });
        }
      })
      .catch(() => {});
  };

  // Simple mode attaches audio from the project's ready assets; Advanced loads them through its library.
  // ponytail: first page only (50 assets); page through when projects outgrow it.
  const [simpleAssetsFailed, setSimpleAssetsFailed] = useState(false);
  const hasTimeline = Boolean(timeline);
  useEffect(() => {
    if (!hasTimeline || advanced || !assetClient) return;
    const requestGeneration = generation.current;
    void assetClient.listEditorAssets(projectId, undefined, 50).then(
      (page) => {
        if (requestGeneration !== generation.current) return;
        setSimpleAssetsFailed(false);
        dispatch({ type: "assets_loaded", assets: page.assets, replace: true });
      },
      () => requestGeneration === generation.current && setSimpleAssetsFailed(true),
    );
  }, [hasTimeline, advanced, assetClient, projectId]);

  // Beats fall back to the import inventory for clips saved before Story mode (spec 4).
  useEffect(() => {
    if (!hasTimeline || !getStudioImportInventory) return;
    const requestGeneration = generation.current;
    void getStudioImportInventory(projectId, documentId).then(
      (loaded) => requestGeneration === generation.current && setInventory(loaded.items),
      // A draft made in Studio has no inventory; beats then come from `source_role` alone.
      () => {},
    );
  }, [hasTimeline, getStudioImportInventory, projectId, documentId]);
  const beats = useMemo(() => (timeline ? computeBeats(timeline, inventory) : []), [timeline, inventory]);

  const { getStudioMaterials } = client;
  useEffect(() => {
    if (!story || !getStudioMaterials) return;
    const requestGeneration = generation.current;
    void getStudioMaterials(projectId, documentId).then(
      (loaded) => requestGeneration === generation.current && setMaterials(loaded),
      // A draft made in Studio has no materials route answer; the panel lists uploads only.
      () => {},
    );
  }, [story, getStudioMaterials, projectId, documentId]);

  // Auto-draft narration (spec 2026-10-31): read and polled here; when it completes, the
  // revision the narration wrote is adopted like any newer saved revision.
  const narrationClient =
    client.startNarration && client.getNarration && client.decideNarration && client.editNarrationBeat && client.revoiceNarrationBeat && client.cancelNarration && client.restartNarration
      ? (client as Required<Pick<typeof client, "startNarration" | "getNarration" | "decideNarration" | "editNarrationBeat" | "revoiceNarrationBeat" | "cancelNarration" | "restartNarration">>)
      : undefined;
  const [narration, setNarration] = useNarration(narrationClient, projectId, documentId, Boolean(timeline && narrationClient), () => {
    void client.getEditDocument(projectId, documentId).then(
      (latest) => adoptNarratedRevision(dispatch, latest),
      () => {},
    );
  });
  const [showScript, setShowScript] = useState(false);
  // Beats with a narration voice, and those whose text changed after it (spec 2026-11-01, goal 6).
  const voicedBeats = new Set(
    (timeline?.clips ?? []).flatMap((clip) => (clip.clip_id.startsWith("clip_narration_") ? [clip.clip_id.slice("clip_narration_".length) as BeatId] : [])),
  );
  const staleBeats = new Set<BeatId>(narration?.status === "completed" ? (narration.stale_beats ?? []) : []);
  const narrationLocked = isNarrationActive(narration);

  // Story previews the draft's own media, its narration voices included; Timeline's library
  // is not mounted here.
  const mediaIds = useMemo(
    () => (timeline?.asset_refs ?? []).map((ref) => ref.asset_id).join(" "),
    [timeline],
  );
  useEffect(() => {
    if (!story || !assetClient || !mediaIds) return;
    const requestGeneration = generation.current;
    for (const assetId of mediaIds.split(" ")) {
      if (assetId in previewSources) continue;
      void assetClient.createEditorPreviewCapability(projectId, assetId).then(
        (capability) =>
          requestGeneration === generation.current &&
          setPreviewSources((current) => ({ ...current, [assetId]: capability.preview_url })),
        () => {},
      );
    }
    // previewSources is read, not watched: each asset is asked for once per change of the media set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [story, assetClient, mediaIds, projectId]);

  const selectBeat = (id: BeatId) => {
    const beat = beats.find((entry) => entry.id === id);
    if (!beat) return;
    setSelectedBeat(id);
    player.seekTo(beat.startFrame);
    dispatch({ type: "set_playhead", frame: beat.startFrame });
    // The text and captions below the beat follow the beat's own scene.
    const sceneId = timeline?.clips?.find((clip) => clip.clip_id === beat.clipIds[0])?.scene_id;
    if (sceneId) dispatch({ type: "select_scene", sceneId });
  };
  const { attachStudioMaterial } = client;
  const attachMaterial = useMemo(
    () => (attachStudioMaterial ? (itemId: string) => attachStudioMaterial(projectId, documentId, itemId) : undefined),
    [attachStudioMaterial, projectId, documentId],
  );
  // The first beat is open until another is chosen, as the design shows.
  const shownBeat = beats.find((beat) => beat.id === selectedBeat) ?? beats[0];
  // Spec 8: Hook takes the run's title, Outro the credit line; each only while the draft lacks it.
  const mainMaterial = materials?.items.find((item) => item.role === "main");
  const hookTitle = mainMaterial?.label || documentTitle || "";
  // Only a confirmed original names its creator; "unresolved" may be a reposter (final review I2).
  const credit =
    mainMaterial?.verdict === "original" || mainMaterial?.verdict === "replaced"
      ? creditLine(mainMaterial.owner_handle, mainMaterial.platform)
      : "";
  const addable = (["hook", "outro"] as const).filter(
    (id) => !beats.some((beat) => beat.id === id) && (id === "hook" ? hookTitle : credit),
  );
  const addBeat = (id: "hook" | "outro") => {
    if (!timeline) return;
    const operations = id === "hook" ? addHook(timeline, hookTitle) : addOutro(timeline, credit);
    dispatch({ type: "commit_operations", operations });
  };
  const { requestStoryAssist } = client;
  const askAssist = useMemo(
    () =>
      requestStoryAssist
        ? (body: Parameters<typeof requestStoryAssist>[2]) => requestStoryAssist(projectId, documentId, body)
        : undefined,
    [requestStoryAssist, projectId, documentId],
  );

  // Spec 9: a material dropped on a tile joins that beat, taking the beat's role.
  const dropMaterial = async (beatId: BeatId, data: string) => {
    const beat = beats.find((entry) => entry.id === beatId);
    if (!beat || !timeline || !data) return;
    const upload = data.startsWith("upload:") ? state.assets[data.slice("upload:".length)] : undefined;
    const item = upload ? undefined : materials?.items.find((entry) => entry.item_id === data);
    const role = item?.role && ROLE_BEAT[item.role] === beatId ? item.role : BEAT_ROLE[beatId];
    if (!role || (!upload && !(item && attachMaterial))) return;
    try {
      const asset = upload ?? (await attachMaterial!(item!.item_id));
      if (!upload) dispatch({ type: "assets_loaded", assets: [asset], replace: false });
      dispatch({ type: "commit_operations", operations: addMaterialToBeat(timeline, beat, asset, role) });
    } catch {
      // The material stays in the panel; dropping it again retries.
    }
  };

  // Excluding is an import decision on the saved revision, as the import gate makes it.
  const { resolveStudioImportItem } = client;
  const removeMissing =
    resolveStudioImportItem && saveStatus === "saved"
      ? async (itemId: string) => {
          const requestGeneration = generation.current;
          const decided = await resolveStudioImportItem(projectId, documentId, itemId, {
            base_revision: base.revision,
            decision: { kind: "exclude" },
          });
          if (requestGeneration !== generation.current) return;
          setInventory(decided.items);
          // The decision recorded a new revision with the same content; adopt it.
          const latest = await client.getEditDocument(projectId, documentId);
          if (requestGeneration === generation.current) dispatch({ type: "save_succeeded", document: latest, operationIds: [] });
        }
      : undefined;

  const requestReview = () => {
    setJob("review");
    setCommentFocusRequest((value) => value + 1);
  };

  const commitSceneOperation = (operation: EditDocumentOperation) => {
    dispatch({ type: "commit_timeline_operation", operation });
    if (operation.kind !== "add_clip_from_asset" || !assetClient) return;
    // Attached audio should play in the preview without a trip to the Advanced library.
    const requestGeneration = generation.current;
    void assetClient.createEditorPreviewCapability(projectId, operation.asset_id).then(
      (capability) => {
        if (requestGeneration !== generation.current) return;
        setPreviewSources((current) => ({ ...current, [operation.asset_id]: capability.preview_url }));
      },
      () => {},
    );
  };

  const addAsset = (asset: EditorAsset) => {
    if (!timeline) return;
    const operation = createAddClipFromAssetOperation(timeline, asset, state.playheadFrame, {
      operationId: makeOperationId(),
      clipId: `clip_${crypto.randomUUID()}`,
    });
    if (operation) dispatch({ type: "commit_timeline_operation", operation });
  };

  const upgradeDocument = () => {
    const upgrade = client.upgradeEditDocument;
    if (!upgrade || !canStartUpgrade(state)) return;
    // A replacement invalidates every response owned by the document it replaces.
    generation.current += 1;
    const requestGeneration = generation.current;
    dispatch({ type: "upgrade_started" });
    void upgrade(projectId, documentId, { base_revision: draft.revision }, makeOperationId())
      .then((result) => {
        if (requestGeneration !== generation.current) return;
        dispatch(
          result.kind === "conflict"
            ? { type: "upgrade_conflicted", latest: result.latest }
            : { type: "upgrade_succeeded", document: result.document },
        );
      })
      .catch(() => {
        if (requestGeneration === generation.current) dispatch({ type: "upgrade_failed" });
      });
  };

  const saveDot: Record<EditorState["saveStatus"], string> = {
    saved: "bg-status-done",
    dirty: "bg-status-waiting",
    saving: "bg-status-waiting animate-pulse",
    failed: "bg-status-failed",
    conflict: "bg-status-failed",
    offline: "bg-status-idle",
  };
  const banner = "flex flex-wrap items-center gap-3 border-b border-hairline px-4 py-2 text-sm";
  const iconButton =
    "grid size-9 place-items-center rounded-md text-muted-ink hover:bg-surface hover:text-ink focus-visible:outline-2 focus-visible:outline-copper disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <section className={`studio-shell pen-studio studio-job-${job} ${advanced ? "studio-advanced" : "studio-simple"}${story ? " studio-story" : ""} flex min-h-0 flex-1 flex-col bg-background text-foreground`} aria-label="Guided Studio">
      {/* DESIGN §13: back to the documents, the title, the destinations, and where saving stands. */}
      <StudioHeader
        title={documentTitle ?? documentId}
        viewport={viewport}
        onBack={onBack}
        backDisabled={backDisabled}
        jobs={<StudioJobNav selected={job} onSelect={selectJob} />}
        mode={
          <>
        {timeline ? (
          <div role="group" aria-label={t("studio.editor.mode")} id={modeGroupId} className="flex rounded-md bg-well p-0.5">
            {(["simple", "advanced"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                className="rounded px-2.5 py-1 text-[13px] text-muted-ink aria-[pressed=true]:bg-raised aria-[pressed=true]:text-ink focus-visible:outline-2 focus-visible:outline-copper"
                aria-pressed={state.mode === mode}
                onClick={() => dispatch({ type: "set_editor_mode", mode })}
              >
                {t(mode === "simple" ? "studio.editor.story" : "studio.editor.timeline")}
              </button>
            ))}
          </div>
        ) : null}
        {!compact && !timeline ? (
          <div className="flex rounded-md bg-well p-0.5" role="group" aria-label={t("studio.editor.mode")}>
            <button type="button" aria-pressed="true" className="rounded bg-raised px-2.5 py-1 text-[13px] text-ink">
              {t("studio.editor.story")}
            </button>
            <button
              type="button"
              disabled
              title={t("studio.editor.advancedDisabled")}
              className="rounded px-2.5 py-1 text-[13px] text-faint"
            >
              {t("studio.editor.timeline")}
            </button>
          </div>
        ) : null}
          </>
        }
        extra={
          <>
        {compact && !timeline && client.upgradeEditDocument ? (
          <p className="text-xs text-muted-ink max-md:order-last">{t("studio.editor.compactEnable")}</p>
        ) : null}
          </>
        }
        history={
          <>
        {viewport === "phone" ? null : (
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            className={iconButton}
            aria-label={t("studio.editor.undo")}
            disabled={!state.history.length || state.inFlightOperationIds.length > 0 || upgrading}
            onClick={() => dispatch({ type: "undo" })}
          >
            <Undo2 aria-hidden="true" size={16} />
          </button>
          <button
            type="button"
            className={iconButton}
            aria-label={t("studio.editor.redo")}
            disabled={!state.future.length || state.inFlightOperationIds.length > 0 || upgrading}
            onClick={() => dispatch({ type: "redo" })}
          >
            <Redo2 aria-hidden="true" size={16} />
          </button>
        </div>
        )}
          </>
        }
        save={
          <>
          <span aria-hidden="true" className={`size-2 rounded-full ${saveDot[state.saveStatus]}`} />
          {/* The document's own project, which the global project switcher may no longer show. */}
          <span aria-live="polite">{t(`studio.editor.status.${state.saveStatus}`)}</span>
          <span aria-hidden="true" className="font-mono text-faint max-md:hidden">
            · {t("studio.editor.rev", { revision: base.revision })}
          </span>
          <span className="sr-only">{t("studio.editor.savedRevision", { revision: base.revision })}</span>
          </>
        }
        primary={
        <button
          type="button"
          onClick={requestReview}
          className="h-9 rounded-md border max-md:hidden border-hairline px-3 text-[13px] text-ink hover:bg-surface focus-visible:outline-2 focus-visible:outline-copper"
        >
          {t("studio.editor.requestReview")}
        </button>
        }
        narration={
          <>
        {story && timeline && narrationClient ? (
          <>
            <NarrationStatus
              client={narrationClient}
              projectId={projectId}
              documentId={documentId}
              state={narration}
              variant={viewport === "full_desktop" ? "chip" : "block"}
              onChange={(next) => {
                setNarration(next);
                setShowScript(true);
              }}
              onOpenScript={() => setShowScript(true)}
            />
          </>
        ) : null}
          </>
        }
        menuAttention={Boolean(narration?.stale_beats?.length)}
        menu={
          <>
            {story && timeline && narrationClient ? (
              <div className="flex flex-wrap gap-2 border-b border-hairline pb-3">
            {narration ? (
              <button
                type="button"
                aria-pressed={showScript}
                className="rounded-md bg-well px-2.5 py-1 text-[13px] text-muted-ink aria-[pressed=true]:bg-raised aria-[pressed=true]:text-ink"
                onClick={() => setShowScript((value) => !value)}
              >
                {t("studio.narration.script")}
              </button>
            ) : null}
            {story && askAssist ? (
              <button
                type="button"
                aria-haspopup="dialog"
                aria-expanded={assistOn}
                onClick={() => setAssistOn((on) => !on)}
                className="inline-flex h-9 items-center gap-1.5 rounded-md border border-studio-ai/60 px-3 text-[13px] text-studio-ai focus-visible:outline-2 focus-visible:outline-copper"
              >
                <Sparkles aria-hidden="true" size={14} /> {t("studio.assist.toggle")}
              </button>
            ) : null}
              </div>
            ) : story && askAssist ? (
              <button
                type="button"
                aria-haspopup="dialog"
                aria-expanded={assistOn}
                onClick={() => setAssistOn((on) => !on)}
                className="inline-flex h-9 items-center gap-1.5 self-start rounded-md border border-studio-ai/60 px-3 text-[13px] text-studio-ai focus-visible:outline-2 focus-visible:outline-copper"
              >
                <Sparkles aria-hidden="true" size={14} /> {t("studio.assist.toggle")}
              </button>
            ) : null}
            <span className="text-muted-ink">{t("studio.editor.project", { name: projectName ?? base.project_id })}</span>
            {workspaceControls ?? <p className="text-muted-ink">{t("studio.editor.noSwitch")}</p>}
            {/* Phones hide the top bar's Undo and Redo; they stay reachable here (final review I5). */}
            {viewport === "phone" ? (
            <div className="flex flex-wrap gap-2 border-t border-hairline pt-3">
              <button
                type="button"
                className={toolbarButton}
                disabled={!state.history.length || state.inFlightOperationIds.length > 0 || upgrading}
                onClick={() => dispatch({ type: "undo" })}
              >
                {t("studio.editor.undo")}
              </button>
              <button
                type="button"
                className={toolbarButton}
                disabled={!state.future.length || state.inFlightOperationIds.length > 0 || upgrading}
                onClick={() => dispatch({ type: "redo" })}
              >
                {t("studio.editor.redo")}
              </button>
            </div>
            ) : null}
            {!compact && !timeline && client.upgradeEditDocument ? (
              <div className="flex flex-col gap-1">
                <button
                  type="button"
                  className={`${toolbarButton} self-start`}
                  disabled={!canStartUpgrade(state)}
                  aria-describedby={canStartUpgrade(state) ? undefined : upgradeReasonId}
                  onClick={upgradeDocument}
                >
                  {t("studio.editor.enableAdvanced")}
                </button>
                <span id={upgradeReasonId} className="sr-only">
                  {t("studio.editor.enableReason")}
                </span>
                <span className="text-xs text-muted-ink">{t("studio.editor.enableNote")}</span>
              </div>
            ) : null}
            {compact || !editing ? null : (
              <div className="flex flex-col gap-2 text-xs text-muted-ink" aria-label={t("studio.editor.layout")}>
                {collapsible ? (
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className={toolbarButton} aria-expanded={sceneBoardOpen} aria-controls="studio-region-scenes" onClick={() => setSceneBoardOpen((open) => !open)}>
                      {t("studio.editor.scenePanel")}
                    </button>
                    <button type="button" className={toolbarButton} aria-expanded={inspectorOpen} aria-controls="studio-region-inspector" onClick={() => setInspectorOpen((open) => !open)}>
                      {t("studio.editor.inspectorPanel")}
                    </button>
                  </div>
                ) : null}
                {sceneRegionOpen && !stripLayout ? (
                  <>
                    <label htmlFor={sceneWidthId}>{t("studio.editor.sceneWidth")}</label>
                    <input id={sceneWidthId} type="range" min={12} max={22} step={1} value={sceneBoardWidth} onChange={(event) => setSceneBoardWidth(event.target.valueAsNumber)} />
                  </>
                ) : null}
                {inspectorRegionOpen ? (
                  <>
                    <label htmlFor={inspectorWidthId}>{t("studio.editor.inspectorWidth")}</label>
                    <input id={inspectorWidthId} type="range" min={16} max={28} step={0.25} value={inspectorWidth} onChange={(event) => setInspectorWidth(event.target.valueAsNumber)} />
                  </>
                ) : null}
              </div>
            )}
          </>
        }
      />
      {narrationLocked ? (
        <p role="status" className="border-b border-hairline bg-surface px-4 py-2 text-sm text-copper">
          {t("studio.narration.locked")}
        </p>
      ) : null}

      {state.upgradeStatus === "failed" && (
        <div role="alert" className={`${banner} bg-status-failed/10`}>
          <p>{t("studio.editor.upgradeFailed")}</p>
        </div>
      )}
      {state.saveStatus === "failed" && (
        <div role="alert" className={`${banner} bg-status-failed/10`}>
          <p>{t("studio.editor.saveFailed")}</p>
          <button type="button" className={toolbarButton} onClick={() => dispatch({ type: "retry_save" })}>
            {t("studio.editor.retry")}
          </button>
        </div>
      )}
      {state.saveStatus === "conflict" && (
        <div role="alert" className={`${banner} bg-copper/10`}>
          <p>{t("studio.editor.conflict", { revision: state.latestConflict?.revision ?? "" })}</p>
          <button type="button" className={toolbarButton} onClick={() => dispatch({ type: "reload_latest" })}>
            {t("studio.editor.reloadLatest")}
          </button>
          <button
            type="button"
            className={toolbarButton}
            onClick={() => dispatch({
              type: "keep_editing_locally",
              operationIdPrefix: `op_rebase_${makeOperationId()}`,
            })}
          >
            {t("studio.editor.keepLocal")}
          </button>
        </div>
      )}
      {state.refusedEdits > refusalsSeen && (
        <div role="status" aria-label={t("studio.editor.refusedTitle")} className={`${banner} bg-copper/10`}>
          <p>{t("studio.editor.refused")}</p>
          <button type="button" className={toolbarButton} onClick={() => setRefusalsSeen(state.refusedEdits)}>
            {t("studio.editor.dismiss")}
          </button>
        </div>
      )}
      {state.saveStatus === "offline" && (
        <div role="status" className={`${banner} bg-surface`}>
          <p>{t("studio.editor.offline")}</p>
        </div>
      )}

      {compact && editing ? (
        <CompactStudioNav
          panes={
            advanced
              ? [
                  { id: "scenes", label: t("studio.pane.assets") },
                  { id: "preview", label: t("studio.pane.preview") },
                  { id: "timeline", label: t("studio.pane.timeline") },
                  { id: "controls", label: t("studio.pane.inspector") },
                ]
              : story
                ? [
                    { id: "scenes", label: t("studio.pane.materials") },
                    { id: "preview", label: t("studio.pane.preview") },
                    { id: "controls", label: t("studio.pane.inspector") },
                  ]
                : [
                    { id: "scenes", label: "Scenes" },
                    { id: "preview", label: "Preview" },
                    { id: "controls", label: "Controls" },
                  ]
          }
          selected={editPane}
          onSelect={setEditPane}
        />
      ) : null}

      <div id="studio-panel-scenes" className="flex min-h-0 flex-1 flex-col">
        <div
          aria-label="Guided editing workstation"
          // Render shows nothing from the workstation, so it yields the space.
          hidden={job === "render"}
          style={workstationStyle}
          className={`grid min-h-0 flex-1 ${compact ? "grid-cols-1 overflow-auto" : "overflow-hidden"}`}
        >
          <div
            id="studio-region-scenes"
            className={stripLayout ? "col-span-2 col-start-1 row-start-2 min-w-0" : "contents"}
            hidden={!editing || (compact ? editPane !== "scenes" : !sceneRegionOpen)}
          >
            {story && timeline && showScript && narration && narrationClient ? (
              <ScriptPanel
                client={narrationClient}
                projectId={projectId}
                documentId={documentId}
                state={narration}
                onChange={setNarration}
              />
            ) : story && timeline ? (
              <MaterialsPanel
                materials={materials}
                uploads={Object.values(state.assets)}
                beats={beats}
                document={timeline}
                previews={previewSources}
              />
            ) : advanced ? (
              assetClient ? (
                // One workstation cell: the asset list fills it, the SFX library sits under it.
                <div className="grid min-h-0 grid-rows-[minmax(0,1fr)_auto]">
                <AssetLibrary
                  client={assetClient}
                  describe={describeAsset}
                  projectId={projectId}
                  generationRef={generation}
                  onAssets={(assets, replace) => dispatch({ type: "assets_loaded", assets, replace })}
                  onAdd={addAsset}
                  onPreviewSource={(assetId, previewUrl) =>
                    setPreviewSources((current) => ({ ...current, [assetId]: previewUrl }))
                  }
                />
                {/* The shared SFX library with its labels (spec 2026-10-31, decision 8). */}
                {client.listSfx ? (
                  <div className="max-h-64 overflow-auto border-r border-t border-border bg-card/60 p-2">
                  <SfxLibrary
                    client={{ listSfx: client.listSfx, addSfxToProject: client.addSfxToProject }}
                    projectId={projectId}
                    onAdd={(asset) => {
                      dispatch({ type: "assets_loaded", assets: [asset], replace: false });
                      addAsset(asset);
                    }}
                  />
                  </div>
                ) : null}
                </div>
              ) : null
            ) : (
              <SceneBoard
                document={state.draft}
                selectedSceneId={state.selectedSceneId}
                onSelect={(sceneId) => dispatch({ type: "select_scene", sceneId })}
                onMove={
                  timeline
                    ? (sceneId, toIndex) =>
                        dispatch({
                          type: "commit_timeline_operation",
                          operation: { kind: "reorder_scene", operation_id: makeOperationId(), scene_id: sceneId, to_index: toIndex },
                        })
                    : undefined
                }
                moveDisabled={upgrading}
                onPreview={player.play}
                previewDisabled={saveStatus !== "saved"}
                onAdvanced={() => { if (timeline) dispatch({ type: "set_editor_mode", mode: "advanced" }); else upgradeDocument(); }}
              />
            )}
          </div>
          <main
            hidden={!previewVisible}
            className={`flex min-w-0 flex-col gap-3 bg-black/40 p-4 ${
              // A compact column keeps the preview watchable above the review panel.
              compact ? "min-h-[28rem] [&>section]:min-h-72" : "min-h-0"
            } ${
              stripLayout ? "col-start-1 row-start-1" : ""
            }`}
          >
            {reviewing ? (
              <header className="studio-review-preview-header">
                <div>
                  <h2>{t("studio.review.preview.title")}</h2>
                  <p>{t("studio.review.preview.reviewing", { revision: base.revision })}</p>
                </div>
                <span>{t("studio.review.preview.readOnly")}</span>
              </header>
            ) : null}
            {story && !reviewing ? (
              <div className="flex items-center justify-end gap-2">
                {/* No style preset names a target platform yet, so TikTok's areas are shown. */}
                {safeZone ? <span className="text-xs text-muted-ink">{t("studio.story.safeZonePlatform")}</span> : null}
                <button
                  type="button"
                  aria-pressed={safeZone}
                  onClick={() => setSafeZone((value) => !value)}
                  className="rounded-md border border-hairline px-2.5 py-1 text-[13px] text-muted-ink aria-[pressed=true]:border-copper aria-[pressed=true]:text-ink focus-visible:outline-2 focus-visible:outline-copper"
                >
                  {t("studio.story.safeZone")}
                </button>
              </div>
            ) : null}
            {/* On a compact Timeline pane the lanes take the space; the one preview stays mounted. */}
            <div className="contents" hidden={compact && editPane === "timeline"}>
              <StudioPreview
                overlay={story && !reviewing ? (safeZone ? <SafeZoneOverlay /> : null) : undefined}
                // Review shows what was saved; Edit shows the draft.
                document={reviewing ? base : state.draft}
                onPlayer={setAttachedPlayer}
                embedded
                previewSources={previewSources}
                onPreviewUnavailable={(assetId) =>
                  // Same reference when the asset is already gone, so the player
                  // reporting an unusable source cannot loop the editor.
                  setPreviewSources((current) => {
                    if (!(assetId in current)) return current;
                    const { [assetId]: _dropped, ...rest } = current;
                    return rest;
                  })
                }
              />
            </div>
            {advanced && timeline ? (
              <div className="contents" hidden={reviewing || (compact && editPane !== "timeline")}>
                <Timeline
                  state={state}
                  labelOf={labelOf}
                  readOnly={timelineReadOnly}
                  onInspect={() => setEditPane("controls")}
                  dispatch={dispatch}
                  onSeek={player.seekTo}
                  onPlay={player.play}
                  onPause={player.pause}
                />
                <IssuesBar
                  document={timeline}
                  selectedIssueId={state.selectedIssueId}
                  mode={state.mode}
                  dispatch={dispatch}
                  labelOf={labelOf}
                />
              </div>
            ) : null}
            {reviewClient ? (
              // Beside the one shared preview; other jobs hide it without unmounting unsent text.
              <div hidden={!reviewing} className="studio-review-panel-region">
                <StudioReviewPanel
                  client={reviewClient}
                  projectId={projectId}
                  documentId={documentId}
                  savedDocument={base}
                  saveStatus={saveStatus}
                  isOffline={state.isOffline}
                  // The saved revision's own validity, the same facts the server checks.
                  blockingIssues={(isTimelineDocument(base) ? timelineIssues(base).length : 0) + (hasValidText(base) ? 0 : 1)}
                  currentFrame={state.playheadFrame}
                  onLoadRevision={loadNewerRevision}
                  commentFocusRequest={commentFocusRequest}
                />
              </div>
            ) : (
              <p role="status" hidden={!reviewing} className="text-sm text-muted-foreground">
                Review is not available in this Studio session. Your draft is unaffected.
              </p>
            )}
            {reviewing ? <p className="studio-review-preview-footer">{t("studio.review.preview.footer")}</p> : null}
          </main>
          <div
            id="studio-region-inspector"
            className="contents"
            hidden={!editing || (compact ? editPane !== "controls" : !inspectorRegionOpen)}
          >
            {advanced && timeline ? (
              <TimelineInspector
                document={timeline}
                labelOf={labelOf}
                selectedClipId={state.selectedClipId}
                selectedTrackId={state.selectedTrackId}
                onOperation={(operation) => dispatch({ type: "commit_timeline_operation", operation })}
              />
            ) : (
              // One grid cell: the caption editor stacks under the copy inspector.
              <div
                className={`studio-simple-inspector flex min-h-0 flex-col overflow-auto ${stripLayout ? "col-start-2 row-start-1" : ""}`}
              >
                {story && timeline ? (
                  shownBeat ? (
                    <BeatInspector
                      beat={shownBeat}
                      beats={beats}
                      document={timeline}
                      inventory={inventory}
                      materials={materials}
                      dispatch={dispatch}
                      attachMaterial={attachMaterial}
                      onRemoveMissing={removeMissing}
                      narrated={voicedBeats.has(shownBeat.id)}
                    />
                  ) : (
                    <p className="p-4 text-sm text-muted-ink">{t("studio.inspector.empty")}</p>
                  )
                ) : null}
                {story && shownBeat && assistOn && askAssist ? (
                  <AssistPanel
                    key={shownBeat.id}
                    request={askAssist}
                    baseRevision={base.revision}
                    beat={shownBeat}
                    document={timeline!}
                    ready={saveStatus === "saved"}
                    dispatch={dispatch}
                  />
                ) : null}
                <Inspector
                  scene={selectedScene}
                  clip={selectedClip}
                  fps={state.draft.canvas.fps}
                  disabled={upgrading}
                  textLocked={Boolean(
                    timeline &&
                      selectedClip &&
                      ((clip) =>
                        clip?.locked ||
                        timeline.tracks.find((track) => track.track_id === clip?.track_id)?.locked)(
                        timeline.clips?.find((entry) => entry.clip_id === selectedClip.clip_id),
                      ),
                  )}
                  sceneIndex={state.draft.scenes.findIndex((scene) => scene.scene_id === state.selectedSceneId)}
                  sceneCount={state.draft.scenes.length}
                  textOnly={viewport === "phone"}
                  onTextChange={(clipId, field, value) =>
                    dispatch({ type: "edit_text", clipId, field, value, operationId: makeOperationId() })
                  }
                  onOwnershipChange={(clipId, ownership) =>
                    dispatch({ type: "edit_ownership", clipId, ownership, operationId: makeOperationId() })
                  }
                  onDurationChange={(sceneId, durationInFrames) =>
                    dispatch({ type: "edit_duration", sceneId, durationInFrames, operationId: makeOperationId() })
                  }
                >
                  <SceneMediaInspector document={state.draft} sceneId={state.selectedSceneId} />
                  {timeline ? <CaptionTextInspector document={timeline} selectedSceneId={state.selectedSceneId} disabled={upgrading} compact onOperation={(operation) => dispatch({ type: "commit_timeline_operation", operation })} /> : <section className="studio-caption-summary" aria-label="Captions"><h3>Captions</h3><p>No editable captions in this document.</p><button className="studio-style-trigger" type="button" disabled>Caption style unavailable</button></section>}
                </Inspector>
                {timeline && viewport !== "phone" ? (
                  <>
                    <details className="studio-audio-settings"><summary>Scene audio</summary>
                    <SceneAudioInspector
                      document={timeline}
                      selectedSceneId={state.selectedSceneId}
                      assets={Object.values(state.assets)}
                      loadFailed={simpleAssetsFailed}
                      disabled={upgrading}
                      onOperation={commitSceneOperation}
                    />
                    </details>
                  </>
                ) : null}
              </div>
            )}
          </div>
          {story && timeline && editing ? (
            <div className="col-span-full border-t border-hairline bg-bg px-4 py-3">
              <BeatStrip
                beats={beats}
                fps={timeline.canvas.fps}
                totalFrames={timeline.canvas.duration_in_frames}
                selected={shownBeat?.id ?? null}
                onSelect={selectBeat}
                document={timeline}
                previews={previewSources}
                onDropMaterial={(beatId, data) => void dropMaterial(beatId, data)}
                addable={[...addable]}
                onAddBeat={addBeat}
                voiced={voicedBeats}
                stale={staleBeats}
                variant={compact ? "chips" : "tiles"}
              />
            </div>
          ) : null}
        </div>
        {renderClient ? (
          <div className="contents" hidden={job !== "render"}>
            <RenderPanel
              client={renderClient}
              projectId={projectId}
              documentId={documentId}
              // The saved revision, never the draft: an unsaved or conflicted
              // document cannot be rendered, and the panel's gate explains why.
              documentRevision={base.revision}
              documentTitle={documentTitle}
              canvas={base.canvas}
              // The template the saved document carries, not one the UI assumes.
              templateId={base.template.template_id}
              templateVersion={base.template.version}
              facts={{ saveStatus, online: !state.isOffline }}
              monitorOnly={viewport === "phone"}
              sceneOrder={[...base.scenes]
                .sort((a, b) => a.start_frame - b.start_frame)
                .map((scene) => scene.scene_id)}
              onResolveImports={onResolveImports}
              // The saved revision is what a render reads, so its text and its
              // structure are what decide whether it can be rendered at all.
              validation={{
                textValid: hasValidText(base),
                blockingIssues: isTimelineDocument(base) ? timelineIssues(base).length : 0,
              }}
            />
          </div>
        ) : (
          <p role="status" hidden={job !== "render"} className="px-4 py-3 text-sm text-muted-foreground">
            Rendering is not available in this Studio session. Your draft is unaffected.
          </p>
        )}
      </div>
    </section>
  );
}

export function GuidedStudio(props: Props) {
  const { client, projectId, documentId } = props;
  const [document, setDocument] = useState<EditDocument | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setDocument(null);
    setFailed(false);
    void client
      .getEditDocument(projectId, documentId)
      .then((value) => active && setDocument(value))
      .catch(() => active && setFailed(true));
    return () => { active = false; };
  }, [attempt, client, documentId, projectId]);

  if (failed) {
    return (
      <section className="flex flex-1 flex-col items-center justify-center gap-3 p-6" aria-label="Guided Studio">
        <div role="alert" className="text-center text-sm">
          <p>Could not load Studio. Check your connection and try again.</p>
        </div>
        <button type="button" className={toolbarButton} onClick={() => setAttempt((value) => value + 1)}>Retry</button>
        <button type="button" className={toolbarButton} onClick={props.onBack}>Back</button>
      </section>
    );
  }
  if (!document) return <p className="p-6 text-sm text-muted-foreground">Loading Studio…</p>;
  return <Editor key={document.revision} {...props} document={document} />;
}
