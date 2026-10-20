import { useEffect, useState } from "react";

import { usageClient, type UsageClient, type UsageView } from "@/api/usage";

const megabytes = (bytes: number) => `${(bytes / 1_000_000).toFixed(1)} MB`;

export function UsagePage({ client = usageClient }: { client?: Pick<UsageClient, "get"> }) {
  const [usage, setUsage] = useState<UsageView | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    client.get().then(setUsage, () => setError(true));
  }, [client]);

  if (error) return <p role="alert" className="text-sm text-destructive">Usage could not be loaded. Try again.</p>;
  if (!usage) return <p className="text-sm text-muted-foreground">Loading usage…</p>;
  return (
    <div className="dashboard-usage">
      <section className="pen-recent-runs">
        <header><h2>{`This month (${usage.month})`}</h2></header>
        <dl className="dashboard-usage-totals">
          <dt>Workflows completed</dt><dd>{usage.workflows}</dd>
          <dt>Videos rendered</dt><dd>{usage.videos}</dd>
          <dt>Rendered time</dt><dd>{`${Math.round(usage.rendered_seconds)} s`}</dd>
          <dt>Media stored</dt><dd>{megabytes(usage.stored_bytes)}</dd>
        </dl>
      </section>
      <section className="pen-recent-runs">
        <header><h2>Source account sessions today</h2></header>
        <table>
          <thead><tr><th>Platform</th><th>Used today</th><th>Remaining</th></tr></thead>
          <tbody>
            {usage.quotas.map((quota) => (
              <tr key={quota.platform}>
                <td>{quota.platform}</td>
                <td>{quota.used_today}</td>
                <td>{quota.daily_leases === null ? "No limit" : `${quota.remaining_today} of ${quota.daily_leases}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs text-muted-foreground">Past the limit, workflows still run without signing in, and their report says so.</p>
      </section>
    </div>
  );
}
