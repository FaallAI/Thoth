import { useState } from "react";
import { CircleCheck } from "lucide-react";

import type { EditDocumentV2 } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";
import type { EditorAction, EditorMode } from "./editor_state";
import { issueTarget, timelineIssues, type TimelineIssue } from "./timeline_domain";

type Props = {
  document: EditDocumentV2;
  selectedIssueId: string;
  mode: EditorMode;
  dispatch: (action: EditorAction) => void;
};

/**
 * The issues bar under the timeline. Every timeline issue is a warning: none of them blocks a
 * render, which render readiness decides (DESIGN §13.4), so the bar counts no "blocking" ones.
 */
export function IssuesBar({ document: doc, selectedIssueId, mode, dispatch }: Props) {
  const { t, plural } = useLocale();
  const [open, setOpen] = useState(false);
  const issues = timelineIssues(doc);
  const sentence = (issue: TimelineIssue) =>
    t(`studio.issues.${issue.code}`, {
      track: doc.tracks.find((track) => track.track_id === issue.target.track_id)?.label ?? issue.target.track_id,
    });

  const select = (issue: TimelineIssue) => {
    const target = issueTarget(issue);
    // Advanced mode first: the element to focus only exists there.
    if (mode !== "advanced") dispatch({ type: "set_editor_mode", mode: "advanced" });
    dispatch({ type: "select_issue", issueId: issue.issue_id });
    dispatch({ type: "select_track", trackId: target.selectedTrackId });
    if (target.selectedClipId) dispatch({ type: "select_clip", clipId: target.selectedClipId });
    // Focus moves only on this deliberate click, never on a background revalidation that
    // reorders the list.
    const id = target.selectedClipId
      ? `timeline-clip-${target.selectedClipId}`
      : `timeline-track-${target.selectedTrackId}`;
    window.document.getElementById(id)?.focus();
  };

  return (
    <section className="relative border-t border-hairline bg-well text-xs" aria-label={t("studio.issues.title")}>
      {open && issues.length > 0 ? (
        <ul className="absolute bottom-full left-0 right-0 max-h-[40vh] space-y-1 overflow-auto border-t border-hairline bg-surface p-2">
          {issues.map((issue) => {
            const selected = issue.issue_id === selectedIssueId;
            return (
              <li key={issue.issue_id}>
                <button
                  type="button"
                  aria-current={selected}
                  className={`w-full rounded-md border px-2 py-1 text-left transition-colors focus-visible:outline-2 focus-visible:outline-copper ${
                    selected ? "border-copper bg-raised text-ink" : "border-hairline text-muted-ink hover:bg-raised"
                  }`}
                  onClick={() => select(issue)}
                >
                  {sentence(issue)}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
      <div className="flex h-8 items-center gap-2 px-3">
        {issues.length === 0 ? (
          <>
            <CircleCheck aria-hidden="true" size={13} className="text-status-done" />
            <span className="text-muted-ink">{t("studio.issues.none")}</span>
          </>
        ) : (
          <>
            <span aria-hidden="true" className="size-2 rounded-full bg-status-waiting" />
            <span className="shrink-0 text-ink">{plural("studio.issues.warnings", issues.length)}</span>
            <span className="min-w-0 truncate text-faint">{sentence(issues[0]!)}</span>
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
