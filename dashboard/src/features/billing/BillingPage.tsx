import { useEffect, useState } from "react";

import { billingClient, type BillingClient, type BillingView } from "@/api/billing";
import { Button } from "@/components/ui/button";

/** Rp99.000: dots between thousands, fixed whatever the runtime's locale data says. */
const rupiah = (value: number) => `Rp${String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ".")}`;
const left = (used: number, allowed: number | null | undefined) => Math.max(0, (allowed ?? 0) - used);

export function BillingPage({
  client = billingClient,
  navigate = (url: string) => window.location.assign(url),
}: { client?: Pick<BillingClient, "get" | "checkout">; navigate?: (url: string) => void }) {
  const [view, setView] = useState<BillingView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => client.get().then(setView, () => setError("Billing could not be loaded. Try again."));

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  async function choose(planId: string) {
    setError(null);
    try {
      const made = await client.checkout(planId);
      if (made.invoice_url) navigate(made.invoice_url);
      else await load();
    } catch {
      setError("Checkout is not available right now. Try again later.");
    }
  }

  if (error && !view) return <p role="alert" className="text-sm text-destructive">{error}</p>;
  if (!view) return <p className="text-sm text-muted-foreground">Loading billing…</p>;
  if (view.unlimited) return <p>Unlimited (operator)</p>;
  return (
    <div className="dashboard-billing">
      <section className="pen-recent-runs">
        <header><h2>{`${view.plan?.name ?? "Free"} plan`}</h2></header>
        <p>{`${left(view.workflows_used, view.workflows_allowed)} of ${view.workflows_allowed} workflows left`}</p>
        <p>{`${left(view.videos_used, view.videos_allowed)} of ${view.videos_allowed} videos left`}</p>
        {view.period_end && (
          <p className="text-xs text-muted-foreground">{`This period ends on ${new Date(view.period_end).toLocaleDateString("id-ID")}`}</p>
        )}
      </section>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <section className="pen-recent-runs">
        <header><h2>Plans</h2></header>
        <ul>
          {view.plans.map((plan) => (
            <li key={plan.plan_id}>
              <strong>{plan.name}</strong>{" "}
              <span>{`${rupiah(plan.price_idr)} / ${plan.period_days} days`}</span>{" "}
              <span>{`${plan.workflows_per_period} workflows, ${plan.videos_per_period} videos`}</span>{" "}
              <Button type="button" variant="outline" onClick={() => void choose(plan.plan_id)}>{`Choose ${plan.name}`}</Button>
            </li>
          ))}
        </ul>
      </section>
      {view.invoices.length > 0 && (
        <section className="pen-recent-runs">
          <header><h2>Invoices</h2></header>
          <ul>
            {view.invoices.map((invoice) => (
              <li key={invoice.invoice_id}>
                {`${rupiah(invoice.amount_idr)} · ${invoice.status}`}{" "}
                {invoice.invoice_url && <a href={invoice.invoice_url}>Pay</a>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
