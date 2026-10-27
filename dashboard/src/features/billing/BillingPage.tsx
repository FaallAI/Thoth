// Billing (DESIGN §8.10): the plan and its limits, stated honestly while billing is not live.
import { Hourglass } from "lucide-react";
import { useEffect, useState } from "react";

import { billingClient, BillingRequestError, type BillingClient, type BillingView } from "@/api/billing";
import { EmptyState, Skeleton } from "@/components/Feedback";
import { Button } from "@/components/ui/button";
import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";

/** Rp99.000: dots between thousands, fixed whatever the runtime's locale data says. */
const rupiah = (value: number) => `Rp${String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ".")}`;
const REFUSALS = new Set(["already_on_plan", "plan_active", "unknown_plan"]);

function refusal(failure: unknown): MessageKey {
  if (!(failure instanceof BillingRequestError)) return "billing.refusal.unavailable";
  if (failure.status === 403) return "billing.refusal.forbidden";
  return failure.code && REFUSALS.has(failure.code) ? (`billing.refusal.${failure.code}` as MessageKey) : "billing.refusal.unavailable";
}

function Limit({ label, used, allowed }: { label: string; used: number; allowed: number | null | undefined }) {
  const { number } = useLocale();
  const share = allowed ? Math.min(1, used / allowed) : 0;
  return (
    <div className="flex items-center gap-4 border-b border-hairline py-4 text-sm">
      <span className="flex-1 text-ink">{label}</span>
      {allowed ? (
        <span aria-hidden="true" className="h-1.5 w-40 overflow-hidden rounded-full bg-well max-sm:hidden">
          <span className="block h-full rounded-full bg-copper" style={{ width: `${share * 100}%` }} />
        </span>
      ) : null}
      <span className="w-28 text-right font-mono text-ink">
        {number(used)} / {allowed == null ? "∞" : number(allowed)}
      </span>
    </div>
  );
}

export function BillingPage({
  client = billingClient,
  navigate = (url: string) => window.location.assign(url),
}: { client?: Pick<BillingClient, "get" | "checkout">; navigate?: (url: string) => void }) {
  const { t, day } = useLocale();
  const [view, setView] = useState<BillingView | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [error, setError] = useState<MessageKey | null>(null);
  const load = () => client.get().then(setView, () => setLoadFailed(true));

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
    } catch (failure) {
      setError(refusal(failure));
    }
  }

  if (loadFailed && !view) return <EmptyState>{t("billing.error")}</EmptyState>;
  if (!view) return <Skeleton rows={4} />;
  if (view.unlimited) return <EmptyState>{t("billing.unlimited")}</EmptyState>;
  const live = Boolean(view.checkout_available);
  return (
    <div className="flex max-w-[1200px] flex-col gap-6">
      {!live && (
        <div role="status" className="flex gap-4 rounded-[10px] border-l-2 border-status-waiting bg-surface px-5 py-4">
          <Hourglass aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-status-waiting" />
          <div>
            <p className="font-semibold text-ink">{t("billing.notLiveTitle")}</p>
            <p className="text-sm text-muted-ink">{t("billing.notLiveBody")}</p>
          </div>
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section className="flex flex-col gap-4 rounded-[10px] bg-surface p-6">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-ink">{t("billing.currentPlan")}</span>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-raised px-2.5 py-0.5 text-ink">
              <span aria-hidden="true" className="size-2 rounded-full bg-status-done" />
              {t("billing.active")}
            </span>
          </div>
          <h2 className="text-2xl font-semibold text-ink">{view.plan?.name ?? t("billing.free")}</h2>
          <dl className="flex flex-col border-t border-hairline pt-2 text-sm">
            {view.period_end && (
              <div className="flex justify-between py-2">
                <dt className="text-muted-ink">{t("billing.periodEnds")}</dt>
                <dd className="text-ink">{day(view.period_end)}</dd>
              </div>
            )}
            <div className="flex justify-between py-2">
              <dt className="text-muted-ink">{t("billing.invoices")}</dt>
              <dd className="text-ink">{view.invoices.length > 0 ? view.invoices.length : t("billing.noInvoices")}</dd>
            </div>
          </dl>
          {!live && <p className="text-sm text-muted-ink">{t("billing.plansLater")}</p>}
        </section>
        <section className="rounded-[10px] bg-surface p-6">
          <h2 className="mb-2 text-base font-semibold text-ink">{t("billing.limits")}</h2>
          <Limit label={t("billing.workflows")} used={view.workflows_used} allowed={view.workflows_allowed} />
          <Limit label={t("billing.videos")} used={view.videos_used} allowed={view.videos_allowed} />
        </section>
      </div>
      {error && (
        <p role="alert" className="text-sm text-status-failed">
          {t(error)}
        </p>
      )}
      {live && (
        <section className="flex flex-col gap-3">
          <h2 className="text-base font-semibold text-ink">{t("billing.plans")}</h2>
          <ul className="grid gap-4 md:grid-cols-3">
            {view.plans.map((plan) => (
              <li key={plan.plan_id} className="flex flex-col gap-2 rounded-[10px] bg-surface p-5 text-sm">
                <strong className="text-base text-ink">{plan.name}</strong>
                <span className="text-ink">{t("billing.planPrice", { price: rupiah(plan.price_idr), days: plan.period_days ?? 30 })}</span>
                <span className="text-muted-ink">
                  {t("billing.planAllows", { workflows: plan.workflows_per_period, videos: plan.videos_per_period })}
                </span>
                {plan.plan_id === view.plan?.plan_id ? (
                  <span className="mt-2 text-muted-ink">{t("billing.currentPlan")}</span>
                ) : (
                  <Button className="mt-2" variant="secondary" onClick={() => void choose(plan.plan_id)}>
                    {t("billing.choose", { name: plan.name })}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {view.invoices.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-base font-semibold text-ink">{t("billing.invoices")}</h2>
          <ul className="flex flex-col divide-y divide-hairline rounded-[10px] bg-surface text-sm">
            {view.invoices.map((invoice) => (
              <li key={invoice.invoice_id} className="flex items-center justify-between px-5 py-3 text-ink">
                <span>{`${rupiah(invoice.amount_idr)} · ${invoice.status}`}</span>
                {invoice.invoice_url && (
                  <a className="text-copper underline" href={invoice.invoice_url}>
                    {t("billing.pay")}
                  </a>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
