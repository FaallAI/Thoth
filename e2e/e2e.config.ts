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
    {
      // The dashboard behind the local stack; a read-scope developer token signs every request.
      engine: web({ headers: { Authorization: `Bearer ${process.env.THOTH_DEV_TOKEN ?? ''}` } }),
      app: { url: process.env.THOTH_WEB_URL ?? 'http://127.0.0.1:8088' },
    },
  ],
  agents: { default: { model: zai('glm-5.3'), maxModelCalls: 15 } },
} satisfies E2EConfig;
