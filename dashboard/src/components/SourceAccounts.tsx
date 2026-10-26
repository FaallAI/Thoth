import { useCallback, useEffect, useState, type KeyboardEvent } from "react";
import { CircleAlert, Info, KeyRound, Network, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageActions } from "@/components/PageActions";
import { PlatformIcon } from "@/components/PlatformIcon";
import { AddAccountDialog, EditAccountDialog, ReimportDialog } from "@/components/SourceAccountDialogs";
import {
  PLATFORMS,
  errorKey,
  platformLabel,
  type AccessMode,
  type BrowserEngine,
  type PlatformAccounts,
  type SourceAccount,
  type SourceAccountsClient,
  type SourceAccountsOverview,
  type SourcePlatform,
  type SourceProxy,
} from "@/api/source-accounts";
import { formatClock, type MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";

const MODES: AccessMode[] = ["anonymous", "fallback", "always"];
// Spec 2026-10-13, 3.4: Camoufox is switched to only after the fingerprint comparison.
const ENGINES: BrowserEngine[] = ["patchright", "camoufox"];
// The server refuses Camoufox elsewhere (engine_unsupported): only Instagram's reels run it.
const CAMOUFOX_PLATFORMS = ["instagram"];
const MAX_BUDGET = 100_000;
const STATUSES = ["healthy", "cooldown", "expired", "disabled"] as const;
const STATUS_DOT = { healthy: "bg-status-done", cooldown: "bg-status-waiting", expired: "bg-status-failed", disabled: "bg-status-idle" };
const DAY_MS = 86_400_000;

type Policy = { mode: AccessMode; min_spacing_seconds: number; daily_budget: number; engine: BrowserEngine };

/** A whole number typed into the card, committed on blur or Enter when it is in range. */
function useNumberField(saved: number, max: number, commit: (value: number) => void) {
  const [text, setText] = useState(String(saved));
  useEffect(() => setText(String(saved)), [saved]);
  const parsed = Number(text);
  const valid = text !== "" && Number.isInteger(parsed) && parsed >= 0 && parsed <= max;
  const done = () => { if (valid && parsed !== saved) commit(parsed); };
  return {
    value: text,
    "aria-invalid": !valid,
    onChange: (event: { target: { value: string } }) => setText(event.target.value.trim()),
    onBlur: done,
    onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => { if (event.key === "Enter") done(); },
  };
}

function AccessCard({ group, available, onSave }: {
  group: PlatformAccounts;
  available: boolean;
  onSave: (policy: Policy) => Promise<void>;
}) {
  const { t } = useLocale();
  const save = (change: Partial<Policy>) => void onSave({ mode: group.mode,
    min_spacing_seconds: group.min_spacing_seconds, daily_budget: group.daily_budget, engine: group.engine, ...change });
  const spacing = useNumberField(group.min_spacing_seconds, 86_400, (value) => save({ min_spacing_seconds: value }));
  const budget = useNumberField(group.daily_budget, MAX_BUDGET, (value) => save({ daily_budget: value }));
  // Arrow keys move the choice like a native radio group; only the checked radio is tabbable.
  const stepper = <T extends string>(options: T[], current: T, pick: (id: T) => void) =>
    (event: KeyboardEvent<HTMLDivElement>) => {
      const delta = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
      if (!delta || !available) return;
      event.preventDefault();
      const index = (options.indexOf(current) + delta + options.length) % options.length;
      event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]')[index]?.focus();
      pick(options[index]);
    };
  const radios = <T extends string>(options: T[], current: T, pick: (id: T) => void, label: (id: T) => string) =>
    options.map((option) => <button key={option} type="button" role="radio" aria-checked={current === option}
      tabIndex={current === option ? 0 : -1}
      disabled={!available} onClick={() => option !== current && pick(option)}>
      {label(option)}</button>);
  const pickMode = (mode: AccessMode) => save({ mode });
  const pickEngine = (engine: BrowserEngine) => save({ engine });
  const name = platformLabel(group.platform);
  return <section className="sa-card sa-access" aria-label={t("sa.access", { platform: name })}>
    <header><h2><KeyRound aria-hidden="true" />{t("sa.access", { platform: name })}</h2><span>{t("sa.rotate")}</span></header>
    <div className="sa-access-grid">
      <div>
        <p className="sa-field-label" id="sa-mode-label">{t("sa.mode")}</p>
        <div className="sa-segmented" role="radiogroup" aria-labelledby="sa-mode-label"
          onKeyDown={stepper(MODES, group.mode, pickMode)}>
          {radios(MODES, group.mode, pickMode, (mode) => t(`sa.mode.${mode}`))}
        </div>
        <p className="sa-mode-hints">{MODES.map((mode) => `${t(`sa.mode.${mode}`)}: ${t(`sa.modeHint.${mode}`)}`).join("   ·   ")}</p>
      </div>
      <div>
        <label className="sa-field-label" htmlFor="sa-spacing">{t("sa.spacing")}</label>
        <div className="sa-spacing">
          <Input id="sa-spacing" inputMode="numeric" disabled={!available} {...spacing} />
          <span>{t("sa.seconds")}</span>
        </div>
      </div>
      {CAMOUFOX_PLATFORMS.includes(group.platform) && <div>
        <p className="sa-field-label" id="sa-engine-label">{t("sa.engine")}</p>
        <div className="sa-segmented" role="radiogroup" aria-labelledby="sa-engine-label"
          onKeyDown={stepper(ENGINES, group.engine, pickEngine)}>
          {radios(ENGINES, group.engine, pickEngine, (engine) => engine)}
        </div>
        <p className="sa-mode-hints">{ENGINES.map((engine) => `${engine}: ${t(`sa.engineHint.${engine}`)}`).join("   ·   ")}</p>
      </div>}
      <div>
        <label className="sa-field-label" htmlFor="sa-budget">{t("sa.budget")}</label>
        <div className="sa-spacing">
          <Input id="sa-budget" inputMode="numeric" disabled={!available} {...budget} />
          <span>{t("sa.leases")}</span>
        </div>
        <p className="sa-field-hint">{t("sa.budgetHint")}</p>
      </div>
    </div>
  </section>;
}

/** One account as DESIGN §8.9 lists it: health, a live cooldown, the proxy, today's leases and the last outcome. */
function AccountRow({ account, budget, now, testing, onTest, onReimport, onEdit }: {
  account: SourceAccount;
  budget: number;
  now: number;
  testing: string | null;
  onTest: () => void;
  onReimport: () => void;
  onEdit: () => void;
}) {
  const { t, plural, day } = useLocale();
  const left = account.cooldown_until ? (Date.parse(account.cooldown_until) - now) / 1_000 : 0;
  const expiry = account.cookies_earliest_expiry
    ? Math.ceil((Date.parse(account.cookies_earliest_expiry) - now) / DAY_MS)
    : null;
  const outcome = account.last_outcome ? t(`sa.outcome.${account.last_outcome}`) : t("sa.outcome.none");
  const bad = account.last_outcome !== null && account.last_outcome !== "success";
  return <tr className="border-b border-hairline">
    <td className="py-3 pl-3">
      <div className="flex items-center gap-3">
        <PlatformIcon platform={account.platform} className="size-5 text-ink" />
        <div>
          <p className="text-ink">{account.label}</p>
          <p className="text-xs text-muted-ink">{account.cookie_names.join(", ")}</p>
        </div>
      </div>
    </td>
    <td className="py-3">
      <span className="inline-flex items-center gap-1.5 rounded-full bg-raised px-2.5 py-0.5 text-[13px] whitespace-nowrap text-ink">
        <span aria-hidden="true" className={cn("size-2 rounded-full", STATUS_DOT[account.status])} />
        {t(`sa.status.${account.status}`)}
      </span>
    </td>
    <td className="py-3 font-mono text-[13px] text-status-waiting max-lg:hidden">{left > 0 ? formatClock(left) : <span className="text-faint">—</span>}</td>
    <td className="py-3 font-mono text-[13px] text-ink max-lg:hidden">{account.proxy_display ?? t("sa.direct")}</td>
    <td className="py-3 max-md:hidden">
      <span className="flex items-center gap-2 font-mono text-[13px] text-ink">
        {budget ? `${account.uses_today} / ${budget}` : String(account.uses_today)}
        {budget > 0 && <span aria-hidden="true" className="h-1 w-14 overflow-hidden rounded-full bg-well">
          <span className="block h-full rounded-full bg-copper" style={{ width: `${Math.min(100, (100 * account.uses_today) / budget)}%` }} />
        </span>}
      </span>
    </td>
    <td className={cn("py-3 text-[13px] max-md:hidden", bad ? "text-status-failed" : "text-ink")}>
      {outcome}{account.last_used_at ? ` · ${day(account.last_used_at)}` : ""}
    </td>
    <td className="py-3 text-[13px] text-muted-ink max-lg:hidden">
      {expiry === null ? t("sa.sessionOnly") : expiry <= 0 ? t("sa.cookiesExpired") : plural("sa.expiresIn", expiry)}
    </td>
    <td className="py-3 pr-3"><div className="sa-row-actions">
      <button type="button" disabled={testing !== null} aria-label={t("sa.testLabel", { label: account.label })}
        onClick={onTest}>{testing === account.id ? t("sa.testing") : t("sa.test")}</button>
      <button type="button" aria-label={t("sa.reimportLabel", { label: account.label })} onClick={onReimport}>{t("sa.reimport")}</button>
      <button type="button" aria-label={t("sa.editLabel", { label: account.label })} onClick={onEdit}>{t("sa.edit")}</button>
    </div></td>
  </tr>;
}

export function SourceAccounts({ client, onManageProxies }: {
  client: SourceAccountsClient;
  onManageProxies: () => void;
}) {
  const { t, plural } = useLocale();
  const [overview, setOverview] = useState<SourceAccountsOverview | null>(null);
  const [proxies, setProxies] = useState<SourceProxy[]>([]);
  const [platform, setPlatform] = useState<SourcePlatform>("tiktok");
  const [adding, setAdding] = useState(false);
  const [reimporting, setReimporting] = useState<SourceAccount | null>(null);
  const [editing, setEditing] = useState<SourceAccount | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [loadError, setLoadError] = useState<MessageKey | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await client.overview();
      setOverview(next);
      setProxies(next.available ? await client.proxies().catch(() => []) : []);
      setLoadError(null);
    } catch (failure) {
      setLoadError(errorKey(failure));
    }
  }, [client]);

  useEffect(() => { void load(); }, [load]);

  const available = overview?.available ?? false;
  const group = overview?.platforms.find((entry) => entry.platform === platform);
  // The cooldown column counts down while any account on this platform cools down.
  const cooling = group?.accounts.some((entry) => entry.cooldown_until !== null) ?? false;
  const now = useNow(1_000, cooling).getTime();
  // A cooldown that has run out is leasable again, as the store treats it.
  const usable = group?.accounts.some((entry) => entry.status === "healthy"
    || (entry.status === "cooldown" && entry.cooldown_until !== null && Date.parse(entry.cooldown_until) <= now));

  async function savePolicy(policy: Policy) {
    try {
      await client.setPolicy(platform, policy);
      await load();
    } catch (failure) {
      setNotice({ tone: "error", text: t(errorKey(failure)) });
    }
  }

  async function test(account: SourceAccount) {
    setTesting(account.id);
    try {
      const checked = await client.test(account.id);
      setNotice({ tone: checked.result === "expired" ? "error" : "ok", text: t(`sa.test.${checked.result}`, { label: account.label }) });
      await load();
    } catch (failure) {
      setNotice({ tone: "error", text: t(errorKey(failure)) });
    } finally {
      setTesting(null);
    }
  }

  const changed = () => { void load(); };

  return <div className="sa-page">
    <PageActions>
      <Button variant="secondary" onClick={onManageProxies}><Network aria-hidden="true" />{t("sa.manageProxies")}</Button>
      <Button disabled={!available} onClick={() => setAdding(true)}>{t("sa.add")}<Plus aria-hidden="true" /></Button>
    </PageActions>
    {loadError && <p role="alert" className="sa-banner sa-banner--error"><CircleAlert aria-hidden="true" />{t(loadError)}</p>}
    {overview && !available && <p role="status" className="sa-banner"><Info aria-hidden="true" />{t("sa.notConfigured")}</p>}
    <div className="sa-tabs" role="tablist" aria-label={t("sa.platforms")}>
      {PLATFORMS.map((entry) => <button key={entry.id} type="button" role="tab" aria-selected={platform === entry.id}
        onClick={() => setPlatform(entry.id)}>{entry.label}</button>)}
    </div>
    {notice && <p role="status" className={`sa-toast sa-toast--${notice.tone}`}>{notice.text}
      <button type="button" aria-label={t("sa.dismiss")} onClick={() => setNotice(null)}>×</button></p>}
    {group && <>
      <AccessCard group={group} available={available} onSave={savePolicy} />
      {available && group.mode !== "anonymous" && !usable && <p role="status" className="sa-banner sa-banner--warning">
        <CircleAlert aria-hidden="true" />{t("sa.noHealthy", { platform: platformLabel(platform) })}</p>}
      <section className="sa-card sa-counts" aria-label={t("sa.counts")}>
        {STATUSES.map((status) => <div key={status}>
          <i className={`sa-dot sa-dot--${status}`} aria-hidden="true" />
          <strong>{String(group.counts[status]).padStart(2, "0")}</strong><span>{t(`sa.status.${status}`)}</span></div>)}
      </section>
      <section className="sa-card sa-table" aria-label={t("sa.rotation")}>
        <header><h2>{t("sa.rotation")}</h2><span>{plural("sa.accountCount", group.accounts.length)}</span></header>
        {group.accounts.length ? <table className="w-full border-collapse text-left text-sm">
          <thead><tr className="border-b border-hairline text-[13px] text-muted-ink">
            <th className="py-3 pl-3 font-medium">{t("sa.col.label")}</th>
            <th className="py-3 font-medium">{t("sa.col.health")}</th>
            <th className="py-3 font-medium max-lg:hidden">{t("sa.col.cooldown")}</th>
            <th className="py-3 font-medium max-lg:hidden">{t("sa.col.proxy")}</th>
            <th className="py-3 font-medium max-md:hidden">{t("sa.col.leases")}</th>
            <th className="py-3 font-medium max-md:hidden">{t("sa.col.outcome")}</th>
            <th className="py-3 font-medium max-lg:hidden">{t("sa.col.cookies")}</th>
            <th className="py-3 pr-3 font-medium">{t("sa.col.actions")}</th>
          </tr></thead>
          <tbody>{group.accounts.map((account) => <AccountRow key={account.id} account={account} budget={group.daily_budget}
            now={now} testing={testing} onTest={() => void test(account)} onReimport={() => setReimporting(account)}
            onEdit={() => setEditing(account)} />)}</tbody>
        </table> : <div className="sa-empty">
          <strong>{t("sa.empty", { platform: platformLabel(platform) })}</strong>
          <p>{t("sa.emptyHint")}</p>
          <Button disabled={!available} onClick={() => setAdding(true)}>{t("sa.add")}<Plus aria-hidden="true" /></Button>
        </div>}
        <p className="sa-footnote"><Info aria-hidden="true" />{t("sa.testNote")}</p>
      </section>
    </>}
    <AddAccountDialog open={adding} onOpenChange={setAdding} client={client} platform={platform} proxies={proxies}
      onSaved={changed} onImportProxies={() => { setAdding(false); onManageProxies(); }} />
    <ReimportDialog account={reimporting} onOpenChange={(open) => !open && setReimporting(null)} client={client} onSaved={changed} />
    <EditAccountDialog account={editing} onOpenChange={(open) => !open && setEditing(null)} client={client} proxies={proxies}
      onSaved={changed} onDeleted={changed} onImportProxies={() => { setEditing(null); onManageProxies(); }} />
  </div>;
}
