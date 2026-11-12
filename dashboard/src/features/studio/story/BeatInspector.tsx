import { BEAT_MOVE_PRESETS, movePreset } from "../move_presets";
import { useEffect, useId, useState, type Dispatch, type KeyboardEvent } from "react";
import { ArrowDown, ArrowUp, Plus, TriangleAlert, X } from "lucide-react";
import { headingFitChars } from "@thoth/remotion-composition";

import type { EditDocumentOperation, EditDocumentV2, EditorAsset, StudioImportItem, StudioMaterials } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

import { reasonText } from "@/features/workflows/OpenInStudio";

import { useContextMenu, type MenuEntry } from "@/components/ContextMenu";
import type { EditorAction } from "../editor_state";
import { ReplaceMediaDialog } from "../ReplaceMediaDialog";
import { Switch } from "../StudioSwitch";
import { clipLabel, materialRowLabel } from "../studio_labels";
import { ROLE_BEAT, beatOwnFrames, type Beat } from "./story_beats";
import {
  addMaterialToBeat,
  longestReading,
  presetY,
  removeFromBeat,
  setClipSeconds,
  setEmphasis,
  setMotion,
  setPositionPreset,
  swapClips,
  type Motion,
  type PositionPreset,
} from "./story_edits";

type Props = {
  beat: Beat;
  beats: Beat[];
  document: EditDocumentV2;
  inventory: StudioImportItem[];
  materials: StudioMaterials | null;
  dispatch: Dispatch<EditorAction>;
  /** The editor asset for one run material (spec §6.2); absent where the route is. */
  attachMaterial?: (itemId: string) => Promise<EditorAsset>;
  /** Exclude a missing material, as the import gate does; absent while the draft is unsaved. */
  onRemoveMissing?: (itemId: string) => Promise<void>;
  /** The beat has a narration voice: its cards share the voice's time (spec 2026-11-01). */
  narrated?: boolean;
  /** Right-click menu (spec 2026-11-08 §5.2): the preview plays from a frame; a clip opens in the Timeline. */
  onPlayFrom?: (frame: number) => void;
  onShowInTimeline?: (clipId: string) => void;
  /** Replace media: the assets on offer and their names. */
  replaceAssets?: EditorAsset[];
  assetName?: (asset: EditorAsset) => string;
  /** Changes when the beat strip asks to add from materials; opens the picker. */
  pickRequest?: number;
  /** Called once the request opened the picker, so a later remount does not open it again. */
  onPickHandled?: () => void;
};

/** A material that can stand in for a missing one (spec §9: "Use profile card"). */
const ALTERNATIVE: Partial<Record<string, string>> = { profile_page: "profile_card" };

type Clip = NonNullable<EditDocumentV2["clips"]>[number];
const CARD_BEATS = new Set(["evidence", "reactions"]);
const PRESETS: PositionPreset[] = ["top", "middle", "lower"];
const HEADING_SLOT = { top: "title_top", middle: "title", lower: "title_lower", card: "card" } as const;
type HeadingPlace = keyof typeof HEADING_SLOT;
/** Style B's narrator card joins the three places (spec 2026-11-09, 3.6). */
const HEADING_PLACES: HeadingPlace[] = ["top", "middle", "lower", "card"];
/** Any older slot draws mid-frame, so it reads as Middle. */
const headingPreset = (slot: string): HeadingPlace =>
  slot === "title_top" ? "top" : slot === "title_lower" ? "lower" : slot === "card" ? "card" : "middle";
const MOTIONS: Motion[] = ["none", "slow_zoom", "pan"];
const section = "flex flex-col gap-2 border-t border-hairline pt-3";
const heading = "text-xs font-medium tracking-wide text-muted-ink uppercase";
const choice =
  "rounded-md border border-hairline px-2.5 py-1 text-[13px] text-muted-ink aria-[pressed=true]:border-copper aria-[pressed=true]:text-ink focus-visible:outline-2 focus-visible:outline-copper";
const field = "h-9 w-24 rounded-md border border-hairline bg-well px-2 text-sm text-ink focus-visible:outline-2 focus-visible:outline-copper";

type VideoOf = Extract<Clip, { kind: "video" }>;
const newOperationId = () => `op_${crypto.randomUUID()}`;

/**
 * Background, Dim and the moves that need no playhead, for every card of a beat at once (spec
 * 2026-11-09, 3.7). Marks are a Timeline tool; the beat names the cards that have them.
 */
function BeatEffects({
  clips,
  fps,
  commit,
  label,
}: {
  clips: VideoOf[];
  fps: number;
  commit: (operations: EditDocumentOperation[]) => unknown;
  label: (clip: Clip) => string;
}) {
  const { t } = useLocale();
  const dimId = useId();
  const stored = Math.round((clips[0]?.dim ?? 0) * 100);
  const [dim, setDim] = useState(stored);
  useEffect(() => setDim(stored), [stored]);
  const each = (make: (clip: VideoOf) => EditDocumentOperation) => commit(clips.map(make));
  const commitDim = () => {
    if (dim !== stored) each((clip) => ({ kind: "set_clip_dim", operation_id: newOperationId(), clip_id: clip.clip_id, dim: dim / 100 }));
  };
  const marked = clips.filter((clip) => (clip.emphasis?.marks?.length ?? 0) > 0);
  return (
    <>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("studio.effects.background")}>
        {(["none", "blur_fill"] as const).map((background) => (
          <button
            key={background}
            type="button"
            className={choice}
            aria-pressed={clips.every((clip) => (clip.background ?? "none") === background)}
            onClick={() =>
              each((clip) => ({ kind: "set_clip_background", operation_id: newOperationId(), clip_id: clip.clip_id, background }))
            }
          >
            {t(`studio.effects.background.${background}`)}
          </button>
        ))}
      </div>
      <label htmlFor={dimId} className="flex items-center justify-between gap-2 text-xs text-muted-ink">
        {t("studio.effects.dim")}
        <input
          id={dimId}
          type="range"
          min={0}
          max={80}
          step={5}
          value={dim}
          aria-valuetext={`${dim}%`}
          onChange={(event) => setDim(Number(event.target.value))}
          onPointerUp={commitDim}
          onKeyUp={commitDim}
          onBlur={commitDim}
        />
      </label>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("studio.effects.moves")}>
        {BEAT_MOVE_PRESETS.map((kind) => (
          <button
            key={kind}
            type="button"
            className={choice}
            onClick={() =>
              each((clip) => ({
                kind: "set_clip_moves",
                operation_id: newOperationId(),
                clip_id: clip.clip_id,
                moves: movePreset(kind, clip.duration_in_frames, fps),
              }))
            }
          >
            {t(`studio.effects.preset.${kind}`)}
          </button>
        ))}
      </div>
      {marked.length ? (
        <p className="text-xs text-muted-ink">{t("studio.story.timelineMarks", { names: marked.map(label).join(", ") })}</p>
      ) : null}
    </>
  );
}

/** Spec 2026-10-27 §9: the selected beat's cards, timing, position, motion and emphasis. */
export function BeatInspector({
  beat,
  beats,
  document,
  inventory,
  materials,
  dispatch,
  attachMaterial,
  onRemoveMissing,
  narrated = false,
  onPlayFrom,
  onShowInTimeline,
  replaceAssets,
  assetName,
  pickRequest,
  onPickHandled,
}: Props) {
  const { t, plural } = useLocale();
  const [picking, setPicking] = useState(false);
  const [addFailed, setAddFailed] = useState(false);
  const [removeFailed, setRemoveFailed] = useState(false);
  const menu = useContextMenu();
  const [replacing, setReplacing] = useState<string | null>(null);
  useEffect(() => {
    if (!pickRequest) return;
    setPicking(true);
    onPickHandled?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one opening per request.
  }, [pickRequest]);
  const fps = document.canvas.fps;
  const commit = (operations: EditDocumentOperation[]) =>
    operations.length && dispatch({ type: "commit_operations", operations });
  const seconds = (frames: number) => t("studio.story.seconds", { seconds: (frames / fps).toFixed(1) });

  const clips = beat.clipIds
    .map((id) => (document.clips ?? []).find((clip) => clip.clip_id === id))
    .filter((clip): clip is Clip => Boolean(clip));
  // Kind and source, never an id (spec 2026-11-01, Studio shell v2).
  const label = (clip: Clip) => clipLabel(clip, { document, materials, t, inventory });
  const cards = CARD_BEATS.has(beat.id) ? clips.filter((clip) => clip.kind === "video") : [];
  const cardIds = cards.map((clip) => clip.clip_id);
  // Photos in the Footage beat may move too (operator, 2026-10-28); its videos already do.
  const kindOf = new Map((document.asset_refs ?? []).map((ref) => [ref.asset_id, ref.kind]));
  const photos =
    beat.id === "footage"
      ? clips.filter((clip) => clip.kind === "video" && kindOf.get(clip.asset_id) === "image")
      : [];
  const moving = cards.length ? cards : photos;
  const text = beat.id === "hook" || beat.id === "outro" ? clips.find((clip) => clip.kind === "text") : undefined;
  // A credit keeps its lower corner: it is no heading (2026-11-12).
  const headingClip = clips.find(
    (clip): clip is Extract<(typeof clips)[number], { kind: "text" }> => clip.kind === "text" && clip.style_slot !== "credit",
  );
  const reading = longestReading(beat, inventory);

  // Spec 2026-11-08 §5.2: the Shown item's own edits, the same helpers the buttons below use.
  const kindOfAsset = (assetId: string) => (document.asset_refs ?? []).find((ref) => ref.asset_id === assetId)?.kind;
  const shownMenu = (clip: Clip, index: number): MenuEntry[] => {
    const unavailable = t("studio.menu.reason.unavailable");
    const earlier = index > 0 ? swapClips(document, clips[index - 1]!.clip_id, clip.clip_id) : [];
    const later = index < clips.length - 1 ? swapClips(document, clip.clip_id, clips[index + 1]!.clip_id) : [];
    const media = clip.kind === "video" && "asset_id" in clip;
    const entries: MenuEntry[] = [
      { kind: "item", id: "earlier", label: t("studio.menu.moveEarlier"), disabled: !earlier.length, reason: t("studio.menu.reason.first"), onSelect: () => commit(earlier) },
      { kind: "item", id: "later", label: t("studio.menu.moveLater"), disabled: !later.length, reason: t("studio.menu.reason.last"), onSelect: () => commit(later) },
      { kind: "item", id: "remove", label: t("studio.menu.removeFromBeat"), onSelect: () => commit([removeFromBeat(clip.clip_id)]) },
      {
        kind: "item",
        id: "replace",
        label: t("studio.menu.replaceMedia"),
        disabled: !media || !replaceAssets,
        reason: !media ? t("studio.menu.reason.notVideo") : unavailable,
        onSelect: () => setReplacing(clip.clip_id),
      },
    ];
    if (moving.some((entry) => entry.clip_id === clip.clip_id)) {
      entries.push({
        kind: "group",
        id: "position",
        label: t("studio.inspector.position"),
        entries: PRESETS.map((preset) => ({
          kind: "item" as const,
          id: `position-${preset}`,
          label: t(`studio.inspector.position.${preset}`),
          onSelect: () => commit(setPositionPreset(document, [clip.clip_id], preset)),
        })),
      });
    }
    if (cards.some((entry) => entry.clip_id === clip.clip_id)) {
      const lit = "emphasis" in clip && Boolean(clip.emphasis?.highlight);
      const pointed = "emphasis" in clip && Boolean(clip.emphasis?.arrow);
      entries.push({
        kind: "group",
        id: "emphasis",
        label: t("studio.inspector.emphasis"),
        entries: [
          { kind: "item", id: "highlight", label: t("studio.inspector.emphasis.highlight"), onSelect: () => commit(setEmphasis([clip.clip_id], !lit, pointed)) },
          { kind: "item", id: "arrow", label: t("studio.inspector.emphasis.arrow"), onSelect: () => commit(setEmphasis([clip.clip_id], lit, !pointed)) },
        ],
      });
    }
    entries.push(
      { kind: "item", id: "play", label: t("studio.menu.playFromHere"), disabled: !onPlayFrom, reason: unavailable, onSelect: () => onPlayFrom?.(clip.from_frame) },
      { kind: "item", id: "timeline", label: t("studio.menu.showInTimeline"), disabled: !onShowInTimeline, reason: unavailable, onSelect: () => onShowInTimeline?.(clip.clip_id) },
    );
    return entries;
  };
  const replacingClip = clips.find((clip) => clip.clip_id === replacing);
  const replacingAsset = replacingClip && "asset_id" in replacingClip ? replacingClip.asset_id : undefined;

  // The same seconds as the beat's tile: a beat that spans others does not count their time.
  const ownFrames = beatOwnFrames(beats, document.canvas.duration_in_frames).get(beat.id) ?? beat.durationInFrames;
  const header = [
    t("studio.inspector.beatOf", { index: beats.indexOf(beat) + 1, count: beats.length }),
    seconds(ownFrames),
    plural("studio.inspector.materials", clips.length),
    ...(beat.missing.length ? [t("studio.story.missing", { count: beat.missing.length })] : []),
  ].join(" · ");

  const shownAssets = new Set(clips.map((clip) => ("asset_id" in clip ? clip.asset_id : null)));
  const candidates = (materials?.items ?? []).filter(
    (item) =>
      item.media_kind !== "none" &&
      // Without the run's Content Set only materials that already have an asset can be added.
      (materials?.provenance_available || item.asset_id) &&
      item.role &&
      ROLE_BEAT[item.role] === beat.id &&
      !beat.clipIds.includes(`clip_${item.item_id}`) &&
      !shownAssets.has(item.asset_id ?? null),
  );
  const add = async (itemId: string, role: NonNullable<StudioImportItem["role"]>) => {
    if (!attachMaterial) return;
    setAddFailed(false);
    try {
      const asset = await attachMaterial(itemId);
      dispatch({ type: "assets_loaded", assets: [asset], replace: false });
      commit(addMaterialToBeat(document, beat, asset, role));
      setPicking(false);
    } catch {
      setAddFailed(true);
    }
  };

  const onCommitKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") event.currentTarget.blur();
  };
  const allCards = <T,>(read: (clip: Clip) => T, value: T) => cards.length > 0 && cards.every((clip) => read(clip) === value);
  const placement = (clip: Clip) => ("position" in clip ? clip.position?.y ?? 0 : 0);
  const motionOf = (clip: Clip) => ("motion" in clip ? clip.motion ?? "none" : "none");
  const highlight = allCards((clip) => ("emphasis" in clip ? Boolean(clip.emphasis?.highlight) : false), true);
  const arrow = allCards((clip) => ("emphasis" in clip ? Boolean(clip.emphasis?.arrow) : false), true);

  return (
    <div className="flex flex-col gap-3 p-4" key={beat.id}>
      <header className="flex flex-col gap-1">
        <h2 className="text-[17px] font-semibold text-ink">{t(`studio.story.beat.${beat.id}`)}</h2>
        <p className="font-mono text-xs text-muted-ink">{header}</p>
      </header>

      {beat.missing.map((entry) => {
        const stand = (materials?.items ?? []).find(
          (item) => entry.role && item.role === ALTERNATIVE[entry.role] && !beat.clipIds.includes(`clip_${item.item_id}`),
        );
        return (
          <div key={entry.item_id} role="alert" className="flex flex-col gap-2 rounded-md border border-status-failed/50 bg-status-failed/10 p-3 text-sm text-ink">
            <p className="font-medium">{t("studio.inspector.missingTitle", { label: entry.label })}</p>
            {entry.reason ? <p className="text-xs text-muted-ink">{reasonText(t, entry.label, entry.reason)}</p> : null}
            <div className="flex flex-wrap gap-2">
              {stand && attachMaterial ? (
                <button type="button" className={choice} onClick={() => void add(stand.item_id, stand.role!)}>
                  {t("studio.inspector.useProfileCard")}
                </button>
              ) : null}
              <button
                type="button"
                className={choice}
                disabled={!onRemoveMissing}
                onClick={async () => {
                  setRemoveFailed(false);
                  try {
                    await onRemoveMissing?.(entry.item_id);
                  } catch {
                    setRemoveFailed(true);
                  }
                }}
              >
                {t("studio.inspector.removeMissing")}
              </button>
            </div>
            {!onRemoveMissing ? <p className="text-xs text-muted-ink">{t("studio.inspector.removeMissingNote")}</p> : null}
            {removeFailed ? <p className="text-xs text-status-failed">{t("studio.inspector.removeFailed")}</p> : null}
          </div>
        );
      })}

      {menu.element}
      {replacingClip && replacingAsset && replaceAssets ? (
        <ReplaceMediaDialog
          currentAssetId={replacingAsset}
          kind={kindOfAsset(replacingAsset) === "image" ? "image" : "video"}
          assets={replaceAssets}
          nameOf={(asset) => assetName?.(asset) ?? t(`studio.label.kind.${asset.kind}`)}
          onClose={() => setReplacing(null)}
          onReplace={(assetId) => {
            setReplacing(null);
            commit([{ kind: "replace_clip_asset", operation_id: `op_${crypto.randomUUID()}`, clip_id: replacingClip.clip_id, asset_id: assetId }]);
          }}
        />
      ) : null}
      <section aria-label={t("studio.inspector.shown")} className={section}>
        <h3 className={heading}>{t("studio.inspector.shown")}</h3>
        <ul className="flex flex-col gap-1">
          {clips.map((clip, index) => (
            <li
              key={clip.clip_id}
              {...menu.bind(() => shownMenu(clip, index))}
              className="flex items-center gap-1 rounded-md bg-surface px-2 py-1.5 text-sm text-ink"
            >
              <span className="min-w-0 flex-1 truncate">{label(clip)}</span>
              <IconButton
                label={t("studio.inspector.earlier", { label: label(clip) })}
                disabled={index === 0 || !swapClips(document, clips[index - 1]!.clip_id, clip.clip_id).length}
                onClick={() => commit(swapClips(document, clips[index - 1]!.clip_id, clip.clip_id))}
              >
                <ArrowUp size={14} />
              </IconButton>
              <IconButton
                label={t("studio.inspector.later", { label: label(clip) })}
                disabled={index === clips.length - 1 || !swapClips(document, clip.clip_id, clips[index + 1]!.clip_id).length}
                onClick={() => commit(swapClips(document, clip.clip_id, clips[index + 1]!.clip_id))}
              >
                <ArrowDown size={14} />
              </IconButton>
              <IconButton label={t("studio.inspector.remove", { label: label(clip) })} onClick={() => commit([removeFromBeat(clip.clip_id)])}>
                <X size={14} />
              </IconButton>
            </li>
          ))}
        </ul>
        {attachMaterial ? (
          <button
            type="button"
            aria-expanded={picking}
            onClick={() => setPicking((open) => !open)}
            className="inline-flex items-center gap-1 self-start text-[13px] text-copper hover:underline focus-visible:outline-2 focus-visible:outline-copper"
          >
            <Plus aria-hidden="true" size={14} /> {t("studio.inspector.add")}
          </button>
        ) : null}
        {picking ? (
          candidates.length ? (
            <ul role="listbox" aria-label={t("studio.inspector.add")} className="flex flex-col rounded-md border border-hairline bg-raised p-1">
              {candidates.map((item) => (
                <li
                  key={item.item_id}
                  role="option"
                  aria-selected={false}
                  tabIndex={0}
                  onClick={() => void add(item.item_id, item.role!)}
                  onKeyDown={(event) => event.key === "Enter" && void add(item.item_id, item.role!)}
                  className="cursor-pointer rounded px-2 py-1.5 text-sm text-ink hover:bg-surface focus-visible:outline-2 focus-visible:outline-copper"
                >
                  {materialRowLabel(item, t)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-ink">{t("studio.inspector.addNone")}</p>
          )
        ) : null}
        {addFailed ? <p role="alert" className="text-xs text-status-failed">{t("studio.inspector.addFailed")}</p> : null}
      </section>

      <section aria-label={t("studio.inspector.timing")} className={section}>
        <h3 className={heading}>{t("studio.inspector.timing")}</h3>
        {narrated && cards.length ? (
          <p className="text-sm text-muted-ink">{t("studio.inspector.followsVoice", { length: seconds(ownFrames) })}</p>
        ) : cards.length ? (
          <>
            <label className="flex items-center justify-between gap-2 text-sm text-ink">
              {t("studio.inspector.eachCard")}
              <input
                // Keyed by the stored value, so undo, Assist and a reload show the draft's own.
                key={Math.max(...cards.map((clip) => clip.duration_in_frames))}
                type="number"
                min={0.5}
                step={0.5}
                className={field}
                defaultValue={(Math.max(...cards.map((clip) => clip.duration_in_frames)) / fps).toFixed(1)}
                onKeyDown={onCommitKey}
                onBlur={(event) => {
                  const value = event.currentTarget.valueAsNumber;
                  if (value > 0) commit(setClipSeconds(document, cardIds, value));
                }}
              />
            </label>
            {reading != null ? (
              <p className="text-xs text-muted-ink">{t("studio.inspector.reading", { seconds: reading.toFixed(1) })}</p>
            ) : null}
          </>
        ) : text ? (
          <>
            <label className="flex flex-col gap-1 text-sm text-ink">
              {t("studio.inspector.text")}
              <input
                key={text.kind === "text" ? text.heading : ""}
                type="text"
                className={`${field} w-full`}
                defaultValue={text.kind === "text" ? text.heading : ""}
                onKeyDown={onCommitKey}
                onBlur={(event) => {
                  const value = event.currentTarget.value.trim();
                  if (text.kind === "text" && value && value !== text.heading) {
                    commit([{ kind: "replace_text", operation_id: `op_${crypto.randomUUID()}`, clip_id: text.clip_id, field: "heading", value }]);
                  }
                }}
              />
            </label>
            <label className="flex items-center justify-between gap-2 text-sm text-ink">
              {t("studio.inspector.length")}
              <input
                key={text.duration_in_frames}
                type="number"
                min={0.5}
                step={0.5}
                className={field}
                defaultValue={(text.duration_in_frames / fps).toFixed(1)}
                onKeyDown={onCommitKey}
                onBlur={(event) => {
                  const value = event.currentTarget.valueAsNumber;
                  if (value > 0 && Math.round(value * fps) !== text.duration_in_frames) {
                    commit(setClipSeconds(document, [text.clip_id], value));
                  }
                }}
              />
            </label>
          </>
        ) : (
          <p className="text-sm text-muted-ink">{t("studio.inspector.followsVideo", { length: seconds(ownFrames) })}</p>
        )}
      </section>

      {headingClip ? (
        <section role="group" aria-label={t("studio.inspector.headingPlace")} className={section}>
          <h3 className={heading}>{t("studio.inspector.headingPlace")}</h3>
          <div className="flex flex-wrap gap-1.5">
            {HEADING_PLACES.map((preset) => (
              <button
                key={preset}
                type="button"
                className={choice}
                aria-pressed={headingPreset(headingClip.style_slot) === preset}
                onClick={() => commit([{ kind: "set_text_place", operation_id: `op_${crypto.randomUUID()}`, clip_id: headingClip.clip_id, style_slot: HEADING_SLOT[preset] }])}
              >
                {t(`studio.inspector.position.${preset}`)}
              </button>
            ))}
          </div>
          {headingClip.heading.length > headingFitChars(document.canvas) ? (
            <p className="flex items-center gap-1.5 text-xs text-status-waiting">
              <TriangleAlert aria-hidden="true" size={14} />
              <span>{t("studio.inspector.tooLong", { count: headingClip.heading.length })}</span>
            </p>
          ) : null}
        </section>
      ) : null}
      {cards.length ? (
        <section role="group" aria-label={t("studio.inspector.position")} className={section}>
            <h3 className={heading}>{t("studio.inspector.position")}</h3>
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  className={choice}
                  aria-pressed={cards.length > 0 && cards.every((clip) => Math.abs(placement(clip) - presetY(document, clip, preset)) < 1e-6)}
                  onClick={() => commit(setPositionPreset(document, cardIds, preset))}
                >
                  {t(`studio.inspector.position.${preset}`)}
                </button>
              ))}
            </div>
            <p className="text-xs text-muted-ink">{t("studio.inspector.safeNote")}</p>
          </section>
      ) : null}
      {moving.length ? (
        <section role="group" aria-label={t("studio.inspector.motion")} className={section}>
          <h3 className={heading}>{t("studio.inspector.motion")}</h3>
          <div className="flex flex-wrap gap-1.5">
            {MOTIONS.map((motion) => (
              <button
                key={motion}
                type="button"
                className={choice}
                // Moves play over Motion, so a Motion choice replaces them and none reads as chosen meanwhile.
                aria-pressed={moving.every((clip) => motionOf(clip) === motion && !(clip as VideoOf).moves?.length)}
                onClick={() =>
                  commit([
                    ...setMotion(moving.map((clip) => clip.clip_id), motion),
                    ...moving
                      .filter((clip) => (clip as VideoOf).moves?.length)
                      .map((clip): EditDocumentOperation => ({ kind: "set_clip_moves", operation_id: newOperationId(), clip_id: clip.clip_id, moves: [] })),
                  ])
                }
              >
                {t(`studio.inspector.motion.${motion}`)}
              </button>
            ))}
          </div>
          <BeatEffects clips={moving as VideoOf[]} fps={fps} commit={commit} label={label} />
        </section>
      ) : null}
      {cards.length ? (
        <section role="group" aria-label={t("studio.inspector.emphasis")} className={section}>
          <h3 className={heading}>{t("studio.inspector.emphasis")}</h3>
          <Switch label={t("studio.inspector.emphasis.highlight")} checked={highlight} onChange={(on) => commit(setEmphasis(cardIds, on, arrow))} />
          <Switch label={t("studio.inspector.emphasis.arrow")} checked={arrow} onChange={(on) => commit(setEmphasis(cardIds, highlight, on))} />
        </section>
      ) : null}
    </div>
  );
}

function IconButton({ label, disabled, onClick, children }: { label: string; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="grid size-7 shrink-0 place-items-center rounded text-muted-ink hover:bg-raised hover:text-ink focus-visible:outline-2 focus-visible:outline-copper disabled:opacity-30"
    >
      {children}
    </button>
  );
}
