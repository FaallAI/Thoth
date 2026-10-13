import { useCallback, useEffect, useState, type KeyboardEvent } from "react";
import { CircleAlert, Info, KeyRound, Network, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageActions } from "@/components/PageActions";
import { AddAccountDialog, EditAccountDialog, ReimportDialog } from "@/components/SourceAccountDialogs";
import {
  PLATFORMS,
  errorText,
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

const MODES: { id: AccessMode; hint: string }[] = [
  { id: "anonymous", hint: "never use accounts" },
  { id: "fallback", hint: "when anonymous access is blocked" },
  { id: "always", hint: "whenever a healthy account exists" },
];
// Spec 2026-10-13, 3.4: Camoufox is switched to only after the fingerprint comparison.
const ENGINES: { id: BrowserEngine; hint: string }[] = [
  { id: "patchright", hint: "Chromium, the default" },
  { id: "camoufox", hint: "Firefox; switch after the fingerprint comparison" },
];
// The server refuses Camoufox elsewhere (engine_unsupported): only Instagram's reels run it.
const CAMOUFOX_PLATFORMS = ["instagram"];
const MAX_BUDGET = 100_000;
const STATUS_LABEL = { healthy: "healthy", cooldown: "cooling down", expired: "expired", disabled: "disabled" };
const DAY_MS = 86_400_000;

function expiryText(value: string | null, now: number): string {
  if (!value) return "session only";
  const days = Math.ceil((Date.parse(value) - now) / DAY_MS);
  return days <= 0 ? "expired" : `in ${days} day${days === 1 ? "" : "s"}`;
}

function clock(value: string): string {
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function StatusCell({ account }: { account: SourceAccount }) {
  return <div className="sa-status">
    <span className={`sa-badge sa-badge--${account.status}`}>{account.status}</span>
    {account.status === "cooldown" && account.cooldown_until && <small>until {clock(account.cooldown_until)}</small>}
    {account.status === "expired" && <small>re-import needed</small>}
  </div>;
}

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
  const save = (change: Partial<Policy>) => void onSave({ mode: group.mode,
    min_spacing_seconds: group.min_spacing_seconds, daily_budget: group.daily_budget, engine: group.engine, ...change });
  const spacing = useNumberField(group.min_spacing_seconds, 86_400, (value) => save({ min_spacing_seconds: value }));
  const budget = useNumberField(group.daily_budget, MAX_BUDGET, (value) => save({ daily_budget: value }));
  // Arrow keys move the choice like a native radio group; only the checked radio is tabbable.
  const stepper = <T extends string>(options: { id: T }[], current: T, pick: (id: T) => void) =>
    (event: KeyboardEvent<HTMLDivElement>) => {
      const delta = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
      if (!delta || !available) return;
      event.preventDefault();
      const index = (options.findIndex((option) => option.id === current) + delta + options.length) % options.length;
      event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]')[index]?.focus();
      pick(options[index].id);
    };
  const radios = <T extends string>(options: { id: T }[], current: T, pick: (id: T) => void) =>
    options.map((option) => <button key={option.id} type="button" role="radio" aria-checked={current === option.id}
      tabIndex={current === option.id ? 0 : -1}
      disabled={!available} onClick={() => option.id !== current && pick(option.id)}>
      {option.id}</button>);
  const pickMode = (mode: AccessMode) => save({ mode });
  const pickEngine = (engine: BrowserEngine) => save({ engine });
  return <section className="sa-card sa-access" aria-label={`${platformLabel(group.platform)} access`}>
    <header><h2><KeyRound aria-hidden="true" />{platformLabel(group.platform)} access</h2><span>Accounts rotate when used</span></header>
    <div className="sa-access-grid">
      <div>
        <p className="sa-field-label" id="sa-mode-label">Access mode</p>
        <div className="sa-segmented" role="radiogroup" aria-labelledby="sa-mode-label"
          onKeyDown={stepper(MODES, group.mode, pickMode)}>
          {radios(MODES, group.mode, pickMode)}
        </div>
        <p className="sa-mode-hints">{MODES.map((mode) => `${mode.id}: ${mode.hint}`).join("   ·   ")}</p>
      </div>
      <div>
        <label className="sa-field-label" htmlFor="sa-spacing">Minimum spacing</label>
        <div className="sa-spacing">
          <Input id="sa-spacing" inputMode="numeric" disabled={!available} {...spacing} />
          <span>seconds</span>
        </div>
      </div>
      {CAMOUFOX_PLATFORMS.includes(group.platform) && <div>
        <p className="sa-field-label" id="sa-engine-label">Browser engine</p>
        <div className="sa-segmented" role="radiogroup" aria-labelledby="sa-engine-label"
          onKeyDown={stepper(ENGINES, group.engine, pickEngine)}>
          {radios(ENGINES, group.engine, pickEngine)}
        </div>
        <p className="sa-mode-hints">{ENGINES.map((engine) => `${engine.id}: ${engine.hint}`).join("   ·   ")}</p>
      </div>}
      <div>
        <label className="sa-field-label" htmlFor="sa-budget">Daily budget</label>
        <div className="sa-spacing">
          <Input id="sa-budget" inputMode="numeric" disabled={!available} {...budget} />
          <span>leases</span>
        </div>
        <p className="sa-field-hint">Per account, per UTC day. 0 means unlimited.</p>
      </div>
    </div>
  </section>;
}

export function SourceAccounts({ client, onManageProxies }: {
  client: SourceAccountsClient;
  onManageProxies: () => void;
}) {
  const [overview, setOverview] = useState<SourceAccountsOverview | null>(null);
  const [proxies, setProxies] = useState<SourceProxy[]>([]);
  const [platform, setPlatform] = useState<SourcePlatform>("tiktok");
  const [adding, setAdding] = useState(false);
  const [reimporting, setReimporting] = useState<SourceAccount | null>(null);
  const [editing, setEditing] = useState<SourceAccount | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [loadError, setLoadError] = useState("");

  const load = useCallback(async () => {
    try {
      const next = await client.overview();
      setOverview(next);
      setProxies(next.available ? await client.proxies().catch(() => []) : []);
      setLoadError("");
    } catch (failure) {
      setLoadError(errorText(failure));
    }
  }, [client]);

  useEffect(() => { void load(); }, [load]);

  const available = overview?.available ?? false;
  const group = overview?.platforms.find((entry) => entry.platform === platform);
  const now = Date.now();
  // A cooldown that has run out is leasable again, as the store treats it.
  const usable = group?.accounts.some((entry) => entry.status === "healthy"
    || (entry.status === "cooldown" && entry.cooldown_until !== null && Date.parse(entry.cooldown_until) <= now));

  async function savePolicy(policy: Policy) {
    try {
      await client.setPolicy(platform, policy);
      await load();
    } catch (failure) {
      setNotice({ tone: "error", text: errorText(failure) });
    }
  }

  async function test(account: SourceAccount) {
    setTesting(account.id);
    try {
      const checked = await client.test(account.id);
      const text = { valid: "Session valid", expired: "Session expired", inconclusive: "Check inconclusive. Try again later." }[checked.result];
      setNotice({ tone: checked.result === "expired" ? "error" : "ok", text: `${account.label}: ${text}` });
      await load();
    } catch (failure) {
      setNotice({ tone: "error", text: errorText(failure) });
    } finally {
      setTesting(null);
    }
  }

  const changed = () => { void load(); };

  return <div className="sa-page">
    <PageActions>
      <Button variant="secondary" onClick={onManageProxies}><Network aria-hidden="true" />Manage proxies</Button>
      <Button disabled={!available} onClick={() => setAdding(true)}>Add account<Plus aria-hidden="true" /></Button>
    </PageActions>
    {loadError && <p role="alert" className="sa-banner sa-banner--error"><CircleAlert aria-hidden="true" />{loadError}</p>}
    {overview && !available && <p role="status" className="sa-banner"><Info aria-hidden="true" />
      Source accounts are not configured on this server. Acquisition runs anonymously, and accounts cannot be added.</p>}
    <div className="sa-tabs" role="tablist" aria-label="Platforms">
      {PLATFORMS.map((entry) => <button key={entry.id} type="button" role="tab" aria-selected={platform === entry.id}
        onClick={() => setPlatform(entry.id)}>{entry.label}</button>)}
    </div>
    {notice && <p role="status" className={`sa-toast sa-toast--${notice.tone}`}>{notice.text}
      <button type="button" aria-label="Dismiss" onClick={() => setNotice(null)}>×</button></p>}
    {group && <>
      <AccessCard group={group} available={available} onSave={savePolicy} />
      {available && group.mode !== "anonymous" && !usable && <p role="status" className="sa-banner sa-banner--warning">
        <CircleAlert aria-hidden="true" />No healthy account. Acquisition on {platformLabel(platform)} runs anonymously.</p>}
      <section className="sa-card sa-counts" aria-label="Account status counts">
        {(Object.keys(STATUS_LABEL) as (keyof typeof STATUS_LABEL)[]).map((status) => <div key={status}>
          <i className={`sa-dot sa-dot--${status}`} aria-hidden="true" />
          <strong>{String(group.counts[status]).padStart(2, "0")}</strong><span>{STATUS_LABEL[status]}</span></div>)}
      </section>
      <section className="sa-card sa-table" aria-label="Accounts in rotation">
        <header><h2>Accounts in rotation</h2><span>{String(group.accounts.length).padStart(2, "0")} accounts</span></header>
        {group.accounts.length ? <table className="sa-accounts-table">
          <thead><tr>{["Label", "Status", "Today", "Proxy", "Cookies", "Earliest expiry", "Actions"].map((name) => <th key={name}>{name}</th>)}</tr></thead>
          <tbody>{group.accounts.map((account) => <tr key={account.id}>
            <td className="sa-label">{account.label}</td>
            <td><StatusCell account={account} /></td>
            <td>{group.daily_budget ? `${account.uses_today} / ${group.daily_budget}` : String(account.uses_today)}</td>
            <td>{account.proxy_display ?? "Direct"}</td>
            <td><div className="sa-chips">{account.cookie_names.map((name) => <span key={name}>{name}</span>)}</div></td>
            <td>{expiryText(account.cookies_earliest_expiry, now)}</td>
            <td><div className="sa-row-actions">
              <button type="button" disabled={testing !== null} aria-label={`Test session for ${account.label}`}
                onClick={() => test(account)}>{testing === account.id ? "Testing…" : "Test"}</button>
              <button type="button" aria-label={`Re-import cookies for ${account.label}`}
                onClick={() => setReimporting(account)}>Re-import</button>
              <button type="button" aria-label={`Edit ${account.label}`} onClick={() => setEditing(account)}>Edit</button>
            </div></td>
          </tr>)}</tbody>
        </table> : <div className="sa-empty">
          <strong>No {platformLabel(platform)} accounts yet</strong>
          <p>Sign in with a normal browser, export its cookies with an extension such as Cookie-Editor, then import the file here.</p>
          <Button disabled={!available} onClick={() => setAdding(true)}>Add account<Plus aria-hidden="true" /></Button>
        </div>}
        <p className="sa-footnote"><Info aria-hidden="true" />Test session sends one live request to the platform.</p>
      </section>
    </>}
    <AddAccountDialog open={adding} onOpenChange={setAdding} client={client} platform={platform} proxies={proxies}
      onSaved={changed} onImportProxies={() => { setAdding(false); onManageProxies(); }} />
    <ReimportDialog account={reimporting} onOpenChange={(open) => !open && setReimporting(null)} client={client} onSaved={changed} />
    <EditAccountDialog account={editing} onOpenChange={(open) => !open && setEditing(null)} client={client} proxies={proxies}
      onSaved={changed} onDeleted={changed} onImportProxies={() => { setEditing(null); onManageProxies(); }} />
  </div>;
}
