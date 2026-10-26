// Developer tokens (DESIGN §8.10): a list, a create dialog that shows the secret once, and revoke.
import { Dialog } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { useEffect, useState, type SyntheticEvent } from "react";

import { authClient, AuthRequestError, type AuthClient, type CreatedToken, type TokenView } from "@/api/auth";
import { ConfirmDialog } from "@/components/Feedback";
import { Button } from "@/components/ui/button";
import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";

type TokensClient = Pick<AuthClient, "listTokens" | "createToken" | "revokeToken">;
const KNOWN = new Set(["token_limit", "user_required", "insufficient_scope"]);
const FIELD = "h-11 w-full rounded-md border border-hairline bg-well px-3 text-sm text-ink";

function message(failure: unknown): MessageKey {
  return failure instanceof AuthRequestError && failure.code && KNOWN.has(failure.code)
    ? (`tokens.error.${failure.code}` as MessageKey)
    : "tokens.error.load";
}

export function TokensPage({ client = authClient }: { client?: TokensClient }) {
  const { t, day } = useLocale();
  const [tokens, setTokens] = useState<TokenView[]>([]);
  const [error, setError] = useState<MessageKey | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"read" | "write" | "admin">("write");
  const [days, setDays] = useState(90);
  const [created, setCreated] = useState<CreatedToken | null>(null);
  const [revoking, setRevoking] = useState<TokenView | null>(null);

  const load = () => client.listTokens().then(setTokens, (failure) => setError(message(failure)));
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  async function create(event: SyntheticEvent) {
    event.preventDefault();
    setError(null);
    try {
      setCreated(await client.createToken({ name: name.trim(), scope, days }));
      setName("");
      await load();
    } catch (failure) {
      setError(message(failure));
    }
  }

  async function revoke(token: TokenView) {
    try {
      await client.revokeToken(token.token_id);
      await load();
    } catch (failure) {
      setError(message(failure));
    }
  }

  const close = (open: boolean) => {
    setCreating(open);
    if (!open) setCreated(null);
  };

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-ink">{t("page.tokens")}</h2>
          <p className="text-sm text-muted-ink">{t("settings.tokensHint")}</p>
        </div>
        <Button variant="secondary" size="lg" onClick={() => setCreating(true)}>
          {t("tokens.create")}
        </Button>
      </div>
      {error && !creating && (
        <p role="alert" className="text-sm text-status-failed">
          {t(error)}
        </p>
      )}
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-hairline text-[13px] text-muted-ink">
            <th className="py-3 pl-3 font-medium">{t("tokens.col.name")}</th>
            <th className="py-3 font-medium max-md:hidden">{t("tokens.col.access")}</th>
            <th className="py-3 font-medium max-md:hidden">{t("tokens.col.lastUsed")}</th>
            <th className="py-3 font-medium max-md:hidden">{t("tokens.col.expires")}</th>
            <th className="py-3 pr-3" />
          </tr>
        </thead>
        <tbody>
          {tokens.map((token) => (
            <tr key={token.token_id} className="border-b border-hairline">
              <td className="py-3 pl-3">
                <p className="text-ink">{token.name}</p>
                <p className="font-mono text-xs text-faint">{`${token.prefix}…`}</p>
              </td>
              <td className="py-3 text-ink max-md:hidden">{t(`tokens.${token.scope}` as MessageKey)}</td>
              <td className="py-3 text-ink max-md:hidden">{token.last_used_at ? day(token.last_used_at) : t("tokens.never")}</td>
              <td className="py-3 text-ink max-md:hidden">{day(token.expires_at)}</td>
              <td className="py-3 pr-3 text-right">
                <Button variant="ghost" aria-label={t("tokens.revokeLabel", { name: token.name })} className="text-status-failed" onClick={() => setRevoking(token)}>
                  {t("tokens.revoke")}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!tokens.length && !error && <p className="text-sm text-muted-ink">{t("tokens.empty")}</p>}

      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(open) => !open && setRevoking(null)}
        title={t("tokens.revokeTitle", { name: revoking?.name ?? "" })}
        description={t("tokens.revokeBody")}
        confirmLabel={t("tokens.revoke")}
        cancelLabel={t("tokens.keep")}
        danger
        onConfirm={() => revoking && void revoke(revoking)}
      />

      <Dialog.Root open={creating} onOpenChange={close}>
        <Dialog.Portal>
          <Dialog.Backdrop className="fixed inset-0 bg-black/60" />
          <Dialog.Popup className="fixed top-1/2 left-1/2 w-[min(520px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 rounded-[10px] bg-raised p-6 shadow-xl">
            <div className="mb-5 flex items-center justify-between">
              <Dialog.Title className="text-base font-semibold text-ink">{t(created ? "tokens.new" : "tokens.create")}</Dialog.Title>
              <Dialog.Close aria-label={t("common.close")} className="grid size-8 place-items-center rounded-md text-muted-ink hover:bg-surface">
                <X className="size-4" />
              </Dialog.Close>
            </div>
            {created ? (
              <div className="flex flex-col gap-3" aria-live="polite">
                <label htmlFor="new-token" className="text-sm text-ink">
                  {t("tokens.new")}
                </label>
                <div className="flex gap-2">
                  <input id="new-token" readOnly value={created.secret} onFocus={(event) => event.target.select()} className={`${FIELD} font-mono`} />
                  <Button variant="secondary" size="lg" onClick={() => void navigator.clipboard?.writeText(created.secret)}>
                    {t("tokens.copy")}
                  </Button>
                </div>
                <p className="text-sm text-status-waiting">{t("tokens.once")}</p>
              </div>
            ) : (
              <form className="flex flex-col gap-4" onSubmit={(event) => void create(event)}>
                <label className="flex flex-col gap-2 text-sm text-ink">
                  {t("tokens.name")}
                  <input autoFocus value={name} maxLength={100} onChange={(event) => setName(event.target.value)} className={FIELD} />
                </label>
                <div className="grid gap-4 sm:grid-cols-2">
                  <label className="flex flex-col gap-2 text-sm text-ink">
                    {t("tokens.access")}
                    <select value={scope} onChange={(event) => setScope(event.target.value as typeof scope)} className={FIELD}>
                      <option value="read">{t("tokens.read")}</option>
                      <option value="write">{t("tokens.write")}</option>
                      <option value="admin">{t("tokens.admin")}</option>
                    </select>
                  </label>
                  <label className="flex flex-col gap-2 text-sm text-ink">
                    {t("tokens.expires")}
                    <select value={days} onChange={(event) => setDays(Number(event.target.value))} className={FIELD}>
                      {[30, 90, 180, 365].map((value) => (
                        <option key={value} value={value}>
                          {t("tokens.days", { days: value })}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                {error && (
                  <p role="alert" className="text-sm text-status-failed">
                    {t(error)}
                  </p>
                )}
                <div className="flex justify-end gap-2 border-t border-hairline pt-4">
                  <Dialog.Close render={<Button variant="ghost" size="lg" />}>{t("common.cancel")}</Dialog.Close>
                  <Button type="submit" size="lg" disabled={!name.trim()}>
                    {t("tokens.create")}
                  </Button>
                </div>
              </form>
            )}
          </Dialog.Popup>
        </Dialog.Portal>
      </Dialog.Root>
    </section>
  );
}
