import { useCallback, useEffect, useState } from "react";
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

function AccessCard({ group, available, onSave }: {
  group: PlatformAccounts;
  available: boolean;
  onSave: (mode: AccessMode, spacing: number) => Promise<void>;
}) {
  const [spacing, setSpacing] = useState(String(group.min_spacing_seconds));
  useEffect(() => setSpacing(String(group.min_spacing_seconds)), [group.min_spacing_seconds]);
  const parsed = Number(spacing);
  const spacingValid = spacing !== "" && Number.isInteger(parsed) && parsed >= 0 && parsed <= 86_400;
  const commitSpacing = () => {
    if (spacingValid && parsed !== group.min_spacing_seconds) void onSave(group.mode, parsed);
  };
  return <section className="sa-card sa-access" aria-label={`${platformLabel(group.platform)} access`}>
    <header><h2><KeyRound aria-hidden="true" />{platformLabel(group.platform)} access</h2><span>Accounts rotate when used</span></header>
    <div className="sa-access-grid">
      <div>
        <p className="sa-field-label" id="sa-mode-label">Access mode</p>
        <div className="sa-segmented" role="radiogroup" aria-labelledby="sa-mode-label">
          {MODES.map((mode) => <button key={mode.id} type="button" role="radio" aria-checked={group.mode === mode.id}
            disabled={!available} onClick={() => mode.id !== group.mode && void onSave(mode.id, group.min_spacing_seconds)}>
            {mode.id}</button>)}
        </div>
        <p className="sa-mode-hints">{MODES.map((mode) => `${mode.id}: ${mode.hint}`).join("   ·   ")}</p>
      </div>
      <div>
        <label className="sa-field-label" htmlFor="sa-spacing">Minimum spacing</label>
        <div className="sa-spacing">
          <Input id="sa-spacing" inputMode="numeric" value={spacing} disabled={!available} aria-invalid={!spacingValid}
            onChange={(event) => setSpacing(event.target.value.trim())} onBlur={commitSpacing}
            onKeyDown={(event) => event.key === "Enter" && commitSpacing()} />
          <span>seconds</span>
        </div>
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

  async function savePolicy(mode: AccessMode, spacing: number) {
    try {
      await client.setPolicy(platform, { mode, min_spacing_seconds: spacing });
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
      {available && group.mode !== "anonymous" && group.counts.healthy === 0 && <p role="status" className="sa-banner sa-banner--warning">
        <CircleAlert aria-hidden="true" />No healthy account. Acquisition on {platformLabel(platform)} runs anonymously.</p>}
      <section className="sa-card sa-counts" aria-label="Account status counts">
        {(Object.keys(STATUS_LABEL) as (keyof typeof STATUS_LABEL)[]).map((status) => <div key={status}>
          <i className={`sa-dot sa-dot--${status}`} aria-hidden="true" />
          <strong>{String(group.counts[status]).padStart(2, "0")}</strong><span>{STATUS_LABEL[status]}</span></div>)}
      </section>
      <section className="sa-card sa-table" aria-label="Accounts in rotation">
        <header><h2>Accounts in rotation</h2><span>{String(group.accounts.length).padStart(2, "0")} accounts</span></header>
        {group.accounts.length ? <table className="sa-accounts-table">
          <thead><tr>{["Label", "Status", "Proxy", "Cookies", "Earliest expiry", "Actions"].map((name) => <th key={name}>{name}</th>)}</tr></thead>
          <tbody>{group.accounts.map((account) => <tr key={account.id}>
            <td className="sa-label">{account.label}</td>
            <td><StatusCell account={account} /></td>
            <td>{account.proxy_display ?? "Direct"}</td>
            <td><div className="sa-chips">{account.cookie_names.map((name) => <span key={name}>{name}</span>)}</div></td>
            <td>{expiryText(account.cookies_earliest_expiry, now)}</td>
            <td><div className="sa-row-actions">
              <button type="button" disabled={testing !== null} onClick={() => test(account)}>{testing === account.id ? "Testing…" : "Test"}</button>
              <button type="button" onClick={() => setReimporting(account)}>Re-import</button>
              <button type="button" onClick={() => setEditing(account)}>Edit</button>
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
