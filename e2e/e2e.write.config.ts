import type { E2EConfig } from 'e2e';
import { web } from '@e2e-dev/web';
import { readFileSync } from 'node:fs';

// Write-scope runs. The token is short-lived and read from a file outside the repo; the throwaway
// project's id sits beside it. No model is configured here, so an agent step cannot run.
const beside = (name: string, env?: string) =>
  readFileSync(env ?? new URL(`../../${name}`, import.meta.url), 'utf8').trim();
const TOKEN = beside('e2e-write-token', process.env.THOTH_E2E_WRITE_TOKEN_FILE);
const PROJECT = beside('e2e-write-project', process.env.THOTH_E2E_WRITE_PROJECT_FILE);

// The browser refuses every write except a preview capability and the throwaway project's own
// routes, and never lets a voice, a model or a run start, whatever a test or a stray click does.
const WRITE_GUARD = `(() => {
  const project = ${JSON.stringify(PROJECT)};
  const real = window.fetch;
  window.__e2eBlocked = [];
  window.fetch = (input, init) => {
    const method = String(init?.method ?? input?.method ?? 'GET').toUpperCase();
    const path = new URL(input?.url ?? input, location.href).pathname;
    const reading = method === 'GET' || method === 'HEAD';
    const preview = method === 'POST' && path.endsWith('/preview-capability');
    const paid = /\\/(narration|assist|workflows|studio-imports|proposals)(\\/|$)/.test(path);
    const own = path.startsWith('/api/v1/projects/' + project + '/') && !paid;
    if (reading || preview || own) return real(input, init);
    window.__e2eBlocked.push(method + ' ' + path);
    return Promise.resolve(new Response(JSON.stringify({ detail: { code: 'e2e_write_guard' } }), { status: 403, headers: { 'Content-Type': 'application/json' } }));
  };
})();`;

const AS_INDONESIAN = `(() => {
  const real = window.fetch;
  window.fetch = async (...args) => {
    const response = await real(...args);
    if (!String(args[0]?.url ?? args[0]).endsWith('/auth/me') || !response.ok) return response;
    const me = await response.clone().json();
    return new Response(JSON.stringify({ ...me, locale: 'id' }), { status: response.status, headers: response.headers });
  };
})();`;

export default {
  tests: ['tests/**/*.e2e.ts', 'tests-write/**/*.e2e.ts'],
  // `rw*` is the deployed stack; `rwdev*` is the branch's dashboard from a vite dev server against it.
  targets: ([
    ['rw1440', 1440, 900, 'en-US', 'http://127.0.0.1:8088'],
    ['rw1440id', 1440, 900, 'id-ID', 'http://127.0.0.1:8088'],
    // A phone (Tier 3a): menu-only editing by long press.
    ['rw430', 430, 932, 'en-US', 'http://127.0.0.1:8088'],
    ['rwdev1440', 1440, 900, 'en-US', 'http://localhost:5199'],
    ['rwdev1440id', 1440, 900, 'id-ID', 'http://localhost:5199'],
  ] as const).map(([name, width, height, locale, url]) => ({
    name,
    engine: web({
      viewport: { width, height },
      locale,
      headers: { Authorization: `Bearer ${TOKEN}` },
      initScripts: locale === 'id-ID' ? [WRITE_GUARD, AS_INDONESIAN] : [WRITE_GUARD],
    }),
    app: { url },
  })),
} satisfies E2EConfig;
