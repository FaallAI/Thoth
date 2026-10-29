import type { PointerEvent } from "react";
import { Lock } from "lucide-react";

import type { EditDocumentV2 } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";
import { clipLabelSource, framesToPixels } from "./timeline_domain";

export type GestureMode = "move" | "trim_start" | "trim_end";

type Clip = NonNullable<EditDocumentV2["clips"]>[number];
type TrackKind = EditDocumentV2["tracks"][number]["kind"];

type Props = {
  clip: Clip;
  trackKind: TrackKind;
  /** The track label, so every control reads as "<track> clip". */
  label: string;
  zoom: number;
  selected: boolean;
  locked: boolean;
  onSelect: () => void;
  onGestureStart: (mode: GestureMode, clientX: number) => void;
  onNudge: (frames: number) => void;
};

/** Video lanes read as footage, cards and words as panels, sound as the darkest well. */
const FILL: Record<TrackKind, string> = {
  main_video: "bg-raised",
  b_roll: "bg-raised",
  overlay: "bg-surface",
  caption: "bg-surface",
  narration: "bg-bg",
  music: "bg-bg",
  sfx: "bg-bg",
};

const handle =
  "absolute top-0 h-full w-2 cursor-ew-resize focus-visible:outline-2 focus-visible:outline-copper disabled:cursor-not-allowed disabled:opacity-0";

export function TimelineClip({
  clip,
  trackKind,
  label,
  zoom,
  selected,
  locked,
  onSelect,
  onGestureStart,
  onNudge,
}: Props) {
  const { t } = useLocale();
  const name = t("studio.timeline.clip", { track: label });
  const source = clipLabelSource(clip);
  const text =
    "text" in source
      ? source.text
      : "role" in source
        ? source.role === "hook" || source.role === "outro"
          ? t(`studio.story.beat.${source.role}`)
          : t(`studio.inventory.role.${source.role}`)
        : t(`studio.timeline.kind.${source.kind}`);
  const start = (mode: GestureMode) => (event: PointerEvent) => {
    if (event.button !== 0) return;
    onSelect();
    onGestureStart(mode, event.clientX);
  };

  return (
    <div
      className="absolute top-1 h-9"
      style={{
        left: `${framesToPixels(clip.from_frame, zoom)}px`,
        width: `${Math.max(8, framesToPixels(clip.duration_in_frames, zoom))}px`,
      }}
    >
      <button
        type="button"
        id={`timeline-clip-${clip.clip_id}`}
        aria-label={name}
        aria-pressed={selected}
        className={`flex h-full w-full items-start gap-1 overflow-hidden rounded-md border px-2 py-1 text-left text-xs text-ink transition-colors focus-visible:outline-2 focus-visible:outline-copper ${FILL[trackKind]} ${
          selected ? "border-2 border-copper" : "border-hairline hover:border-faint"
        }`}
        onClick={onSelect}
        onPointerDown={start("move")}
        onKeyDown={(event) => {
          const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
          if (!step || locked) return;
          event.preventDefault();
          onNudge(step);
        }}
      >
        {locked ? <Lock aria-hidden="true" size={11} className="mt-0.5 shrink-0 text-faint" /> : null}
        <span className="truncate rounded bg-well/70 px-1">{text}</span>
      </button>
      <button
        type="button"
        aria-label={t("studio.timeline.trimStartOf", { clip: name })}
        disabled={locked}
        className={`${handle} left-0 rounded-l-md ${selected ? "bg-copper/40" : ""}`}
        onPointerDown={start("trim_start")}
      />
      <button
        type="button"
        aria-label={t("studio.timeline.trimEndOf", { clip: name })}
        disabled={locked}
        className={`${handle} right-0 rounded-r-md ${selected ? "bg-copper/40" : ""}`}
        onPointerDown={start("trim_end")}
      />
    </div>
  );
}
