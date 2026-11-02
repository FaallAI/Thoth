import type { E2EConfig } from 'e2e';
import { web } from '@e2e-dev/web';
import { createAnthropic } from '@ai-sdk/anthropic';

// GLM 5.3 through z.ai's Anthropic-compatible Coding Plan endpoint. It reads the text snapshot
// only: it cannot see images, so vision stays off.
const zai = createAnthropic({
  baseURL: 'https://api.z.ai/api/anthropic/v1',
  apiKey: process.env.ZAI_API_KEY,
});

export default {
  targets: [
    // The dashboard behind the local stack; a read-scope developer token signs every request.
    // One target per audited width, so a live session opens at that width.
    ...([['web', 1280, 720, 'en-US'], ['w1440', 1440, 900, 'en-US'], ['w1024', 1024, 820, 'en-US'], ['w1024id', 1024, 820, 'id-ID'], ['w430', 430, 932, 'en-US']] as const).map(
      ([name, width, height, locale]) => ({
        name,
        engine: web({
          viewport: { width, height },
          locale,
          headers: { Authorization: `Bearer ${process.env.THOTH_DEV_TOKEN ?? ''}` },
        }),
        app: { url: process.env.THOTH_WEB_URL ?? 'http://127.0.0.1:8088' },
      }),
    ),
    // The same widths against a local vite dev server, to check a fix before it is deployed.
    ...([['dev1440', 1440, 900], ['dev1024', 1024, 820], ['dev430', 430, 932]] as const).map(([name, width, height]) => ({
      name,
      engine: web({
        viewport: { width, height },
        locale: 'en-US',
        headers: { Authorization: `Bearer ${process.env.THOTH_DEV_TOKEN ?? ''}` },
      }),
      app: { url: 'http://localhost:5199' },
    })),
    // Indonesian on the dev server: the language comes from the signed-in user, so the browser
    // rewrites that one answer. Nothing is saved.
    ...([['dev1440id', 1440, 900], ['dev1024id', 1024, 820], ['dev430id', 430, 932]] as const).map(([name, width, height]) => ({
      name,
      engine: web({
        viewport: { width, height },
        locale: 'id-ID',
        headers: { Authorization: `Bearer ${process.env.THOTH_DEV_TOKEN ?? ''}` },
        initScripts: [
          `(() => {
            const real = window.fetch;
            window.fetch = async (...args) => {
              const response = await real(...args);
              if (!String(args[0]?.url ?? args[0]).endsWith('/auth/me') || !response.ok) return response;
              const me = await response.clone().json();
              return new Response(JSON.stringify({ ...me, locale: 'id' }), { status: response.status, headers: response.headers });
            };
          })();`,
        ],
      }),
      app: { url: 'http://localhost:5199' },
    })),
  ],
  agents: { default: { model: zai('glm-5.3'), maxModelCalls: 15 } },
} satisfies E2EConfig;
