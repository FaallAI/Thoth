import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ListFilter, Search } from "lucide-react";
import { listJobs, type JobRecord } from "@/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";

const POLL_MS = 3000;

/** Polls the job list and lets the operator pick which one JobMonitor watches. */
export function JobList({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      listJobs().then((js) => {
        if (!cancelled) setJobs(js.sort((a, b) => b.created_at.localeCompare(a.created_at)));
      });
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const metricsHost = document.getElementById("dashboard-legacy-metrics");
  const metrics = <div className="pen-legacy-metrics" aria-label="Job statistics">
    <div><i className="is-running" /><strong>{String(jobs.filter((job) => job.status === "running").length).padStart(2, "0")}</strong><span>Running</span></div>
    <div title="Review state is not included in the job list API"><i className="is-review" /><strong>—</strong><span>Needs review</span></div>
    <div><i className="is-queued" /><strong>{String(jobs.filter((job) => job.status === "queued").length).padStart(2, "0")}</strong><span>Queued</span></div>
    <div title="The API does not provide the time at which a job failed"><i className="is-failed" /><strong>—</strong><span>Failed today</span></div>
  </div>;
  const visibleJobs = jobs.filter((job) => (status === "all" || job.status === status) && `${job.id} ${job.spec.command} ${job.spec.url ?? ""}`.toLowerCase().includes(search.toLowerCase()));

  return (<>
    {metricsHost ? createPortal(metrics, metricsHost) : metrics}
    <Card className="pen-job-queue flex h-full flex-col gap-0">
      <CardHeader>
        <CardTitle>
          Job queue
        </CardTitle>
        <details className="pen-job-filter"><summary aria-label="Filter jobs"><ListFilter size={18} /></summary><select aria-label="Job status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="all">All jobs</option>{["running", "queued", "succeeded", "failed", "cancelled"].map((value) => <option key={value} value={value}>{value}</option>)}</select></details>
      </CardHeader>
      <div className="pen-job-search"><Search size={14} /><Input aria-label="Search jobs" placeholder="Search jobs" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
      <CardContent className="min-h-0 flex-1 px-0">
        <ScrollArea className="h-full px-3">
          {jobs.length === 0 && (
            <p className="px-1 py-4 text-sm text-muted-foreground">No jobs yet.</p>
          )}
          {jobs.length > 0 && visibleJobs.length === 0 && <p className="py-4 text-xs text-muted-foreground">No matching jobs.</p>}
          <ul className="pen-job-items">
            {visibleJobs.map((job) => (
              <li key={job.id}>
                <button
                  type="button"
                  onClick={() => onSelect(job.id)}
                  className={cn(
                    "pen-job-item",
                    job.id === selectedId && "is-selected"
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs text-foreground">
                      {job.spec.command}
                    </span>
                    <span className="pen-job-id">#{job.id.slice(0, 8)}</span>
                  </div>
                  <p className="pen-job-source">{job.spec.url || job.spec.content_set || new Date(job.created_at).toLocaleString()}</p>
                  <StatusBadge status={job.status} />
                </button>
              </li>
            ))}
          </ul>
        </ScrollArea>
      </CardContent>
    </Card>
  </>
  );
}
