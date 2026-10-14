import { useEffect, useRef, useState, type ReactNode } from "react";
import { LockKeyhole, Upload } from "lucide-react";
import { PenDialog } from "@/components/PenDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  PLATFORMS,
  REQUIRED_COOKIES,
  SourceAccountsRequestError,
  errorText,
  platformLabel,
  type CookieValidation,
  type SourceAccount,
  type SourceAccountsClient,
  type SourcePlatform,
  type SourceProxy,
} from "@/api/source-accounts";

const DIRECT = "direct";
const VALIDATE_DELAY_MS = 250;

function requiredCopy(platform: SourcePlatform): string {
  return `${platformLabel(platform)} requires ${REQUIRED_COOKIES[platform].join(" and ")}.`;
}

function failureText(error: unknown): string {
  if (error instanceof SourceAccountsRequestError && error.missing.length) {
    return `Missing ${error.missing.join(", ")}. Export cookies from a signed-in session.`;
  }
  return errorText(error);
}

function validationText(platform: SourcePlatform, result: CookieValidation): string {
  if (result.error === "missing_required_cookie") {
    return `Missing ${result.missing.join(", ")}. Export cookies from a signed-in ${platformLabel(platform)} session.`;
  }
  if (result.error === "all_cookies_expired") return "Every cookie in the export has expired.";
  if (result.error) return "The file is not a cookie export this page can read.";
  const expiry = result.earliest_expiry ? `; earliest expiry ${result.earliest_expiry.slice(0, 10)}` : "";
  return `Found ${result.count} cookies; ${result.names.join(", ")}${expiry}.`;
}

/** A cookie export from a file or a paste, validated by the server; values are never shown. */
function CookieInput({ platform, client, onChange }: {
  platform: SourcePlatform;
  client: SourceAccountsClient;
  onChange: (text: string, valid: boolean) => void;
}) {
  const [mode, setMode] = useState<"file" | "paste">("file");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [result, setResult] = useState<CookieValidation | null>(null);
  const [failed, setFailed] = useState(false);
  // The parent passes a fresh closure each render; only the export and platform revalidate.
  const report = useRef(onChange);
  report.current = onChange;

  useEffect(() => {
    if (!text) {
      setResult(null);
      report.current("", false);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      client.validate(platform, text).then(
        (validation) => {
          if (!live) return;
          setResult(validation);
          setFailed(false);
          report.current(text, validation.valid);
        },
        () => {
          if (!live) return;
          setResult(null);
          setFailed(true);
          report.current(text, false);
        },
      );
    }, VALIDATE_DELAY_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [text, platform, client]);

  return <div className="sa-cookie-input">
    <div className="sa-segmented" role="group" aria-label="Cookie source">
      {(["file", "paste"] as const).map((option) => <button key={option} type="button"
        aria-pressed={mode === option} onClick={() => setMode(option)}>
        {option === "file" ? "File" : "Paste"}</button>)}
    </div>
    {mode === "file" ? <label className="sa-dropzone">
      <Upload aria-hidden="true" />
      <strong>{fileName || "Choose cookie export file"}</strong>
      <small>JSON or Netscape format · cookie values stay hidden</small>
      <input type="file" accept=".txt,.json,text/plain,application/json" aria-label="Cookie export file"
        onChange={async (event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          setFileName(file.name);
          setText(await file.text());
        }} />
    </label> : <Textarea aria-label="Cookie export" className="sa-secret-text" placeholder="Paste the cookie export"
      value={text} onChange={(event) => { setFileName(""); setText(event.target.value); }} />}
    <p className="sa-field-hint">{requiredCopy(platform)}</p>
    {result && <p role="status" className={result.valid ? "sa-validation sa-validation--ok" : "sa-validation sa-validation--error"}>
      {validationText(platform, result)}</p>}
    {failed && <p role="alert" className="sa-validation sa-validation--error">The export could not be checked. Try again.</p>}
    <p className="sa-lock-note"><LockKeyhole aria-hidden="true" />Only cookie names and expiry are shown after import.</p>
  </div>;
}

/** Direct, or one pool proxy; a proxy another account holds is shown but cannot be chosen. */
function ProxySelect({ proxies, value, onChange, currentProxyId, currentDisplay, onImportProxies }: {
  proxies: SourceProxy[];
  value: string | null;
  onChange: (proxyId: string | null) => void;
  currentProxyId?: string | null;
  currentDisplay?: string | null;
  onImportProxies: () => void;
}) {
  const selected = proxies.find((proxy) => proxy.id === value);
  // A held proxy missing from the list (not loaded yet, or the list failed) still shows by name.
  const shown = selected?.display ?? (value ? (value === currentProxyId && currentDisplay) || "Unlisted proxy" : "Direct");
  return <div className="sa-field">
    <label htmlFor="sa-proxy">Proxy</label>
    <Select value={value ?? DIRECT} onValueChange={(next) => onChange(next === DIRECT ? null : String(next))}>
      <SelectTrigger id="sa-proxy" aria-label="Proxy" className="sa-select"><SelectValue>{shown}</SelectValue></SelectTrigger>
      <SelectContent>
        <SelectItem value={DIRECT}><span className="sa-option"><strong>Direct</strong><small>No proxy</small></span></SelectItem>
        {proxies.map((proxy) => {
          const held = proxy.account_label !== null && proxy.id !== currentProxyId;
          return <SelectItem key={proxy.id} value={proxy.id} disabled={held}>
            <span className="sa-option"><strong>{proxy.display}</strong>
              <small>{held ? `in use by ${platformLabel(proxy.account_platform ?? "")} · ${proxy.account_label}` : "Available"}</small></span>
          </SelectItem>;
        })}
      </SelectContent>
    </Select>
    {proxies.length ? <p className="sa-field-hint">Choose from the pool. One proxy per account.</p>
      : <p className="sa-field-hint">No proxies yet. <button type="button" className="sa-link" onClick={onImportProxies}>Import proxies first.</button></p>}
  </div>;
}

function Footer({ children }: { children: ReactNode }) {
  return <footer className="sa-dialog-footer">{children}</footer>;
}

export function AddAccountDialog({ open, onOpenChange, client, platform: initialPlatform, proxies, onSaved, onImportProxies }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  client: SourceAccountsClient;
  platform: SourcePlatform;
  proxies: SourceProxy[];
  onSaved: (account: SourceAccount) => void;
  onImportProxies: () => void;
}) {
  const [platform, setPlatform] = useState<SourcePlatform>(initialPlatform);
  const [label, setLabel] = useState("");
  const [proxyId, setProxyId] = useState<string | null>(null);
  const [cookies, setCookies] = useState({ text: "", valid: false });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setPlatform(initialPlatform);
      setLabel("");
      setProxyId(null);
      setCookies({ text: "", valid: false });
      setError("");
    }
  }, [open, initialPlatform]);

  async function save() {
    setSaving(true);
    setError("");
    try {
      onSaved(await client.create({ platform, label: label.trim(), cookies: cookies.text, proxy_id: proxyId }));
      onOpenChange(false);
    } catch (failure) {
      setError(failureText(failure));
    } finally {
      setSaving(false);
    }
  }

  return <PenDialog open={open} onOpenChange={onOpenChange} eyebrow="Source access" title="Add account"
    description="Import browser cookies from a session you signed in to." className="sa-dialog">
    <div className="sa-dialog-body">
      <div className="sa-field">
        <label htmlFor="sa-platform">Platform</label>
        <Select value={platform} onValueChange={(next) => setPlatform(next as SourcePlatform)}>
          <SelectTrigger id="sa-platform" aria-label="Platform" className="sa-select"><SelectValue>{platformLabel(platform)}</SelectValue></SelectTrigger>
          <SelectContent>{PLATFORMS.map((entry) => <SelectItem key={entry.id} value={entry.id}>{entry.label}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <div className="sa-field">
        <label htmlFor="sa-label">Account label</label>
        <Input id="sa-label" maxLength={64} placeholder="e.g. Cedar · primary" value={label} onChange={(event) => setLabel(event.target.value)} />
      </div>
      <ProxySelect proxies={proxies} value={proxyId} onChange={setProxyId} onImportProxies={onImportProxies} />
      <div className="sa-field">
        <span className="sa-field-label">Browser cookie export</span>
        <CookieInput key={`${open}`} platform={platform} client={client} onChange={(text, valid) => setCookies({ text, valid })} />
      </div>
      {error && <p role="alert" className="sa-validation sa-validation--error">{error}</p>}
    </div>
    <Footer>
      <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
      <Button disabled={saving || !label.trim() || !cookies.valid} onClick={save}>Import account</Button>
    </Footer>
  </PenDialog>;
}

export function ReimportDialog({ account, onOpenChange, client, onSaved }: {
  account: SourceAccount | null;
  onOpenChange: (open: boolean) => void;
  client: SourceAccountsClient;
  onSaved: (account: SourceAccount) => void;
}) {
  const [cookies, setCookies] = useState({ text: "", valid: false });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setCookies({ text: "", valid: false });
    setError("");
  }, [account?.id]);
  if (!account) return null;

  async function save() {
    if (!account) return;
    setSaving(true);
    setError("");
    try {
      onSaved(await client.reimport(account.id, cookies.text));
      onOpenChange(false);
    } catch (failure) {
      setError(failureText(failure));
    } finally {
      setSaving(false);
    }
  }

  return <PenDialog open onOpenChange={onOpenChange} eyebrow="Source access" title="Re-import cookies"
    description="Replace cookies for this account after signing in again." className="sa-dialog">
    <div className="sa-dialog-body">
      <div className="sa-field"><span className="sa-field-label">Account</span>
        <p className="sa-readonly">{platformLabel(account.platform)} · {account.label}</p></div>
      <div className="sa-field">
        <span className="sa-field-label">Browser cookie export</span>
        <CookieInput key={account.id} platform={account.platform} client={client} onChange={(text, valid) => setCookies({ text, valid })} />
      </div>
      {cookies.valid && <p className="sa-field-hint">Validation passed. Existing session is replaced on save.</p>}
      {error && <p role="alert" className="sa-validation sa-validation--error">{error}</p>}
    </div>
    <Footer>
      <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
      <Button disabled={saving || !cookies.valid} onClick={save}>Replace cookies</Button>
    </Footer>
  </PenDialog>;
}

export function EditAccountDialog({ account, onOpenChange, client, proxies, onSaved, onDeleted, onImportProxies }: {
  account: SourceAccount | null;
  onOpenChange: (open: boolean) => void;
  client: SourceAccountsClient;
  proxies: SourceProxy[];
  onSaved: (account: SourceAccount) => void;
  onDeleted: (accountId: string) => void;
  onImportProxies: () => void;
}) {
  const [label, setLabel] = useState(account?.label ?? "");
  const [proxyId, setProxyId] = useState<string | null>(account?.proxy_id ?? null);
  const [locale, setLocale] = useState(account?.locale ?? "");
  const [timezone, setTimezone] = useState(account?.timezone ?? "");
  const [confirming, setConfirming] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setLabel(account?.label ?? "");
    setProxyId(account?.proxy_id ?? null);
    setLocale(account?.locale ?? "");
    setTimezone(account?.timezone ?? "");
    setConfirming(false);
    setResetting(false);
    setError("");
  }, [account]);

  if (!account) return null;
  const disabled = account.status === "disabled";

  async function run(action: () => Promise<void>) {
    setSaving(true);
    setError("");
    try {
      await action();
    } catch (failure) {
      setError(failureText(failure));
    } finally {
      setSaving(false);
    }
  }

  const save = () => run(async () => {
    if (!account) return;
    onSaved(await client.update(account.id, {
      label: label.trim(),
      proxy_id: proxyId,
      ...(locale.trim() !== account.locale ? { locale: locale.trim() } : {}),
      ...(timezone.trim() !== account.timezone ? { timezone: timezone.trim() } : {}),
    }));
    onOpenChange(false);
  });
  const resetFingerprint = () => run(async () => {
    if (!account) return;
    onSaved(await client.update(account.id, { reset_fingerprint: true }));
    onOpenChange(false);
  });
  const toggle = () => run(async () => {
    if (!account) return;
    onSaved(await client.update(account.id, { disabled: !disabled }));
    onOpenChange(false);
  });
  const remove = () => run(async () => {
    if (!account) return;
    await client.remove(account.id);
    onDeleted(account.id);
    onOpenChange(false);
  });

  return <PenDialog open onOpenChange={onOpenChange} eyebrow="Account settings" title="Edit account"
    description="Update the label or choose a dedicated proxy." className="sa-dialog">
    <div className="sa-dialog-body">
      <div className="sa-field"><span className="sa-field-label">Platform</span>
        <p className="sa-readonly">{platformLabel(account.platform)}</p></div>
      <div className="sa-field">
        <label htmlFor="sa-edit-label">Account label</label>
        <Input id="sa-edit-label" maxLength={64} value={label} onChange={(event) => setLabel(event.target.value)} />
      </div>
      <ProxySelect proxies={proxies} value={proxyId} onChange={setProxyId} currentProxyId={account.proxy_id}
        currentDisplay={account.proxy_display} onImportProxies={onImportProxies} />
      <p className="sa-field-hint">A proxy can serve one account at a time.</p>
      <div className="sa-field">
        <label htmlFor="sa-edit-locale">Locale</label>
        <Input id="sa-edit-locale" maxLength={6} value={locale} onChange={(event) => setLocale(event.target.value)} />
      </div>
      <div className="sa-field">
        <label htmlFor="sa-edit-timezone">Timezone</label>
        <Input id="sa-edit-timezone" maxLength={64} value={timezone} onChange={(event) => setTimezone(event.target.value)} />
      </div>
      <p className="sa-field-hint">Match the proxy's country, for example id-ID and Asia/Jakarta.</p>
      <div className="sa-field"><span className="sa-field-label">Device fingerprint</span>
        <p className="sa-readonly">{account.fingerprint_set ? "Set (Camoufox)" : "Not set"}</p></div>
      {resetting
        ? <><p role="alert" className="sa-validation sa-validation--error">Reset the device of {account.label}? Its browser profiles and fingerprint are deleted, and its next lease shows the platform a new device.</p>
          <Button variant="destructive" disabled={saving} onClick={resetFingerprint}>Confirm reset</Button></>
        : <Button variant="ghost" disabled={saving} onClick={() => setResetting(true)}>Reset device fingerprint</Button>}
      {confirming && <p role="alert" className="sa-validation sa-validation--error">Delete {account.label}? Its cookies are removed and its proxy returns to the pool.</p>}
      {error && <p role="alert" className="sa-validation sa-validation--error">{error}</p>}
    </div>
    <Footer>
      <div className="sa-footer-secondary">
        <Button variant="ghost" disabled={saving} onClick={toggle}>{disabled ? "Enable account" : "Disable account"}</Button>
        {confirming
          ? <Button variant="destructive" disabled={saving} onClick={remove}>Delete account</Button>
          : <Button variant="ghost" disabled={saving} onClick={() => setConfirming(true)}>Delete</Button>}
      </div>
      <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
      <Button disabled={saving || !label.trim()} onClick={save}>Save changes</Button>
    </Footer>
  </PenDialog>;
}
