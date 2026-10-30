import { useId, type ReactNode } from "react";

import type { EditDocumentOperation, EditDocumentV2 } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";
import { setPositionPreset, type PositionPreset } from "./story/story_edits";
import { clipLabel } from "./TimelineClip";
import { formatTimecode } from "./timeline_domain";

type Props = {
  document: EditDocumentV2;
  selectedClipId: string;
  selectedTrackId: string;
  onOperation: (operation: EditDocumentOperation) => void;
};

const field = "flex items-center justify-between gap-2 text-xs text-muted-ink";
const input =
  "w-28 rounded-md border border-hairline bg-well px-2 py-1 font-mono text-xs text-ink focus-visible:outline-2 focus-visible:outline-copper disabled:cursor-not-allowed disabled:opacity-40";
const button =
  "rounded-md border border-hairline px-2 py-1 text-xs text-ink transition-colors hover:bg-raised focus-visible:outline-2 focus-visible:outline-copper disabled:opacity-40";

const newId = () => `op_${crypto.randomUUID()}`;

/** Shown wherever a persisted optional field carries no value. */
const NOT_SET = "—";

const PRESETS: PositionPreset[] = ["top", "middle", "lower"];

/** Omit distributed over the operation union, so each member keeps its own fields. */
type OperationDraft = EditDocumentOperation extends infer T
  ? T extends EditDocumentOperation
    ? Omit<T, "operation_id">
    : never
  : never;

/** One titled group of fields, like the TIMING, TRANSFORM and AUDIO blocks of the design. */
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section role="group" aria-label={title} className="space-y-2 border-t border-hairline pt-3">
      <h3 className="font-mono text-[0.7rem] uppercase tracking-[0.16em] text-faint">{title}</h3>
      {children}
    </section>
  );
}

export function TimelineInspector({
  document,
  selectedClipId,
  selectedTrackId,
  onOperation,
}: Props) {
  const { t, plural } = useLocale();
  const ids = {
    start: useId(),
    end: useId(),
    volume: useId(),
    hidden: useId(),
    muted: useId(),
    locked: useId(),
    ownership: useId(),
    fit: useId(),
    crop: useId(),
    position: useId(),
    fadeIn: useId(),
    fadeOut: useId(),
    overlayPreset: useId(),
    overlayText: useId(),
    overlayAccent: useId(),
    captionStyle: useId(),
    captionCues: useId(),
  };
  const fps = document.canvas.fps;
  const clip = document.clips?.find((candidate) => candidate.clip_id === selectedClipId);
  const track = document.tracks.find(
    (candidate) => candidate.track_id === (clip?.track_id ?? selectedTrackId),
  );
  const frozen = clip?.locked === true || track?.locked === true;
  /** A persisted field D1 stores but has no operation to change. */
  const readOnlyField = (id: string, label: string, value: string) => (
    <div className={field} key={id}>
      <label htmlFor={id}>{label}</label>
      <input id={id} className={input} value={value} readOnly disabled />
    </div>
  );
  const checkbox = (
    id: string,
    label: string,
    checked: boolean,
    disabled: boolean,
    onChange: (on: boolean) => void,
  ) => (
    <div className={field}>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="checkbox"
        className="accent-copper"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
    </div>
  );

  // Every control emits the same typed operation the timeline gestures emit.
  const emit = (operation: OperationDraft) =>
    onOperation({ ...operation, operation_id: newId() } as EditDocumentOperation);

  return (
    <aside
      className="min-h-0 space-y-3 overflow-auto border-l border-hairline bg-surface p-4"
      aria-label={t("studio.timeline.inspector")}
    >
      {clip ? (
        <>
          <header>
            <h2 className="truncate text-sm font-semibold text-ink">{clipLabel(t, clip)}</h2>
            {track ? (
              <p className="text-xs text-muted-ink">{t("studio.timeline.track", { track: track.label })}</p>
            ) : null}
          </header>

          <Section title={t("studio.timeline.section.timing")}>
            <div className={field}>
              <label htmlFor={ids.start}>{t("studio.timeline.startFrame")}</label>
              <span className="ml-auto font-mono text-faint">{formatTimecode(clip.from_frame, fps)}</span>
              <input
                id={ids.start}
                type="number"
                className={input}
                min={0}
                value={clip.from_frame}
                disabled={frozen}
                onChange={(event) =>
                  emit({ kind: "trim_clip_start", clip_id: clip.clip_id, from_frame: Number(event.target.value) })
                }
              />
            </div>
            <div className={field}>
              <label htmlFor={ids.end}>{t("studio.timeline.endFrame")}</label>
              <span className="ml-auto font-mono text-faint">
                {formatTimecode(clip.from_frame + clip.duration_in_frames, fps)}
              </span>
              <input
                id={ids.end}
                type="number"
                className={input}
                min={1}
                value={clip.from_frame + clip.duration_in_frames}
                disabled={frozen}
                onChange={(event) =>
                  emit({ kind: "trim_clip_end", clip_id: clip.clip_id, end_frame: Number(event.target.value) })
                }
              />
            </div>
          </Section>

          {clip.kind === "video" ? (
            <Section title={t("studio.timeline.section.transform")}>
              {clip.position ? (
                <div className="flex gap-1">
                  {PRESETS.map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      className={button}
                      disabled={frozen}
                      onClick={() => setPositionPreset(document, [clip.clip_id], preset).forEach(onOperation)}
                    >
                      {t(`studio.inspector.position.${preset}`)}
                    </button>
                  ))}
                </div>
              ) : null}
              {readOnlyField(ids.fit, t("studio.timeline.fit"), clip.fit)}
              {readOnlyField(
                ids.crop,
                t("studio.timeline.crop"),
                clip.crop ? [clip.crop.left, clip.crop.top, clip.crop.width, clip.crop.height].join(", ") : NOT_SET,
              )}
              {readOnlyField(
                ids.position,
                t("studio.timeline.position"),
                clip.position ? `${clip.position.x}, ${clip.position.y} ×${clip.position.scale}` : NOT_SET,
              )}
              {clip.blur_regions?.length ? (
                // Detected subtitles arrive switched off: muting and blurring the speech leaves
                // the viewer neither the words nor the text until narration replaces it.
                <div className={field}>
                  <span>{plural("studio.timeline.subtitles", clip.blur_regions.length)}</span>
                  {clip.blur_enabled ? (
                    <button
                      type="button"
                      className={button}
                      disabled={frozen}
                      onClick={() => emit({ kind: "set_clip_blur", clip_id: clip.clip_id, blur_enabled: false })}
                    >
                      {t("studio.timeline.removeBlur")}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className={button}
                      disabled={frozen}
                      onClick={() => {
                        emit({ kind: "set_clip_blur", clip_id: clip.clip_id, blur_enabled: true });
                        emit({ kind: "set_track_muted", track_id: clip.track_id, muted: true });
                      }}
                    >
                      {t("studio.timeline.blurAndMute")}
                    </button>
                  )}
                </div>
              ) : null}
            </Section>
          ) : null}

          {clip.kind === "audio" ? (
            <Section title={t("studio.timeline.section.audio")}>
              <div className={field}>
                <label htmlFor={ids.volume}>{t("studio.timeline.volume")}</label>
                <input
                  id={ids.volume}
                  type="range"
                  className="w-28 accent-copper"
                  min={0}
                  max={1}
                  step={0.1}
                  value={clip.volume ?? 1}
                  disabled={frozen}
                  onChange={(event) =>
                    emit({ kind: "set_clip_volume", clip_id: clip.clip_id, volume: Number(event.target.value) })
                  }
                />
              </div>
              {readOnlyField(ids.fadeIn, t("studio.timeline.fadeIn"), String(clip.fade_in_frames ?? 0))}
              {readOnlyField(ids.fadeOut, t("studio.timeline.fadeOut"), String(clip.fade_out_frames ?? 0))}
            </Section>
          ) : clip.kind !== "video" ? (
            // A video sounds through its track mute; every other clip has no sound of its own.
            <Section title={t("studio.timeline.section.audio")}>
              <p className="text-xs text-faint">{t("studio.timeline.noAudio")}</p>
            </Section>
          ) : null}

          {clip.kind === "overlay" ? (
            <Section title={t("studio.timeline.section.content")}>
              {readOnlyField(ids.overlayPreset, t("studio.timeline.overlayPreset"), clip.preset_id)}
              {readOnlyField(ids.overlayText, t("studio.timeline.overlayText"), clip.parameters?.text ?? NOT_SET)}
              {readOnlyField(
                ids.overlayAccent,
                t("studio.timeline.overlayAccent"),
                clip.parameters?.accent_slot ?? NOT_SET,
              )}
            </Section>
          ) : null}
          {clip.kind === "caption" ? (
            <Section title={t("studio.timeline.section.content")}>
              {readOnlyField(ids.captionStyle, t("studio.timeline.captionStyle"), clip.style_slot)}
              {readOnlyField(
                ids.captionCues,
                t("studio.timeline.captionCues"),
                clip.cues.length
                  ? clip.cues
                      .map((cue) => `${cue.from_frame}–${cue.from_frame + cue.duration_in_frames} ${cue.text}`)
                      .join(" · ")
                  : NOT_SET,
              )}
            </Section>
          ) : null}

          <Section title={t("studio.timeline.section.clip")}>
            {checkbox(ids.hidden, t("studio.timeline.hidden"), clip.hidden === true, frozen, (hidden) =>
              emit({ kind: "set_clip_hidden", clip_id: clip.clip_id, hidden }),
            )}
            {checkbox(ids.locked, t("studio.timeline.lockedField"), clip.locked === true, false, (locked) =>
              emit({ kind: "set_clip_locked", clip_id: clip.clip_id, locked }),
            )}
            <div className={field}>
              <label htmlFor={ids.ownership}>{t("studio.timeline.ownership")}</label>
              <select
                id={ids.ownership}
                className="rounded-md border border-hairline bg-well px-2 py-1 text-xs text-ink focus-visible:outline-2 focus-visible:outline-copper disabled:opacity-40"
                value={clip.ownership}
                disabled={frozen}
                onChange={(event) =>
                  emit({
                    kind: "set_ownership",
                    clip_id: clip.clip_id,
                    ownership: event.target.value as "ai_managed" | "user_edited" | "locked",
                  })
                }
              >
                {(["ai_managed", "user_edited", "locked"] as const).map((value) => (
                  <option key={value} value={value}>
                    {t(`studio.timeline.ownership.${value}`)}
                  </option>
                ))}
              </select>
            </div>
          </Section>
        </>
      ) : track ? (
        <>
          <header>
            <h2 className="truncate text-sm font-semibold text-ink">{track.label}</h2>
            <p className="font-mono text-xs text-muted-ink">{track.kind}</p>
          </header>
          <Section title={t("studio.timeline.section.track")}>
            {checkbox(ids.hidden, t("studio.timeline.hidden"), track.hidden === true, track.locked === true, (hidden) =>
              emit({ kind: "set_track_visibility", track_id: track.track_id, hidden }),
            )}
            {checkbox(ids.muted, t("studio.timeline.muted"), track.muted === true, track.locked === true, (muted) =>
              emit({ kind: "set_track_muted", track_id: track.track_id, muted }),
            )}
            {checkbox(ids.locked, t("studio.timeline.lockedField"), track.locked === true, false, (locked) =>
              emit({ kind: "set_track_locked", track_id: track.track_id, locked }),
            )}
            {track.clip_ids?.length === 0 && track.locked !== true ? (
              <button
                type="button"
                className={button}
                onClick={() => emit({ kind: "remove_empty_track", track_id: track.track_id })}
              >
                {t("studio.timeline.removeEmptyTrack")}
              </button>
            ) : null}
          </Section>
        </>
      ) : (
        <p className="text-xs text-muted-ink">{t("studio.timeline.selectSomething")}</p>
      )}
    </aside>
  );
}
