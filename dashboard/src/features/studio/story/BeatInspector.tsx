import { useState, type Dispatch, type KeyboardEvent } from "react";
import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";

import type { EditDocumentOperation, EditDocumentV2, EditorAsset, StudioImportItem, StudioMaterials } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

import type { EditorAction } from "../editor_state";
import { ROLE_BEAT, type Beat } from "./story_beats";
import {
  PRESET_Y,
  addMaterialToBeat,
  longestReading,
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
};

type Clip = NonNullable<EditDocumentV2["clips"]>[number];
const CARD_BEATS = new Set(["evidence", "reactions"]);
const PRESETS: PositionPreset[] = ["top", "middle", "lower"];
const MOTIONS: Motion[] = ["none", "slow_zoom", "pan"];
const section = "flex flex-col gap-2 border-t border-hairline pt-3";
const heading = "text-xs font-medium tracking-wide text-muted-ink uppercase";
const choice =
  "rounded-md border border-hairline px-2.5 py-1 text-[13px] text-muted-ink aria-[pressed=true]:border-copper aria-[pressed=true]:text-ink focus-visible:outline-2 focus-visible:outline-copper";
const field = "h-9 w-24 rounded-md border border-hairline bg-well px-2 text-sm text-ink focus-visible:outline-2 focus-visible:outline-copper";

/** Spec 2026-10-27 §9: the selected beat's cards, timing, position, motion and emphasis. */
export function BeatInspector({ beat, beats, document, inventory, materials, dispatch, attachMaterial }: Props) {
  const { t } = useLocale();
  const [picking, setPicking] = useState(false);
  const [addFailed, setAddFailed] = useState(false);
  const fps = document.canvas.fps;
  const commit = (operations: EditDocumentOperation[]) =>
    operations.length && dispatch({ type: "commit_operations", operations });
  const seconds = (frames: number) => t("studio.story.seconds", { seconds: (frames / fps).toFixed(1) });

  const clips = beat.clipIds
    .map((id) => (document.clips ?? []).find((clip) => clip.clip_id === id))
    .filter((clip): clip is Clip => Boolean(clip));
  const items = new Map(inventory.map((entry) => [`clip_${entry.item_id}`, entry]));
  const labelled = new Map((materials?.items ?? []).map((item) => [`clip_${item.item_id}`, item.label]));
  const label = (clip: Clip) =>
    clip.kind === "text" ? clip.heading : labelled.get(clip.clip_id) ?? items.get(clip.clip_id)?.label ?? ("asset_id" in clip ? clip.asset_id : clip.clip_id);
  const cards = CARD_BEATS.has(beat.id) ? clips.filter((clip) => clip.kind === "video") : [];
  const cardIds = cards.map((clip) => clip.clip_id);
  const text = beat.id === "hook" || beat.id === "outro" ? clips.find((clip) => clip.kind === "text") : undefined;
  const reading = longestReading(beat, inventory);

  const header = [
    t("studio.inspector.beatOf", { index: beats.indexOf(beat) + 1, count: beats.length }),
    seconds(beat.durationInFrames),
    t("studio.inspector.materials", { count: clips.length }),
    ...(beat.missing.length ? [t("studio.story.missing", { count: beat.missing.length })] : []),
  ].join(" · ");

  const shownAssets = new Set(clips.map((clip) => ("asset_id" in clip ? clip.asset_id : null)));
  const candidates = (materials?.items ?? []).filter(
    (item) =>
      item.media_kind !== "none" &&
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
      commit([addMaterialToBeat(document, beat, asset, role)]);
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

      <section aria-label={t("studio.inspector.shown")} className={section}>
        <h3 className={heading}>{t("studio.inspector.shown")}</h3>
        <ul className="flex flex-col gap-1">
          {clips.map((clip, index) => (
            <li key={clip.clip_id} className="flex items-center gap-1 rounded-md bg-surface px-2 py-1.5 text-sm text-ink">
              <span className="min-w-0 flex-1 truncate">{label(clip)}</span>
              <IconButton
                label={t("studio.inspector.earlier", { label: label(clip) })}
                disabled={index === 0}
                onClick={() => commit(swapClips(document, clips[index - 1]!.clip_id, clip.clip_id))}
              >
                <ArrowUp size={14} />
              </IconButton>
              <IconButton
                label={t("studio.inspector.later", { label: label(clip) })}
                disabled={index === clips.length - 1}
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
                  {item.label}
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
        {cards.length ? (
          <>
            <label className="flex items-center justify-between gap-2 text-sm text-ink">
              {t("studio.inspector.eachCard")}
              <input
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
          <p className="text-sm text-muted-ink">{t("studio.inspector.followsVideo", { length: seconds(beat.durationInFrames) })}</p>
        )}
      </section>

      {cards.length ? (
        <>
          <section role="group" aria-label={t("studio.inspector.position")} className={section}>
            <h3 className={heading}>{t("studio.inspector.position")}</h3>
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  className={choice}
                  aria-pressed={allCards(placement, PRESET_Y[preset])}
                  onClick={() => commit(setPositionPreset(document, cardIds, preset))}
                >
                  {t(`studio.inspector.position.${preset}`)}
                </button>
              ))}
            </div>
            <p className="text-xs text-muted-ink">{t("studio.inspector.safeNote")}</p>
          </section>
          <section role="group" aria-label={t("studio.inspector.motion")} className={section}>
            <h3 className={heading}>{t("studio.inspector.motion")}</h3>
            <div className="flex flex-wrap gap-1.5">
              {MOTIONS.map((motion) => (
                <button
                  key={motion}
                  type="button"
                  className={choice}
                  aria-pressed={allCards(motionOf, motion)}
                  onClick={() => commit(setMotion(cardIds, motion))}
                >
                  {t(`studio.inspector.motion.${motion}`)}
                </button>
              ))}
            </div>
          </section>
          <section role="group" aria-label={t("studio.inspector.emphasis")} className={section}>
            <h3 className={heading}>{t("studio.inspector.emphasis")}</h3>
            <Switch label={t("studio.inspector.emphasis.highlight")} checked={highlight} onChange={(on) => commit(setEmphasis(cardIds, on, arrow))} />
            <Switch label={t("studio.inspector.emphasis.arrow")} checked={arrow} onChange={(on) => commit(setEmphasis(cardIds, highlight, on))} />
          </section>
        </>
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

function Switch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (on: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex items-center justify-between rounded-md px-1 py-1 text-sm text-ink focus-visible:outline-2 focus-visible:outline-copper"
    >
      {label}
      <span aria-hidden="true" className={`flex h-5 w-9 items-center rounded-full p-0.5 ${checked ? "bg-copper" : "bg-well"}`}>
        <span className={`size-4 rounded-full bg-ink transition-transform ${checked ? "translate-x-4" : ""}`} />
      </span>
    </button>
  );
}
