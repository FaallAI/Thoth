import { useEffect, useId, useState, type ReactNode } from "react";
import { PanelRight } from "lucide-react";

import type { EditDocumentOperation, EditDocumentV2 } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";
import { setPositionPreset, type PositionPreset } from "./story/story_edits";
import { clipLabel } from "./TimelineClip";
import { issueSentence } from "./IssuesPanel";
import { formatTimecode, parseTimecode, sourceSpan, timelineIssues, trackName } from "./timeline_domain";

/** The speeds a clip may play at; the server accepts exactly these (Tier 3a). */
const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4] as const;

type Props = {
  document: EditDocumentV2;
  selectedClipId: string;
  selectedTrackId: string;
  onOperation: (operation: EditDocumentOperation) => void;
  /** The clip's human name (spec 2026-11-01); absent, the Timeline's own words for it. */
  labelOf?: (clip: NonNullable<EditDocumentV2["clips"]>[number]) => string;
  /** At 1024 an Inspector with nothing selected folds to a narrow rail (spec 2026-11-08 §5.1). */
  rail?: boolean;
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

/** A time a person types ("0:07.5"); an unreadable one changes nothing and shows the time again. */
function TimeField({
  id,
  label,
  frame,
  fps,
  disabled,
  onCommit,
}: {
  id: string;
  label: string;
  frame: number;
  fps: number;
  disabled: boolean;
  onCommit: (frame: number) => void;
}) {
  const shown = formatTimecode(frame, fps);
  const [text, setText] = useState(shown);
  useEffect(() => setText(shown), [shown]);
  const commit = () => {
    // Only what the person typed: the shown time is rounded, so reading it back could move the clip.
    if (text.trim() === shown) return;
    const next = parseTimecode(text, fps);
    // The field shows the stored time again; an accepted edit then shows its new time.
    setText(shown);
    if (next === null || next === frame) return;
    onCommit(next);
  };
  return (
    <div className={field}>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="text"
        inputMode="decimal"
        className={input}
        value={text}
        disabled={disabled}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          } else if (event.key === "Escape") {
            setText(shown);
          }
        }}
      />
    </div>
  );
}

/**
 * A number a person types; it commits on Enter or on leaving the field, never while typing.
 * `onCommit` answers false to refuse the value, and the field shows the stored value again.
 */
function NumberField({
  id,
  label,
  shown,
  disabled,
  onCommit,
}: {
  id: string;
  label: string;
  shown: string;
  disabled: boolean;
  onCommit: (value: number) => boolean | void;
}) {
  const [text, setText] = useState(shown);
  useEffect(() => setText(shown), [shown]);
  const commit = () => {
    if (text.trim() === shown) return;
    const value = Number(text.trim().replace(",", "."));
    // The stored value shows again; an accepted edit then shows its new value.
    setText(shown);
    if (text.trim() && Number.isFinite(value)) onCommit(value);
  };
  return (
    <div className={field}>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="text"
        inputMode="decimal"
        className={input}
        value={text}
        disabled={disabled}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          } else if (event.key === "Escape") {
            setText(shown);
          }
        }}
      />
    </div>
  );
}

/** A fraction as a percent with at most one decimal, and back, without float noise. */
const percentOf = (fraction: number) => String(Math.round(fraction * 1000) / 10);
const fractionOf = (percent: number) => Math.round(percent * 100) / 10000;
/** The server's longest fade (`FadeFrames`). */
const MAX_FADE_FRAMES = 300;

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
  labelOf,
  rail = false,
}: Props) {
  const { t, plural } = useLocale();
  const ids = {
    start: useId(),
    end: useId(),
    startTime: useId(),
    endTime: useId(),
    volume: useId(),
    hidden: useId(),
    muted: useId(),
    locked: useId(),
    ownership: useId(),
    fit: useId(),
    cropLeft: useId(),
    cropTop: useId(),
    cropRight: useId(),
    cropBottom: useId(),
    positionX: useId(),
    positionY: useId(),
    scale: useId(),
    fadeIn: useId(),
    speed: useId(),
    fadeOut: useId(),
    overlayPreset: useId(),
    overlayText: useId(),
    overlayAccent: useId(),
    captionStyle: useId(),
    captionCues: useId(),
  };
  const fps = document.canvas.fps;
  const clip = document.clips?.find((candidate) => candidate.clip_id === selectedClipId);
  // The selected clip's own warnings (spec 2026-11-01, goal 7).
  const clipIssues = clip ? timelineIssues(document).filter((issue) => issue.target.kind === "clip" && issue.target.id === clip.clip_id) : [];
  const track = document.tracks.find(
    (candidate) => candidate.track_id === (clip?.track_id ?? selectedTrackId),
  );
  const frozen = clip?.locked === true || track?.locked === true;
  // Why the last typed value was refused; it belongs to one clip and clears with the selection.
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => setProblem(null), [selectedClipId]);
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

  type Video = Extract<NonNullable<EditDocumentV2["clips"]>[number], { kind: "video" }>;

  /** Crop as the share cut from each side, in percent (spec 2026-11-08 §6). */
  const cropFields = (video: Video) => {
    const crop = video.crop ?? { left: 0, top: 0, width: 1, height: 1 };
    const sides = { left: crop.left, top: crop.top, right: 1 - crop.left - crop.width, bottom: 1 - crop.top - crop.height };
    const set = (side: keyof typeof sides, percent: number) => {
      if (percent < 0 || percent > 100) return false;
      const next = { ...sides, [side]: fractionOf(percent) };
      const width = Math.round((1 - next.left - next.right) * 10000) / 10000;
      const height = Math.round((1 - next.top - next.bottom) * 10000) / 10000;
      if (width <= 0 || height <= 0) {
        setProblem(t("studio.timeline.cropNone"));
        return false;
      }
      setProblem(null);
      emit({ kind: "set_clip_crop", clip_id: video.clip_id, crop: { left: next.left, top: next.top, width, height } });
    };
    const fields = [
      ["left", ids.cropLeft, "studio.timeline.cropLeft"],
      ["top", ids.cropTop, "studio.timeline.cropTop"],
      ["right", ids.cropRight, "studio.timeline.cropRight"],
      ["bottom", ids.cropBottom, "studio.timeline.cropBottom"],
    ] as const;
    return (
      <>
        {fields.map(([side, id, label]) => (
          <NumberField
            key={side}
            id={id}
            label={t(label)}
            shown={percentOf(sides[side])}
            disabled={frozen}
            onCommit={(percent) => set(side, percent)}
          />
        ))}
        <button
          type="button"
          className={button}
          disabled={frozen || !video.crop}
          onClick={() => emit({ kind: "set_clip_crop", clip_id: video.clip_id, crop: null })}
        >
          {t("studio.timeline.resetCrop")}
        </button>
      </>
    );
  };

  /** Offset in percent of the canvas and scale in percent (spec 2026-11-08 §6). */
  const positionFields = (video: Video) => {
    const position = video.position ?? { x: 0, y: 0, scale: 1 };
    const place = (next: Partial<typeof position>) =>
      emit({ kind: "set_clip_position", clip_id: video.clip_id, position: { ...position, ...next } });
    const within = (low: number, high: number, apply: (percent: number) => void) => (percent: number) =>
      percent < low || percent > high ? false : apply(percent);
    return (
      <>
        <NumberField
          id={ids.positionX}
          label={t("studio.timeline.positionX")}
          shown={percentOf(position.x)}
          disabled={frozen}
          onCommit={within(-100, 100, (percent) => place({ x: fractionOf(percent) }))}
        />
        <NumberField
          id={ids.positionY}
          label={t("studio.timeline.positionY")}
          shown={percentOf(position.y)}
          disabled={frozen}
          onCommit={within(-100, 100, (percent) => place({ y: fractionOf(percent) }))}
        />
        <NumberField
          id={ids.scale}
          label={t("studio.timeline.scale")}
          shown={percentOf(position.scale)}
          disabled={frozen}
          onCommit={within(1, 400, (percent) => place({ scale: fractionOf(percent) }))}
        />
        <button
          type="button"
          className={button}
          disabled={frozen || !video.position}
          onClick={() => place({ x: 0, y: 0, scale: 1 })}
        >
          {t("studio.timeline.resetPosition")}
        </button>
      </>
    );
  };

  /** Speed from the presets (Tier 3a): the clip keeps its place and plays more or less source. */
  const speedField = (sped: { clip_id: string; asset_id: string; duration_in_frames: number; source_from_frame?: number; speed?: number; hold_after_source?: boolean }) => {
    const asset = document.asset_refs?.find((ref) => ref.asset_id === sped.asset_id);
    if (asset?.kind === "image") return null;
    const choose = (speed: (typeof SPEEDS)[number]) => {
      const room = asset?.duration_in_frames;
      const needed = (sped.source_from_frame ?? 0) + sourceSpan({ duration_in_frames: sped.duration_in_frames, speed });
      if (room != null && needed > room && !sped.hold_after_source) {
        setProblem(t("studio.menu.reason.no_source"));
        return;
      }
      setProblem(null);
      emit({ kind: "set_clip_speed", clip_id: sped.clip_id, speed });
    };
    return (
      <div className={field}>
        <label htmlFor={ids.speed}>{t("studio.timeline.speed")}</label>
        <select
          id={ids.speed}
          className={input}
          value={String(sped.speed ?? 1)}
          disabled={frozen}
          onChange={(event) => choose(Number(event.target.value) as (typeof SPEEDS)[number])}
        >
          {SPEEDS.map((speed) => (
            <option key={speed} value={String(speed)}>
              {`${speed}×`}
            </option>
          ))}
        </select>
      </div>
    );
  };

  /** Fade in and out in seconds, on a video or audio clip (spec 2026-11-08 §6). */
  const fadeFields = (faded: { clip_id: string; duration_in_frames: number; fade_in_frames?: number; fade_out_frames?: number }) => {
    const fades = { in: faded.fade_in_frames ?? 0, out: faded.fade_out_frames ?? 0 };
    const seconds = (frames: number) => String(Math.round((frames / fps) * 10) / 10);
    const set = (side: "in" | "out", value: number) => {
      const frames = Math.round(value * fps);
      if (frames < 0) return false;
      if (frames > MAX_FADE_FRAMES) {
        setProblem(t("studio.timeline.fadeMax", { seconds: seconds(MAX_FADE_FRAMES) }));
        return false;
      }
      const next = { ...fades, [side]: frames };
      if (next.in + next.out > faded.duration_in_frames) {
        setProblem(t("studio.timeline.fadesTooLong"));
        return false;
      }
      setProblem(null);
      emit({ kind: "set_clip_fades", clip_id: faded.clip_id, fade_in_frames: next.in, fade_out_frames: next.out });
    };
    return (
      <>
        <NumberField
          id={ids.fadeIn}
          label={t("studio.timeline.fadeIn")}
          shown={seconds(fades.in)}
          disabled={frozen}
          onCommit={(value) => set("in", value)}
        />
        <NumberField
          id={ids.fadeOut}
          label={t("studio.timeline.fadeOut")}
          shown={seconds(fades.out)}
          disabled={frozen}
          onCommit={(value) => set("out", value)}
        />
        {problem ? (
          <p role="alert" className="text-xs text-destructive">
            {problem}
          </p>
        ) : null}
      </>
    );
  };

  if (rail && !clip && !track) {
    return (
      <aside
        className="flex min-h-0 flex-col items-center border-l border-hairline bg-surface pt-4 text-faint"
        aria-label={t("studio.timeline.inspector")}
      >
        <PanelRight aria-hidden="true" size={16} />
        <span className="sr-only">{t("studio.timeline.selectSomething")}</span>
      </aside>
    );
  }

  return (
    <aside
      className="min-h-0 space-y-3 overflow-auto border-l border-hairline bg-surface p-4"
      aria-label={t("studio.timeline.inspector")}
    >
      {clip ? (
        <>
          <header>
            <h2 className="truncate text-sm font-semibold text-ink">{labelOf?.(clip) ?? clipLabel(t, clip)}</h2>
            {track ? (
              <p className="text-xs text-muted-ink">{t("studio.timeline.track", { track: trackName(t, document, track) })}</p>
            ) : null}
          </header>

          <Section title={t("studio.timeline.section.timing")}>
            <TimeField
              id={ids.startTime}
              label={t("studio.timeline.startTime")}
              frame={clip.from_frame}
              fps={fps}
              disabled={frozen}
              onCommit={(frame) =>
                emit({ kind: "move_clip", clip_id: clip.clip_id, target_track_id: clip.track_id, from_frame: frame, ripple: false })
              }
            />
            <TimeField
              id={ids.endTime}
              label={t("studio.timeline.endTime")}
              frame={clip.from_frame + clip.duration_in_frames}
              fps={fps}
              disabled={frozen}
              onCommit={(frame) => emit({ kind: "trim_clip_end", clip_id: clip.clip_id, end_frame: frame })}
            />
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
              <div className={field}>
                <label htmlFor={ids.fit}>{t("studio.timeline.fit")}</label>
                <select
                  id={ids.fit}
                  className={input}
                  value={clip.fit}
                  disabled={frozen}
                  onChange={(event) =>
                    emit({ kind: "set_clip_fit", clip_id: clip.clip_id, fit: event.target.value as typeof clip.fit })
                  }
                >
                  {(["cover", "contain", "fill"] as const).map((fit) => (
                    <option key={fit} value={fit}>
                      {t(`studio.timeline.fit.${fit}`)}
                    </option>
                  ))}
                </select>
              </div>
              {speedField(clip)}
              <div role="group" aria-label={t("studio.timeline.crop")} className="space-y-2">
                {cropFields(clip)}
              </div>
              <div role="group" aria-label={t("studio.timeline.position")} className="space-y-2">
                {positionFields(clip)}
              </div>
              {fadeFields(clip)}
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
              {speedField(clip)}
              {fadeFields(clip)}
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
          {clipIssues.length ? (
            <Section title={t("studio.issues.forClip", { count: clipIssues.length })}>
              <ul className="space-y-1 text-xs text-status-waiting">
                {clipIssues.map((issue) => (
                  <li key={issue.issue_id}>{issueSentence(t, document, issue)}</li>
                ))}
              </ul>
            </Section>
          ) : null}
        </>
      ) : track ? (
        <>
          <header>
            <h2 className="truncate text-sm font-semibold text-ink">{trackName(t, document, track)}</h2>
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
