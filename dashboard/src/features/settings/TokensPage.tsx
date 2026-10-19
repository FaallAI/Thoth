import { useEffect, useState, type FormEvent } from "react";

import { authClient, AuthRequestError, type AuthClient, type CreatedToken, type TokenView } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { formatWhen } from "@/lib/format-time";

type TokensClient = Pick<AuthClient, "listTokens" | "createToken" | "revokeToken">;
const ERRORS: Record<string, string> = {
  token_limit: "You have 20 active tokens. Revoke one to create another.",
  user_required: "Developer tokens belong to a signed-in account.",
  insufficient_scope: "Managing tokens needs a signed-in session or an admin token.",
};
const message = (failure: unknown) =>
  (failure instanceof AuthRequestError && failure.code && ERRORS[failure.code]) || "Tokens could not be loaded. Try again.";

export function TokensPage({ client = authClient }: { client?: TokensClient }) {
  const [tokens, setTokens] = useState<TokenView[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"read" | "write" | "admin">("write");
  const [days, setDays] = useState(90);
  const [created, setCreated] = useState<CreatedToken | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = () => client.listTokens().then(setTokens, (failure) => setError(message(failure)));
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  async function create(event: FormEvent) {
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
    setConfirming(null);
    try {
      await client.revokeToken(token.token_id);
      await load();
    } catch (failure) {
      setError(message(failure));
    }
  }

  return (
    <div className="dashboard-tokens">
      <form className="pen-recent-runs dashboard-token-form" onSubmit={(event) => void create(event)}>
        <label htmlFor="token-name">Token name</label>
        <input id="token-name" value={name} maxLength={100} onChange={(event) => setName(event.target.value)} />
        <label htmlFor="token-scope">Access</label>
        <select id="token-scope" value={scope} onChange={(event) => setScope(event.target.value as typeof scope)}>
          <option value="read">Read only</option>
          <option value="write">Read and write</option>
          <option value="admin">Admin (can manage tokens)</option>
        </select>
        <label htmlFor="token-days">Expires after</label>
        <select id="token-days" value={days} onChange={(event) => setDays(Number(event.target.value))}>
          {[30, 90, 180, 365].map((value) => <option key={value} value={value}>{`${value} days`}</option>)}
        </select>
        <Button type="submit" disabled={!name.trim()}>Create token</Button>
      </form>
      {created && (
        <section className="pen-recent-runs dashboard-token-created" aria-live="polite">
          <label htmlFor="new-token">New token</label>
          <input id="new-token" readOnly value={created.secret} onFocus={(event) => event.target.select()} />
          <Button type="button" variant="outline" onClick={() => void navigator.clipboard?.writeText(created.secret)}>Copy</Button>
          <p>Copy it now. It is not shown again.</p>
        </section>
      )}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <section className="pen-recent-runs">
        <header><h2>Your tokens</h2></header>
        <div className="pen-runs-table">
          <table>
            <thead><tr>{["Name", "Token", "Access", "Last used", "Expires", ""].map((heading) => <th key={heading}>{heading}</th>)}</tr></thead>
            <tbody>
              {tokens.map((token) => (
                <tr key={token.token_id}>
                  <td>{token.name}</td>
                  <td>{`${token.prefix}…`}</td>
                  <td>{token.scope}</td>
                  <td>{token.last_used_at ? formatWhen(token.last_used_at) : "Never"}</td>
                  <td>{formatWhen(token.expires_at)}</td>
                  <td>
                    {confirming === token.token_id ? (
                      <Button type="button" variant="destructive" aria-label={`Confirm revoke ${token.name}`} onClick={() => void revoke(token)}>Confirm</Button>
                    ) : (
                      <Button type="button" variant="outline" aria-label={`Revoke ${token.name}`} onClick={() => setConfirming(token.token_id)}>Revoke</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!tokens.length && !error && <p className="pen-empty-runs">No developer tokens yet.</p>}
        </div>
      </section>
    </div>
  );
}
