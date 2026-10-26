// The account client's language save (restyle spec D1).
import { expect, test } from "bun:test";

import { AuthRequestError, createAuthClient } from "./auth";

test("a language is saved with PATCH /api/v1/me and the account comes back", async () => {
  const sent: Request[] = [];
  const client = createAuthClient(async (input, init) => {
    sent.push(new Request(new URL(String(input), "http://thoth.test"), init));
    return Response.json({ locale: "id", workspace_id: "ws_bootstrap" });
  });

  const me = await client.updateMe({ locale: "id" });

  expect(me.locale).toBe("id");
  expect(sent[0].method).toBe("PATCH");
  expect(new URL(sent[0].url).pathname).toBe("/api/v1/me");
  expect(await sent[0].json()).toEqual({ locale: "id" });
});

test("a refused save is the typed error with its code", async () => {
  const client = createAuthClient(async () => Response.json({ detail: "user_required" }, { status: 403 }));

  const failure = await client.updateMe({ locale: "en" }).catch((error: unknown) => error);

  expect(failure).toBeInstanceOf(AuthRequestError);
  expect((failure as AuthRequestError).code).toBe("user_required");
});
