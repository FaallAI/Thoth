import { MapPin } from "lucide-react";
import { useCallback, useEffect, useId, useReducer, useRef } from "react";

import {
  StudioReviewRequestError,
  type ControlPlaneClient,
  type EditDocument,
} from "@/api/control-plane";
import { Button } from "@/components/ui/button";
import { formatDay } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";
import { cn } from "@/lib/utils";
import type { EditorSaveStatus } from "./editor_state";
import {
  REVIEW_TEXT_LIMIT,
  createReviewState,
  currentDecision,
  formatTimecode,
  reasonPayload,
  reviewGate,
  reviewReducer,
  type ReviewAction,
  type ReviewDecisionKind,
  type ReviewMessage,
  type ReviewSubmission,
} from "./studio_review_state";

export type StudioReviewClient = Pick<
  ControlPlaneClient,
  | "listStudioReviewComments"
  | "createStudioReviewComment"
  | "listStudioReviewDecisions"
  | "createStudioReviewDecision"
>;

type Props = {
  client: StudioReviewClient;
  projectId: string;
  documentId: string;
  /** The saved revision every comment and decision binds to; never the draft. */
  savedDocument: EditDocument;
  saveStatus: EditorSaveStatus;
  isOffline: boolean;
  blockingIssues: number;
  /** The shared preview's playhead, offered as a comment anchor. */
  currentFrame: number;
  /** Asks the editor to bring a newer saved revision in, through its own conflict choice. */
  onLoadRevision?: (revision: number) => void;
};

const field =
  "w-full rounded-md border border-hairline bg-well px-3 py-2 text-sm text-ink placeholder:text-faint focus-visible:outline-2 focus-visible:outline-accent";

const makeOperationId = () => `op_${crypto.randomUUID()}`;

export function StudioReviewPanel({
  client,
  projectId,
  documentId,
  savedDocument,
  saveStatus,
  isOffline,
  blockingIssues,
  currentFrame,
  onLoadRevision,
}: Props) {
  const [state, dispatch] = useReducer(reviewReducer, undefined, createReviewState);
  const savedRevision = savedDocument.revision;
  const gate = reviewGate(state, { savedRevision, saveStatus, isOffline, blockingIssues });
  const current = currentDecision(state.decisions, savedRevision);
  const timecode = formatTimecode(currentFrame, savedDocument.canvas.fps);
  // Retry replays the frame the comment was pinned to, never the moved playhead.
  const retryFrame = state.retryable?.kind === "comment" ? state.retryable.request.frame : null;
  const staleActive = state.staleRevision !== null && savedRevision < state.staleRevision;
  const commentId = useId();
  const reasonId = useId();
  const confirmTitleId = useId();
  const approveRef = useRef<HTMLButtonElement>(null);
  const requestRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  /** Bumped when the project or document changes, and on unmount, so a late answer is dropped. */
  const generation = useRef(0);

  const loadComments = useCallback(
    (cursor?: string) => {
      const requestGeneration = generation.current;
      void client
        .listStudioReviewComments(projectId, documentId, cursor ? { cursor } : undefined)
        .then((page) => {
          if (requestGeneration !== generation.current) return;
          if (!Array.isArray(page.comments)) throw new Error("malformed review page");
          dispatch({ type: "comments_loaded", comments: page.comments, nextCursor: page.next_cursor ?? null });
        })
        .catch(() => {
          if (requestGeneration === generation.current) dispatch({ type: "load_failed", list: "comments" });
        });
    },
    [client, documentId, projectId],
  );
  const loadDecisions = useCallback(
    (cursor?: string) => {
      const requestGeneration = generation.current;
      void client
        .listStudioReviewDecisions(projectId, documentId, cursor ? { cursor } : undefined)
        .then((page) => {
          if (requestGeneration !== generation.current) return;
          if (!Array.isArray(page.decisions)) throw new Error("malformed review page");
          dispatch({ type: "decisions_loaded", decisions: page.decisions, nextCursor: page.next_cursor ?? null });
        })
        .catch(() => {
          if (requestGeneration === generation.current) dispatch({ type: "load_failed", list: "decisions" });
        });
    },
    [client, documentId, projectId],
  );

  useEffect(() => {
    dispatch({ type: "reset" });
    loadComments();
    loadDecisions();
    return () => {
      generation.current += 1;
    };
  }, [loadComments, loadDecisions]);

  useEffect(() => {
    if (state.confirming) confirmRef.current?.focus();
  }, [state.confirming]);

  const submit = (submission: ReviewSubmission) => {
    const requestGeneration = generation.current;
    dispatch({ type: "submitted", submission });
    const request: Promise<ReviewAction> =
      submission.kind === "comment"
        ? client
            .createStudioReviewComment(projectId, documentId, submission.request)
            .then((comment) => ({ type: "comment_created", comment }))
        : client
            .createStudioReviewDecision(projectId, documentId, submission.request)
            .then((decision) => ({ type: "decision_created", decision }));
    void request
      .then((action) => {
        if (requestGeneration === generation.current) dispatch(action);
      })
      .catch((error: unknown) => {
        if (requestGeneration !== generation.current) return;
        const typed = error instanceof StudioReviewRequestError;
        dispatch({
          type: "submit_failed",
          code: typed ? error.code : "review_request_failed",
          latestRevision: typed ? error.latestRevision : null,
        });
      });
  };

  const postComment = () => {
    if (!gate.canComment || !state.commentText.trim()) return;
    submit({
      kind: "comment",
      request: {
        base_revision: savedRevision,
        operation_id: makeOperationId(),
        text: state.commentText,
        frame: state.pinToFrame ? currentFrame : null,
      },
    });
  };

  const decide = (decision: ReviewDecisionKind) => {
    if (decision === "approved" ? !gate.canApprove : !gate.canComment) return;
    submit({
      kind: "decision",
      request: {
        base_revision: savedRevision,
        operation_id: makeOperationId(),
        decision,
        reason: reasonPayload(state.reason),
      },
    });
  };

  const cancelConfirmation = () => {
    const trigger = state.confirming === "approved" ? approveRef : requestRef;
    dispatch({ type: "decision_confirming", decision: null });
    trigger.current?.focus();
  };

  const { t, plural, locale } = useLocale();
  const say = (message: ReviewMessage) =>
    "plural" in message ? plural(message.plural, message.count) : t(message.key, message.values);
  const actorName = (actor: { actor_id: string; display_name?: string | null }) => actor.display_name ?? actor.actor_id;
  const when = (createdAt: string) => (Number.isNaN(Date.parse(createdAt)) ? "" : formatDay(locale, createdAt));
  const decisionLabel = (kind: ReviewDecisionKind) => t(`studio.review.decision.${kind}`);
  const initials = (name: string) =>
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0]?.toUpperCase())
      .join("");
  const sectionHeading = "text-[13px] font-semibold tracking-[0.06em] text-muted-ink uppercase";

  return (
    <section className="studio-review-panel flex flex-col gap-5 bg-surface p-5 text-ink" aria-label={t("studio.review.title")}>
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t("studio.review.title")}</h2>
          <p className="mt-1 text-sm text-muted-ink">{t("studio.review.appliesTo", { revision: savedRevision })}</p>
        </div>
        <span className="rounded-full bg-raised px-2.5 py-1 font-mono text-[12.5px] text-muted-ink">rev {savedRevision}</span>
      </header>
      <p className="text-sm font-medium">
        {current
          ? t("studio.review.current", { decision: decisionLabel(current.decision), revision: current.document_revision })
          : t("studio.review.none", { revision: savedRevision })}
      </p>

      <p role="status" aria-live="polite" className="text-sm text-muted-ink empty:hidden">
        {state.pending
          ? t(state.pending.kind === "comment" ? "studio.review.posting" : "studio.review.recording")
          : state.notice
            ? say(state.notice)
            : null}
      </p>
      {gate.blockedReason && !staleActive ? <p className="text-[13px] text-muted-ink">{say(gate.blockedReason)}</p> : null}
      {state.staleRevision !== null ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md bg-accent/10 p-3 text-sm">
          {staleActive ? (
            <>
              <p>{t("studio.review.stale.newer", { revision: state.staleRevision })}</p>
              {onLoadRevision ? (
                <Button variant="secondary" size="sm" onClick={() => onLoadRevision(state.staleRevision!)}>
                  {t("studio.review.stale.load", { revision: state.staleRevision })}
                </Button>
              ) : null}
            </>
          ) : (
            <p>{t("studio.review.stale.loaded", { revision: savedRevision })}</p>
          )}
        </div>
      ) : null}
      {state.error ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md bg-status-failed/10 p-3 text-sm">
          <p>{t(`studio.review.error.${state.error}`)}</p>
          {retryFrame !== null && retryFrame !== undefined ? (
            <p>{t("studio.review.retryPinned", { time: formatTimecode(retryFrame, savedDocument.canvas.fps) })}</p>
          ) : null}
          {state.retryable ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={!gate.canComment}
              onClick={() => state.retryable && submit(state.retryable)}
            >
              {t("studio.review.retry")}
            </Button>
          ) : null}
        </div>
      ) : null}
      {state.historyFailed.comments || state.historyFailed.decisions ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 text-sm">
          <p>{t("studio.review.historyFailed")}</p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              if (state.historyFailed.comments) loadComments();
              if (state.historyFailed.decisions) loadDecisions();
            }}
          >
            {t("studio.review.reload")}
          </Button>
        </div>
      ) : null}

      <div className="flex flex-col gap-3">
        <h3 className={sectionHeading}>{t("studio.review.comments")}</h3>
        {!state.comments.length ? <p className="text-sm text-muted-ink">{t("studio.review.noComments")}</p> : null}
        <ol className="flex flex-col gap-3" aria-label={t("studio.review.commentsList")}>
          {state.comments.map((comment) => {
            const name = actorName(comment.actor);
            const earlier = comment.document_revision !== savedRevision;
            return (
              <li key={comment.comment_id} className={cn("rounded-[10px] border border-hairline bg-raised p-3", earlier && "opacity-70")}>
                <p className="flex items-center gap-2 font-mono text-[12.5px] text-muted-ink">
                  <MapPin aria-hidden="true" className="size-3.5" />
                  {comment.frame == null
                    ? t("studio.review.wholeVideo")
                    : t("studio.review.at", { time: formatTimecode(comment.frame, savedDocument.canvas.fps) })}
                  <span aria-hidden="true">·</span>
                  {earlier
                    ? t("studio.review.earlier", { revision: comment.document_revision })
                    : t("studio.review.thisRevision", { revision: comment.document_revision })}
                </p>
                <div className="mt-2 flex gap-2.5">
                  <span
                    aria-hidden="true"
                    className="flex size-7 shrink-0 items-center justify-center rounded-full bg-well text-[11px] font-semibold text-muted-ink"
                  >
                    {initials(name)}
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm">
                      <span className="font-semibold">{name}</span>
                      <span className="ml-2 text-[13px] text-faint">{when(comment.created_at)}</span>
                    </p>
                    <p className="mt-1 text-sm break-words whitespace-pre-wrap">{comment.text}</p>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
        {state.commentCursor ? (
          <Button variant="ghost" size="sm" className="self-start" onClick={() => loadComments(state.commentCursor!)}>
            {t("studio.review.moreComments")}
          </Button>
        ) : null}
      </div>

      <div className="flex flex-col gap-2 rounded-[10px] border border-hairline bg-raised p-3">
        <label htmlFor={commentId} className="text-sm font-medium">
          {t("studio.review.comment")}
        </label>
        <textarea
          id={commentId}
          className={field}
          rows={3}
          maxLength={REVIEW_TEXT_LIMIT}
          value={state.commentText}
          onChange={(event) => dispatch({ type: "comment_edited", text: event.target.value })}
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label className="flex items-center gap-2 font-mono text-[12.5px] text-muted-ink">
            <input
              type="checkbox"
              className="size-4 accent-[var(--accent)]"
              checked={state.pinToFrame}
              onChange={(event) => dispatch({ type: "pin_toggled", pinned: event.target.checked })}
            />
            {t("studio.review.pin", { time: timecode })}
          </label>
          <Button variant="secondary" size="sm" disabled={!gate.canComment || !state.commentText.trim()} onClick={postComment}>
            {t("studio.review.post")}
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor={reasonId} className="text-sm font-medium">
          {t("studio.review.reason")}
        </label>
        <textarea
          id={reasonId}
          className={field}
          rows={2}
          maxLength={REVIEW_TEXT_LIMIT}
          value={state.reason}
          onChange={(event) => dispatch({ type: "reason_edited", reason: event.target.value })}
        />
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            ref={requestRef}
            variant="ghost"
            disabled={!gate.canComment}
            onClick={() => dispatch({ type: "decision_confirming", decision: "changes_requested" })}
          >
            {t("studio.review.requestChanges")}
          </Button>
          <Button
            ref={approveRef}
            disabled={!gate.canApprove}
            onClick={() => dispatch({ type: "decision_confirming", decision: "approved" })}
          >
            {t("studio.review.approve")}
          </Button>
        </div>
        {gate.approveBlockedReason ? (
          <p className="text-right text-[13px] text-muted-ink">{say(gate.approveBlockedReason)}</p>
        ) : null}
        {state.confirming ? (
          <div
            role="group"
            aria-labelledby={confirmTitleId}
            className="flex flex-col gap-2 rounded-[10px] border border-hairline bg-raised p-3 text-sm"
          >
            <p id={confirmTitleId} className="font-medium">
              {t(`studio.review.confirm.${state.confirming}`, { revision: savedRevision })}
            </p>
            <p className="text-[13px] text-muted-ink">{t("studio.review.confirm.note")}</p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={cancelConfirmation}>
                {t("common.cancel")}
              </Button>
              <Button
                ref={confirmRef}
                size="sm"
                disabled={state.confirming === "approved" ? !gate.canApprove : !gate.canComment}
                onClick={() => state.confirming && decide(state.confirming)}
              >
                {t(`studio.review.confirm.${state.confirming}Button`)}
              </Button>
            </div>
          </div>
        ) : null}
      </div>

      <div className="flex flex-col gap-2">
        <h3 className={sectionHeading}>{t("studio.review.decisions")}</h3>
        {!state.decisions.length ? <p className="text-sm text-muted-ink">{t("studio.review.noDecisions")}</p> : null}
        <ol className="flex flex-col divide-y divide-hairline" aria-label={t("studio.review.decisions")}>
          {state.decisions.map((decision) => (
            <li key={decision.decision_id} className="py-2 text-[13px] text-muted-ink">
              <span className="text-ink">
                {t("studio.review.decisionLine", {
                  decision: decisionLabel(decision.decision),
                  revision: decision.document_revision,
                })}
              </span>{" "}
              · {actorName(decision.actor)} · {when(decision.created_at)}
              {decision.reason ? <span className="block break-words whitespace-pre-wrap">{decision.reason}</span> : null}
            </li>
          ))}
        </ol>
        {state.decisionCursor ? (
          <Button variant="ghost" size="sm" className="self-start" onClick={() => loadDecisions(state.decisionCursor!)}>
            {t("studio.review.olderDecisions")}
          </Button>
        ) : null}
      </div>
    </section>
  );
}
