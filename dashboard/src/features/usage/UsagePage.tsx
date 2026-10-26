// Usage (DESIGN §8.10): this month's counts, bars per day, and today's source-account sessions.
import { useEffect, useState } from "react";

import { usageClient, type UsageClient, type UsageView } from "@/api/usage";
import { EmptyState, MetricTile, Skeleton } from "@/components/Feedback";
import { useLocale } from "@/lib/locale";
import { PLATFORM_NAMES } from "@/lib/platforms";

type Day = { day: number; value: number };
type UsageDay = NonNullable<UsageView["days"]>[number];

/** Every day of the month so far, with zeros where nothing happened. */
function monthDays(month: string, days: UsageView["days"], pick: (day: UsageDay) => number, today: Date): Day[] {
  const [year, number] = month.split("-").map(Number);
  const last = new Date(Date.UTC(year, number, 0)).getUTCDate();
  const current = today.getUTCFullYear() === year && today.getUTCMonth() + 1 === number;
  const values = new Map((days ?? []).map((item) => [Number(item.day.slice(8, 10)), pick(item)]));
  return Array.from({ length: current ? today.getUTCDate() : last }, (_, index) => ({ day: index + 1, value: values.get(index + 1) ?? 0 }));
}

/** Hand-drawn SVG bars (no chart library, restyle R4): the last day shown is the brightest. */
function Bars({ title, days, total }: { title: string; days: Day[]; total: string }) {
  const { t } = useLocale();
  const top = Math.max(1, ...days.map((item) => item.value));
  const width = 100 / Math.max(days.length, 1);
  const ticks = days.filter((_, index) => index === 0 || index === days.length - 1 || (index + 1) % 7 === 0);
  return (
    <figure className="flex flex-col gap-3 rounded-[10px] bg-surface p-5">
      <figcaption className="flex items-baseline justify-between text-sm">
        <span className="font-semibold text-ink">{title}</span>
        <span className="font-mono text-muted-ink">{t("usage.total", { count: total })}</span>
      </figcaption>
      <svg
        viewBox="0 0 100 40"
        preserveAspectRatio="none"
        className="h-32 w-full"
        role="img"
        aria-label={`${title}: ${days.map((item) => `${item.day}: ${item.value}`).join(", ")}`}
      >
        {days.map((item, index) => {
          const height = (item.value / top) * 38;
          return (
            <rect
              key={item.day}
              x={index * width + width * 0.15}
              y={40 - height}
              width={width * 0.7}
              height={height}
              rx={0.6}
              className={index === days.length - 1 ? "fill-copper" : "fill-copper/60"}
            />
          );
        })}
      </svg>
      <div className="relative h-4 font-mono text-[11px] text-faint">
        {ticks.map((item) => (
          <span key={item.day} className="absolute -translate-x-1/2" style={{ left: `${(item.day - 0.5) * width}%` }}>
            {item.day}
          </span>
        ))}
      </div>
    </figure>
  );
}

export function UsagePage({ client = usageClient, now }: { client?: Pick<UsageClient, "get">; now?: Date }) {
  const { t, number, duration } = useLocale();
  const [usage, setUsage] = useState<UsageView | null>(null);
  const [error, setError] = useState(false);
  const [today] = useState(() => now ?? new Date());

  useEffect(() => {
    client.get().then(setUsage, () => setError(true));
  }, [client]);

  if (error) return <EmptyState>{t("usage.error")}</EmptyState>;
  if (!usage) return <Skeleton rows={4} />;
  const megabytes = `${number(Math.round(usage.stored_bytes / 100_000) / 10)} MB`;
  const workflows = monthDays(usage.month, usage.days, (item) => item.workflows, today);
  const videos = monthDays(usage.month, usage.days, (item) => item.videos, today);
  return (
    <div className="flex max-w-[1200px] flex-col gap-8">
      <p className="-mt-4 text-sm text-muted-ink">{t("usage.subtitle", { month: usage.month })}</p>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricTile value={number(usage.workflows)} label={t("usage.workflows")} />
        <MetricTile value={number(usage.videos)} label={t("usage.videos")} />
        <MetricTile value={duration(usage.rendered_seconds)} label={t("usage.renderTime")} />
        <MetricTile value={megabytes} label={t("usage.stored")} />
      </div>
      {(usage.days ?? []).length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Bars title={t("usage.workflows")} days={workflows} total={number(usage.workflows)} />
          <Bars title={t("usage.videos")} days={videos} total={number(usage.videos)} />
        </div>
      ) : (
        <EmptyState>{t("usage.noDays")}</EmptyState>
      )}
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-base font-semibold text-ink">{t("usage.sessions")}</h2>
          <span className="text-sm text-muted-ink">{t("usage.pricesNote")}</span>
        </div>
        <table className="w-full border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-hairline text-[13px] text-muted-ink">
              <th className="py-3 pl-3 font-medium">{t("usage.col.platform")}</th>
              <th className="py-3 text-right font-medium">{t("usage.col.used")}</th>
              <th className="py-3 pr-3 text-right font-medium">{t("usage.col.left")}</th>
            </tr>
          </thead>
          <tbody>
            {usage.quotas.map((quota) => (
              <tr key={quota.platform} className="border-b border-hairline">
                <td className="py-3 pl-3 text-ink">{PLATFORM_NAMES[quota.platform] ?? quota.platform}</td>
                <td className="py-3 text-right font-mono text-ink">{number(quota.used_today)}</td>
                <td className="py-3 pr-3 text-right font-mono text-ink">
                  {quota.daily_leases == null
                    ? t("usage.noLimit")
                    : t("usage.leftOf", { left: number(quota.remaining_today ?? 0), limit: number(quota.daily_leases) })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs text-muted-ink">{t("usage.poolNote")}</p>
      </section>
    </div>
  );
}
