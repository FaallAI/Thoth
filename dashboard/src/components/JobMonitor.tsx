import { useEffect, useRef, useState } from "react";
import {
  cancelJob,
  cleanupJob,
  describeCode,
  formatBytes,
  getJob,
  getManifest,
  streamJob,
  type JobRecord,
  type Manifest,
} from "@/api";
import { CleanupButton } from "@/components/CleanupButton";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { StatusBadge } from "@/components/StatusBadge";
import { LogPane, type LogLine } from "@/components/LogPane";
import { ReviewPanel } from "@/components/ReviewPanel";
import { terminalEventIsFailure, terminalEventKind } from "@/lib/job-events";
import { Check, RotateCcw, ScanEye } from "lucide-react";

let seq = 0;
function nextId() {
  seq += 1;
  return `${Date.now()}-${seq}`;
}

const pct = (ratio: number) => `${Math.round(ratio * 100)}%`;

/** Watches one job over SSE: stage/progress/status, cancel, artifact links, and feeds LogPane. */
export function JobMonitor({ jobId }: { jobId: string | null }) {
  const [record, setRecord] = useState<JobRecord | null>(null);
  const [lines, setLines] = useState<LogLine[]>([]);
  const [manifest, setManifest] = useState<Manifest>({});
  const [manifestNonce, setManifestNonce] = useState(0);
  const esRef = useRef<EventSource | null>(null);

  // Artifact facts are re-read on every terminal transition and after a cleanup,
  // so the panel never claims artifacts that are no longer on disk.
  useEffect(() => {
    if (!jobId) {
      setManifest({});
      return;
    }
    let alive = true;
    getManifest(jobId)
      .then((m) => alive && setManifest(m))
      .catch(() => alive && setManifest({}));
    return () => {
      alive = false;
    };
  }, [jobId, manifestNonce]);

  useEffect(() => {
    esRef.current?.close();
    setRecord(null);
    setLines([]);
    if (!jobId) return;

    let cancelled = false;
    getJob(jobId).then((rec) => {
      if (!cancelled) setRecord(rec);
    });

    const es = streamJob(jobId, (ev) => {
      if (ev.type === "progress") {
        setRecord((prev) =>
          prev ? { ...prev, stage: ev.stage ?? prev.stage, pct: ev.pct ?? prev.pct } : prev
        );
      } else if (ev.type === "log") {
        setLines((prev) => [...prev, { id: nextId(), ts: ev.ts, text: ev.message ?? "", kind: "log" }]);
      } else {
        const terminal = terminalEventKind(ev.type);
        if (!terminal) return;

        if (terminalEventIsFailure(terminal)) {
          setLines((prev) => [
            ...prev,
            { id: nextId(), ts: ev.ts, text: ev.message ?? "job failed", kind: "error" },
          ]);
        } else if (terminal === "cancelled") {
          setLines((prev) => [
            ...prev,
            { id: nextId(), ts: ev.ts, text: "Job cancelled", kind: "log" },
          ]);
        }
        es.close();
        getJob(jobId).then((rec) => !cancelled && setRecord(rec));
        // The run just produced (or stopped producing) artifacts — re-read them.
        if (!cancelled) setManifestNonce((n) => n + 1);
      }
    });
    // Connection drop (not a terminal event) — native EventSource retries on
    // its own; refresh the snapshot in case the job finished while we were
    // disconnected, per the reconnect contract.
    es.onerror = () => {
      getJob(jobId).then((rec) => !cancelled && setRecord(rec));
    };
    esRef.current = es;

    return () => {
      cancelled = true;
      es.close();
    };
  }, [jobId]);

  async function handleCancel() {
    if (jobId) await cancelJob(jobId);
  }

  if (!jobId) {
    return (
      <Card className="pen-job-monitor pen-job-empty flex h-full items-center justify-center py-3">
        <p className="text-sm text-muted-foreground">Start a job or select one from the list.</p>
      </Card>
    );
  }

  const cancellable = record?.status === "queued" || record?.status === "running";
  // Cleanup is only offered once the worker can no longer be writing into the
  // tree. An unknown record is treated as live — refusing is the safe default.
  const terminal =
    record !== null && record.status !== "queued" && record.status !== "running";
  const facts = manifest.main_footage;

  return (
    <div className="pen-job-monitor flex h-full min-h-0 flex-col">
      <Card className="pen-job-progress">
        <CardHeader className="pen-job-monitor-heading">
          <div><span className="pen-eyebrow">Job #{jobId.slice(0, 8)}</span><CardTitle>{record?.spec?.command || "Loading job…"}</CardTitle></div>
          <div className="pen-job-stage-actions"><Button variant="secondary" disabled title="Retry is not supported by the job API">Retry <RotateCcw size={14} /></Button><Button disabled title="Stage approval is not supported by the job API">Approve stage <Check size={14} /></Button></div>
        </CardHeader>
        <CardContent className="pen-job-pipeline">
          <div className="pen-job-progress-label">
            <span>Pipeline progress</span>
            <span>{Math.round((record?.pct ?? 0) * 100)}% complete</span>
          </div>
          <Progress value={(record?.pct ?? 0) * 100} />
          <div className="pen-job-stages">{["Ingest", "Analyze", "Script", "Render", "Export"].map((stage, index) => <div key={stage} className={record?.stage?.toLowerCase() === stage.toLowerCase() ? "is-current" : ""}><span>{String(index + 1).padStart(2, "0")}</span><strong>{stage}</strong><small>{record?.stage?.toLowerCase() === stage.toLowerCase() ? "Current stage" : "Not reported"}</small></div>)}</div>
        </CardContent>
      </Card>
      <div className="pen-job-detail-columns">
        <section className="pen-job-review">
          <span className="pen-eyebrow"><ScanEye size={16} />Job details</span>
          <h3>{record?.stage || "Waiting for job state"}</h3>
          <p>{record?.error || "Inspect the current status and intervene when this run needs attention."}</p>
          {record && <StatusBadge status={record.status} />}
          <div className="pen-job-operational-actions">
            <Button variant="outline" size="sm" disabled={!cancellable} onClick={handleCancel}>Cancel</Button>
            <CleanupButton
              id={jobId}
              trigger="Delete artifacts"
              disabled={!terminal}
              disabledReason="The job is still running; finish or cancel it first"
              onCleanup={cleanupJob}
              onDone={() => setManifestNonce((n) => n + 1)}
            />
          </div>
          {(facts || record?.status === "succeeded") && <details className="pen-job-artifact-details"><summary>Outputs &amp; review</summary>
      {facts && (
        <Card className="gap-2 py-3">
          <CardHeader className="px-3">
            <CardTitle className="font-mono text-xs uppercase tracking-wide text-muted-foreground">
              Main footage plan
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3">
            <div className="space-y-1 text-xs text-muted-foreground" data-testid="main-footage-metrics">
              <div>
                plan {facts.active_plan_version} · mode {facts.planning_mode}
              </div>
              <div>
                coverage {pct(facts.coverage_actual)} of {pct(facts.coverage_target)} target ·{" "}
                {facts.coverage_sec.toFixed(1)}s of {facts.total_duration_sec.toFixed(1)}s
              </div>
              <div>
                {facts.beat_count} beats · {facts.cut_count} cuts · {facts.reuse_count} reuse ·{" "}
                {facts.candidate_count} candidates
              </div>
              <div className="font-mono">
                {Object.entries(facts.transitions)
                  .map(([kind, count]) => `${kind}×${count}`)
                  .join(" · ") || "no transitions"}
              </div>
              {facts.warnings.length > 0 && (
                <ul className="space-y-1">
                  {facts.warnings.map((code) => (
                    <li key={code}>{describeCode(code)}</li>
                  ))}
                </ul>
              )}
              <div>retained {formatBytes(facts.retained_bytes)}</div>
            </div>
          </CardContent>
        </Card>
      )}

      {record?.status === "succeeded" && jobId && <ReviewPanel jobId={jobId} />}
          </details>}
        </section>
      <div className="pen-job-activity min-h-0">
        <LogPane lines={lines} />
      </div>
      </div>
    </div>
  );
}
