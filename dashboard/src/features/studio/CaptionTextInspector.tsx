import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";
import { useId, useState } from "react";
import { Check, ChevronRight, Palette, X } from "lucide-react";

import type { EditDocumentOperation, EditDocumentV2 } from "@/api/control-plane";
import { applyTimelineOperation, CAPTION_STYLE_LABELS, compatibleTrackIds } from "./timeline_domain";

type CaptionTextInspectorProps = {
  document: EditDocumentV2;
  selectedSceneId: string;
  onOperation: (operation: EditDocumentOperation) => void;
  disabled: boolean;
  compact?: boolean;
};

type CaptionStyle = keyof typeof CAPTION_STYLE_LABELS;
type CaptionClip = Extract<NonNullable<EditDocumentV2["clips"]>[number], { kind: "caption" }>;

const fieldClass =
  "mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring read-only:opacity-70";

const operationId = () => `op_${crypto.randomUUID()}`;

/**
 * Captions for the selected scene: cue text, cue timing, and style, plus a first
 * caption when the scene has none. Each edit is one operation on the shared
 * draft, checked against the same rules the server applies before it is sent.
 */
export function CaptionTextInspector({ document, selectedSceneId, onOperation, disabled, compact = false }: CaptionTextInspectorProps) {
  const { t } = useLocale();
  const styleName = (id: string) => t(`studio.caption.style.${id}` as MessageKey);
  const lockedId = useId();
  const styleId = useId();
  const newCaptionId = useId();
  const [refusal, setRefusal] = useState<string>();
  const [newCaption, setNewCaption] = useState("");
  const [styleOpen, setStyleOpen] = useState(false);
  const fps = document.canvas.fps;
  const toSeconds = (frame: number) => String(Number((frame / fps).toFixed(2)));
  const seconds = (from: number, duration: number) =>
    `${(from / fps).toFixed(1)}s–${((from + duration) / fps).toFixed(1)}s`;
  const scene = document.scenes.find((entry) => entry.scene_id === selectedSceneId);
  const captions = scene
    ? (document.clips ?? []).flatMap((clip) =>
        clip.kind === "caption" &&
        clip.from_frame < scene.start_frame + scene.duration_in_frames &&
        scene.start_frame < clip.from_frame + clip.duration_in_frames
          ? [clip]
          : [],
      )
    : [];
  const [captionTrackId] = compatibleTrackIds(document, "caption");

  // A refused operation would be dropped silently by the draft, so say why here instead.
  const emit = (operation: EditDocumentOperation) => {
    try {
      applyTimelineOperation(document, operation, {});
    } catch (error) {
      setRefusal(error instanceof Error ? error.message : String(error));
      return;
    }
    setRefusal(undefined);
    onOperation(operation);
  };

  const commitTiming = (clip: CaptionClip, index: number, edge: "start" | "end", raw: string) => {
    const cue = clip.cues[index]!;
    const value = Number(raw);
    if (!raw.trim() || !Number.isFinite(value)) return setRefusal(t("studio.caption.timeError"));
    const frame = Math.round(value * fps) - clip.from_frame;
    const start = edge === "start" ? frame : cue.from_frame;
    const end = edge === "end" ? frame : cue.from_frame + cue.duration_in_frames;
    if (start === cue.from_frame && end === cue.from_frame + cue.duration_in_frames) return;
    if (start < 0) return setRefusal(t("studio.caption.insideClip"));
    if (end <= start) return setRefusal(t("studio.caption.endAfterStart"));
    emit({
      kind: "set_caption_cue_timing",
      operation_id: operationId(),
      clip_id: clip.clip_id,
      cue_index: index,
      from_frame: start,
      duration_in_frames: end - start,
    });
  };

  return (
    <section aria-label={t("studio.caption.title")} className={`${compact ? "studio-caption-summary" : ""} border-l border-t border-border bg-card/60 p-4`}>
      <h2 className="font-mono text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{t("studio.caption.title")}</h2>
      {refusal ? (
        <p role="alert" className="mt-3 text-xs text-destructive">
          {refusal}
        </p>
      ) : null}
      {compact ? <div className="studio-caption-rows">{captions.flatMap((clip) => clip.cues.map((cue, index) => <details key={`${clip.clip_id}-${index}`}><summary><span>{seconds(clip.from_frame + cue.from_frame, cue.duration_in_frames)}</span><span>{cue.text}</span><ChevronRight size={12} /></summary><textarea aria-label={t("studio.caption.editCompact", { number: index + 1 })} value={cue.text} disabled={disabled || clip.locked || document.tracks.find((track) => track.track_id === clip.track_id)?.locked} onChange={(event) => { if (event.target.value.trim()) emit({ kind: "set_caption_cue_text", operation_id: operationId(), clip_id: clip.clip_id, cue_index: index, text: event.target.value }); }} /></details>))}</div> : null}
      <details className={compact ? "studio-caption-editors" : "contents"} open={!compact || undefined}>
      {compact ? <summary>{t("studio.caption.editAll")}</summary> : null}
      {captions.length ? (
        captions.map((clip) => {
          const track = document.tracks.find((entry) => entry.track_id === clip.track_id);
          const locked = Boolean(clip.locked || track?.locked);
          const style = clip.style_slot ?? "caption_default";
          return (
            <fieldset key={clip.clip_id} className="mt-4 space-y-3">
              <legend className="text-sm font-medium">
                {`${track?.label ?? t("studio.caption.title")} ${seconds(clip.from_frame, clip.duration_in_frames)}`}
              </legend>
              {locked ? (
                <p id={`${lockedId}-${clip.clip_id}`} className="text-xs text-muted-foreground">
                  {t("studio.caption.lockedClip")}
                </p>
              ) : null}
              <div className="text-sm">
                <label htmlFor={`${styleId}-${clip.clip_id}`} className="text-xs text-muted-foreground">
                  {t("studio.caption.styleLabel")}
                </label>
                <select
                  id={`${styleId}-${clip.clip_id}`}
                  className={fieldClass}
                  value={style}
                  disabled={disabled || locked}
                  onChange={(event) =>
                    emit({
                      kind: "set_caption_style",
                      operation_id: operationId(),
                      clip_id: clip.clip_id,
                      style_slot: event.target.value as CaptionStyle,
                    })
                  }
                >
                  {Object.keys(CAPTION_STYLE_LABELS).map((id) => (
                    <option key={id} value={id}>
                      {styleName(id)}
                    </option>
                  ))}
                  {style in CAPTION_STYLE_LABELS ? null : (
                    <option value={style} disabled>
                      {t("studio.caption.notAvailable", { style })}
                    </option>
                  )}
                </select>
              </div>
              {clip.cues.map((cue, index) => {
                const bounds = [
                  ["start", clip.from_frame + cue.from_frame],
                  ["end", clip.from_frame + cue.from_frame + cue.duration_in_frames],
                ] as const;
                return (
                  <div key={index} className="text-sm">
                    <p className="text-xs text-muted-foreground">
                      {`${t("studio.caption.cue", { number: index + 1 })} `}
                      <span className="font-mono">
                        {seconds(clip.from_frame + cue.from_frame, cue.duration_in_frames)}
                      </span>
                    </p>
                    <textarea
                      aria-label={t("studio.caption.cueText", { number: index + 1 })}
                      className={`${fieldClass} min-h-16 resize-y`}
                      value={cue.text}
                      maxLength={300}
                      readOnly={locked}
                      disabled={disabled}
                      aria-describedby={locked ? `${lockedId}-${clip.clip_id}` : undefined}
                      onChange={(event) => {
                        // The server refuses blank cue text, so a blank field is never sent.
                        if (locked || !event.target.value.trim()) return;
                        onOperation({
                          kind: "set_caption_cue_text",
                          operation_id: operationId(),
                          clip_id: clip.clip_id,
                          cue_index: index,
                          text: event.target.value,
                        });
                      }}
                    />
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      {bounds.map(([edge, frame]) => (
                        <input
                          // Remount when the saved frame moves, so the field shows the draft again.
                          key={`${edge}-${frame}`}
                          type="number"
                          step="0.1"
                          min={0}
                          aria-label={t(`studio.caption.cue.${edge}`, { number: index + 1 })}
                          className={fieldClass}
                          defaultValue={toSeconds(frame)}
                          readOnly={locked}
                          disabled={disabled}
                          onBlur={(event) => {
                            if (!locked) commitTiming(clip, index, edge, event.currentTarget.value);
                          }}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" && !locked) {
                              commitTiming(clip, index, edge, event.currentTarget.value);
                            }
                          }}
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </fieldset>
          );
        })
      ) : (
        <>
          <p className="mt-4 text-sm text-muted-foreground">{t("studio.caption.none")}</p>
          {!scene ? null : captionTrackId ? (
            <div className="mt-3 text-sm">
              <label htmlFor={newCaptionId} className="text-xs text-muted-foreground">
                {t("studio.caption.new")}
              </label>
              <textarea
                id={newCaptionId}
                className={`${fieldClass} min-h-16 resize-y`}
                value={newCaption}
                maxLength={300}
                disabled={disabled}
                onChange={(event) => setNewCaption(event.target.value)}
              />
              <button
                type="button"
                className="mt-2 rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-50"
                disabled={disabled || !newCaption.trim()}
                onClick={() => {
                  emit({
                    kind: "add_caption_clip",
                    operation_id: operationId(),
                    clip_id: `clip_${crypto.randomUUID()}`,
                    track_id: captionTrackId,
                    scene_id: scene.scene_id,
                    text: newCaption,
                  });
                  setNewCaption("");
                }}
              >
                {t("studio.caption.add")}
              </button>
            </div>
          ) : (
            <p className="mt-2 text-xs text-muted-foreground">
              {document.tracks.some((track) => track.kind === "caption")
                ? t("studio.caption.lockedLane")
                : t("studio.caption.noLane")}
            </p>
          )}
        </>
      )}
      </details>
      {compact ? <>
        <button type="button" className="studio-style-trigger" aria-label={t("studio.caption.styleLabel")} onClick={() => setStyleOpen((open) => !open)}><Palette size={16} /><span>{captions.length ? ((captions[0]!.style_slot ?? "caption_default") in CAPTION_STYLE_LABELS ? styleName(captions[0]!.style_slot ?? "caption_default") : captions[0]!.style_slot) : t("studio.caption.styleLabel")}</span><ChevronRight size={15} /></button>
        {styleOpen ? <div className="studio-caption-style-menu" role="dialog" aria-label={t("studio.caption.styleLabel")}><header><strong>{t("studio.caption.styleLabel")}</strong><button type="button" aria-label={t("studio.caption.styleClose")} onClick={() => setStyleOpen(false)}><X size={15} /></button></header><p>{t("studio.caption.styleChoices")}</p>{Object.keys(CAPTION_STYLE_LABELS).map((id) => <button key={id} type="button" disabled={disabled || !captions.length || captions[0]!.locked || document.tracks.find((track) => track.track_id === captions[0]!.track_id)?.locked} onClick={() => { emit({ kind: "set_caption_style", operation_id: operationId(), clip_id: captions[0]!.clip_id, style_slot: id as CaptionStyle }); setStyleOpen(false); }}><Palette size={15} /><span>{styleName(id)}</span>{captions[0]?.style_slot === id ? <Check size={14} /> : null}</button>)}<small>{t("studio.caption.styleNote")}</small></div> : null}
      </> : null}
    </section>
  );
}
