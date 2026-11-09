import { useState } from "react";
import { CircleCheck } from "lucide-react";

import type { EditDocumentV2 } from "@/api/control-plane";
import { useLocale, type LocaleState } from "@/lib/locale";
import type { EditorAction, EditorMode } from "./editor_state";
import { issueTarget, timelineIssues, type TimelineIssue } from "./timeline_domain";

type Clip = NonNullable<EditDocumentV2["clips"]>[number];

type Props = {
  document: EditDocumentV2;
  selectedIssueId: string;
  mode: EditorMode;
  dispatch: (action: EditorAction) => void;
  /** The clip's human name (spec 2026-11-01); absent, a row is the issue's sentence alone. */
  labelOf?: (clip: Clip) => string;
  /** In the wide Timeline's toolbar: the count without the sentence, and the list opens upward. */
  inline?: boolean;
};

type Track = EditDocumentV2["tracks"][number];

/** A lane's name: its label, else the word for its kind; never its id. */
export function laneName(t: LocaleState["t"], track: Track | undefined): string {
  return track?.label || (track ? t(`studio.timeline.trackKind.${track.kind}`) : t("studio.label.clip"));
}

/** An issue in readable language: "<lane>: <what is wrong>". */
export function issueSentence(t: LocaleState["t"], doc: EditDocumentV2, issue: TimelineIssue): string {
  return t(`studio.issues.${issue.code}`, { track: laneName(t, doc.tracks.find((track) => track.track_id === issue.target.track_id)) });
}

/** A frame as m:ss.s on the canvas clock. */
function clock(frame: number, fps: number): string {
  const seconds = frame / fps;
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(1).padStart(4, "0")}`;
}

/**
 * The issues bar under the timeline. Every timeline issue is a warning: none of them blocks a
 * render, which render readiness decides (DESIGN §13.4), so the bar counts no "blocking" ones.
 */
export function IssuesBar({ document: doc, selectedIssueId, mode, dispatch, labelOf, inline = false }: Props) {
  const { t, plural } = useLocale();
  const [open, setOpen] = useState(false);
  const issues = timelineIssues(doc);
  // A cleared list closes, so a later warning from a background save never opens it unasked.
  if (open && issues.length === 0) setOpen(false);
  const sentence = (issue: TimelineIssue) => issueSentence(t, doc, issue);
  const clipOf = (issue: TimelineIssue) =>
    issue.target.kind === "clip" ? doc.clips?.find((clip) => clip.clip_id === issue.target.id) : undefined;
  // Grouped under each lane, in track order (spec 2026-11-01, goal 7).
  const lanes = [...doc.tracks]
    .sort((a, b) => a.order - b.order)
    .map((track) => ({ track, issues: issues.filter((issue) => issue.target.track_id === track.track_id) }))
    .filter((lane) => lane.issues.length > 0);

  const select = (issue: TimelineIssue) => {
    const target = issueTarget(issue);
    // Close first, so the clip the issue points at is not under the list.
    setOpen(false);
    // Advanced mode first: the element to focus only exists there.
    if (mode !== "advanced") dispatch({ type: "set_editor_mode", mode: "advanced" });
    dispatch({ type: "select_issue", issueId: issue.issue_id });
    dispatch({ type: "select_track", trackId: target.selectedTrackId });
    // A row's clip may be gone by the time it is chosen: the lane is still a sound target.
    const clip = clipOf(issue);
    if (target.selectedClipId && clip) {
      dispatch({ type: "select_clip", clipId: target.selectedClipId });
      dispatch({ type: "set_playhead", frame: clip.from_frame });
    }
    // Focus moves only on this deliberate click, never on a background revalidation that
    // reorders the list.
    const id = target.selectedClipId
      ? `timeline-clip-${target.selectedClipId}`
      : `timeline-track-${target.selectedTrackId}`;
    window.document.getElementById(id)?.focus();
  };

  return (
    <section className={`relative text-xs ${inline ? "" : "border-t border-hairline bg-well"}`} aria-label={t("studio.issues.title")}>
      {open && issues.length > 0 ? (
        <div className={`absolute bottom-full z-30 overflow-auto rounded-t-[10px] border border-hairline bg-raised p-2 shadow-xl ${inline ? "right-0 max-h-56 w-96 max-w-[80vw]" : "left-0 max-h-[50vh] w-full max-w-md"}`}>
          {lanes.map(({ track, issues: laneIssues }) => (
            <section key={track.track_id} role="group" aria-label={laneName(t, track)} className="mb-2 last:mb-0">
              <h3 className="px-2 py-1 font-mono text-[0.7rem] text-muted-ink">
                {laneName(t, track)} <span className="text-faint">{laneIssues.length}</span>
              </h3>
              <ul className="space-y-1">
                {laneIssues.map((issue) => {
                  const selected = issue.issue_id === selectedIssueId;
                  const clip = clipOf(issue);
                  return (
                    <li key={issue.issue_id}>
                      <button
                        type="button"
                        aria-current={selected}
                        className={`flex w-full items-start gap-2 rounded-md border px-2 py-1.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-copper ${
                          selected ? "border-copper bg-surface text-ink" : "border-transparent text-muted-ink hover:bg-surface"
                        }`}
                        onClick={() => select(issue)}
                      >
                        <span className="min-w-0 flex-1">
                          {clip && labelOf ? <span className="block text-ink">{labelOf(clip)}</span> : null}
                          <span className="block">{sentence(issue)}</span>
                        </span>
                        {clip ? <span className="shrink-0 font-mono text-faint">{clock(clip.from_frame, doc.canvas.fps)}</span> : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      ) : null}
      <div className={`flex items-center gap-2 ${inline ? "" : "h-8 px-3"}`}>
        {issues.length === 0 ? (
          <>
            <CircleCheck aria-hidden="true" size={13} className="text-status-done" />
            <span className="text-muted-ink">{t("studio.issues.none")}</span>
          </>
        ) : (
          <>
            <span aria-hidden="true" className="size-2 rounded-full bg-status-waiting" />
            <span className="shrink-0 text-ink">{plural("studio.issues.warnings", issues.length)}</span>
            {inline ? null : <span className="min-w-0 truncate text-faint">{sentence(issues[0]!)}</span>}
            <button
              type="button"
              aria-expanded={open}
              className="ml-auto shrink-0 rounded px-1 text-copper hover:underline focus-visible:outline-2 focus-visible:outline-copper"
              onClick={() => setOpen((value) => !value)}
            >
              {t("studio.issues.review")}
            </button>
          </>
        )}
      </div>
    </section>
  );
}
