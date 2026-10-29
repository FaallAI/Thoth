import { test } from '@e2e-dev/web';
import { expect } from 'e2e';

// Read-only: these tests open screens and never press Assist's propose, apply or save, so no
// provider is called and no draft changes. Labels match both UI languages (en, id).
const DRAFT = process.env.THOTH_E2E_DRAFT ?? '';

test('a finished run opens its draft in Studio', async ({ app, agent, screen }) => {
  await app.open('/workflows');
  await agent.act('open the most recent finished run');
  await agent.act('open the draft this run made in Studio');
  await expect(screen.getByRole('button', /^(Story|Cerita)$/)).toBeVisible();
});

test('Story mode lists the beats of a draft', async ({ app, agent, screen }) => {
  await app.open(DRAFT);
  await agent.act('switch the editor to Story mode');
  await expect(screen.getByRole('toolbar', /^(Story beats|Beat cerita)$/)).toBeVisible();
});

// The toolbar's Assist button only shows the panel; a suggestion needs a second press, and the
// read-scope token would refuse that POST anyway.
test('Assist opens for the shown beat without sending a request', async ({ app, agent, screen }) => {
  await app.open(DRAFT);
  await agent.act('switch the editor to Story mode');
  await agent.act('open the Assist panel, without asking it for a suggestion');
  await expect(screen.getByRole('region', 'Assist')).toBeVisible();
});
