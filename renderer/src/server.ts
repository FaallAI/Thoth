/**
 * One installation, one active render, one private dispatch surface.
 *
 * This is not a queue: the renderer holds exactly one execution object, and a
 * second request for a different job is refused outright rather than parked.
 * Nothing here retries, schedules, or remembers a backlog; the control plane
 * owns durability, and this service owns only the render it is running now.
 *
 * Every reply is a fixed code. A path, a command, a stream, or an exception
 * message never leaves this module, in an event or in a response.
 */

import { createHash, timingSafeEqual } from "node:crypto";

import type { DispatchClaim, ExpectedOutput, OutputFacts } from "./artifact-root";
import { ArtifactPathInvalid, ArtifactUnavailable, RendererArtifactRoot, probeWithFfprobe } from "./artifact-root";
import type { RendererConfig } from "./config";
import { loadRendererConfig } from "./config";
import type { RenderBundleAsset } from "./contracts";
import { expectedOutputOf, parseRenderBundle } from "./contracts";
import { ControlPlaneClient } from "./control-plane-client";
import { compositionInputProps, createRemotionEngine } from "./remotion-adapter";

export type RenderStatus =
  | "preparing"
  | "rendering"
  | "finalizing"
  | "completed"
  | "failed"
  | "cancelled";

export type RenderFailureCode =
  | "render_asset_unavailable"
  | "render_bundle_invalid"
  | "render_deadline_exceeded"
  | "render_engine_failed"
  | "render_output_invalid";

/** Exactly the Task 1 event JSON: identity, sequence, status, and safe facts. */
export type RenderEvent = {
  render_job_id: string;
  dispatch_id: string;
  sequence: number;
  status: RenderStatus;
  progress_percent?: number;
  /** What the job is doing now; run-progress spec G6. */
  render_stage?: RenderStage;
  rendered_frames?: number;
  encoded_frames?: number;
  total_frames?: number;
  failure_code?: RenderFailureCode;
  output?: OutputFacts;
  occurred_at: string;
};

export type RenderStage = "preparing" | "rendering" | "encoding" | "uploading";

/** One engine progress report: the overall percent and the frame counts behind it. */
export type EngineProgress = {
  readonly percent: number;
  readonly renderedFrames: number;
  readonly encodedFrames: number;
  readonly totalFrames: number;
};

export type EngineRequest = {
  readonly outDir: string;
  readonly publicDir: string;
  readonly outputPath: string;
  readonly compositionId: string;
  readonly inputProps: Record<string, unknown>;
  readonly expected: ExpectedOutput;
  readonly onProgress: (progress: EngineProgress) => void;
  readonly signal: AbortSignal;
};

export type RenderEngine = {
  render(request: EngineRequest): Promise<void>;
};

export type ControlPlanePort = {
  fetchBundle(renderJobId: string): Promise<unknown>;
  fetchAsset(
    renderJobId: string,
    assetId: string,
    signal?: AbortSignal,
  ): Promise<ReadableStream<Uint8Array>>;
  uploadOutput(renderJobId: string, path: string, signal?: AbortSignal): Promise<void>;
  publishEvent(event: RenderEvent): Promise<void>;
};

export type ArtifactPort = {
  /** Declare this dispatch started, or report that some process already did. */
  claimDispatch(renderJobId: string, dispatchId: string): Promise<DispatchClaim>;
  prepare(renderJobId: string): Promise<void>;
  receiveAsset(
    renderJobId: string,
    asset: RenderBundleAsset,
    body: ReadableStream<Uint8Array>,
  ): Promise<void>;
  removeAssets(renderJobId: string): Promise<void>;
  verifyStagedAssets(renderJobId: string, assets: readonly RenderBundleAsset[]): Promise<void>;
  assetsDirectory(renderJobId: string): string;
  bundleDirectory(renderJobId: string): string;
  temporaryOutput(renderJobId: string): string;
  removeTemporaryOutput(renderJobId: string): Promise<void>;
  verifyTemporaryOutput(renderJobId: string, expected: ExpectedOutput): Promise<OutputFacts>;
};

/**
 * Degradation this service survives but should still be seen. Each is a fixed
 * identifier: the original exception, its path, and its output stay here.
 */
export type RendererWarning =
  | "render_event_publish_failed"
  | "render_temporary_output_cleanup_failed";

export type ExecutionDeps = {
  readonly config: RendererConfig;
  readonly client: ControlPlanePort;
  readonly artifacts: ArtifactPort;
  readonly engine: RenderEngine;
  readonly now: () => Date;
  readonly warn: (code: RendererWarning) => void;
};

export type ActiveRender = { readonly render_job_id: string; readonly dispatch_id: string };

export type RendererExecution = {
  start(renderJobId: string, dispatchId: string): Promise<void>;
  cancel(renderJobId: string): Promise<void>;
  status(): { active: ActiveRender | null };
  /** Resolve once the render this service owns has finished reporting. */
  whenIdle(): Promise<void>;
};

export class RendererBusy extends Error {
  readonly code = "render_busy";

  constructor() {
    super("render busy");
    this.name = "RendererBusy";
  }
}

/** Identical to the control plane's `OpaqueId`: one safe segment, never a path. */
const IDENTIFIER = /^[A-Za-z][A-Za-z0-9_-]{0,127}$/;
/** Report at most once a second, not every frame: progress is a signal, not a stream. */
const PROGRESS_INTERVAL_MS = 1_000;
type AbortReason = "cancel" | "deadline";
type Stage = "preparing" | "rendering" | "finalizing";

export function createExecution(deps: ExecutionDeps): RendererExecution {
  let active: ActiveRender | null = null;
  let running: Promise<void> | null = null;
  let controller: AbortController | null = null;
  let reason: AbortReason | null = null;

  async function execute(renderJobId: string, dispatchId: string): Promise<void> {
    let sequence = 0;
    let terminal = false;
    let reported = -1;
    let reportedAt = 0;
    let reportedStage: RenderStage = "rendering";
    let stage: Stage = "preparing";
    const signal = controller!.signal;

    const publish = async (
      status: RenderStatus,
      extra: Partial<RenderEvent> = {},
    ): Promise<void> => {
      if (terminal) {
        return;
      }
      sequence += 1;
      const event: RenderEvent = {
        render_job_id: renderJobId,
        dispatch_id: dispatchId,
        sequence,
        status,
        occurred_at: deps.now().toISOString(),
        ...extra,
      };
      // The control plane's own deadline closes a job it stops hearing about,
      // so an undeliverable report is warned about rather than raised.
      await safely(deps, "render_event_publish_failed", () => deps.client.publishEvent(event));
    };

    try {
      // A cancellation that landed while the dispatch was still being claimed
      // is already final: nothing is fetched and no browser is ever launched.
      signal.throwIfAborted();
      await publish("preparing", { render_stage: "preparing" });

      // The bundle must be this job's, this dispatch's, and this build's, or
      // nothing is prepared, no browser is launched, and no output is written.
      const bundle = parseRenderBundle(await deps.client.fetchBundle(renderJobId), {
        renderJobId,
        dispatchId,
        rendererVersion: deps.config.rendererVersion,
      });
      await deps.artifacts.prepare(renderJobId);
      // The renderer shares no volume with the control plane: every input comes over
      // the private route and is checked against the bundle before it is used.
      for (const asset of bundle.assets) {
        try {
          const body = await deps.client.fetchAsset(renderJobId, asset.asset_id, signal);
          await deps.artifacts.receiveAsset(renderJobId, asset, body);
        } catch {
          // A missing input is the asset's failure, never the bundle's.
          throw new ArtifactUnavailable();
        }
      }
      await deps.artifacts.verifyStagedAssets(renderJobId, bundle.assets);

      const expected = expectedOutputOf(bundle);

      stage = "rendering";
      reported = 0;
      reportedAt = deps.now().getTime();
      await publish("rendering", { progress_percent: 0, render_stage: "rendering" });

      // A cancel that arrived during preparation must not start a browser.
      if (signal.aborted) {
        throw new Error("render aborted");
      }
      await deps.engine.render({
        outDir: deps.artifacts.bundleDirectory(renderJobId),
        publicDir: deps.artifacts.assetsDirectory(renderJobId),
        outputPath: deps.artifacts.temporaryOutput(renderJobId),
        compositionId: bundle.composition_id,
        inputProps: compositionInputProps(bundle),
        expected,
        signal,
        onProgress: (progress: EngineProgress) => {
          if (terminal || !Number.isFinite(progress.percent)) {
            return;
          }
          const bounded = Math.round(progress.percent);
          if (bounded < 0 || bounded > 100 || bounded <= reported) {
            return;
          }
          // Every frame is rendered once the encoder is the one still catching up.
          const renderStage: RenderStage =
            progress.renderedFrames < progress.totalFrames ? "rendering" : "encoding";
          const at = deps.now().getTime();
          const due =
            at - reportedAt >= PROGRESS_INTERVAL_MS ||
            renderStage !== reportedStage ||
            bounded === 100;
          if (!due) {
            return;
          }
          reported = bounded;
          reportedAt = at;
          reportedStage = renderStage;
          void publish("rendering", {
            progress_percent: bounded,
            render_stage: renderStage,
            rendered_frames: progress.renderedFrames,
            encoded_frames: progress.encodedFrames,
            total_frames: progress.totalFrames,
          });
        },
      });
      if (signal.aborted) {
        throw new Error("render aborted");
      }

      stage = "finalizing";
      // Finalizing verifies the file and uploads it to the control plane.
      await publish("finalizing", { render_stage: "uploading" });
      const output = await deps.artifacts.verifyTemporaryOutput(renderJobId, expected);
      // The control plane stores the file and checks it against these facts on publish;
      // a failed upload stays in this stage, so it closes as render_output_invalid.
      await deps.client.uploadOutput(
        renderJobId,
        deps.artifacts.temporaryOutput(renderJobId),
        signal,
      );

      terminal = true;
      sequence += 1;
      // The render itself succeeded; losing the report degrades visibility, not
      // the result, so it is warned about rather than turned into a failure.
      await safely(deps, "render_event_publish_failed", () =>
        deps.client.publishEvent({
          render_job_id: renderJobId,
          dispatch_id: dispatchId,
          sequence,
          status: "completed",
          output,
          occurred_at: deps.now().toISOString(),
        }),
      );
      // The render lives in the store now: the local output and inputs are not kept.
      await safely(deps, "render_temporary_output_cleanup_failed", () =>
        deps.artifacts.removeTemporaryOutput(renderJobId),
      );
      await safely(deps, "render_temporary_output_cleanup_failed", () =>
        deps.artifacts.removeAssets(renderJobId),
      );
    } catch (error) {
      const closing = closingEvent(stage, error, reason);
      terminal = true;
      sequence += 1;
      await safely(deps, "render_temporary_output_cleanup_failed", () =>
        deps.artifacts.removeTemporaryOutput(renderJobId),
      );
      await safely(deps, "render_temporary_output_cleanup_failed", () =>
        deps.artifacts.removeAssets(renderJobId),
      );
      await safely(deps, "render_event_publish_failed", () =>
        deps.client.publishEvent({
          render_job_id: renderJobId,
          dispatch_id: dispatchId,
          sequence,
          status: closing.status,
          ...(closing.failure_code ? { failure_code: closing.failure_code } : {}),
          occurred_at: deps.now().toISOString(),
        }),
      );
    }
  }

  return {
    async start(renderJobId: string, dispatchId: string): Promise<void> {
      if (!IDENTIFIER.test(renderJobId) || !IDENTIFIER.test(dispatchId)) {
        throw new RendererBusy();
      }
      // A redelivered start of the dispatch this service is running now is the
      // same request, and is already being answered.
      if (active?.render_job_id === renderJobId && active.dispatch_id === dispatchId) {
        return;
      }
      // Any other identity is refused outright rather than parked.
      if (active) {
        throw new RendererBusy();
      }

      // Hold the slot across the claim so no second identity can take it while
      // the filesystem decides, and give it back untouched unless this start
      // turns out to be the one that may run. A dispatch some process already
      // claimed is accepted and dropped: no bundle, no engine, no event, and
      // no output, whether that process was this one or the one before it.
      active = { render_job_id: renderJobId, dispatch_id: dispatchId };
      // The slot is cancellable from the moment it is taken, so a cancel that
      // arrives while the filesystem is still deciding is observed, not lost.
      controller = new AbortController();
      reason = null;
      const abandon = (): void => {
        active = null;
        controller = null;
        reason = null;
      };

      let claim: DispatchClaim;
      try {
        claim = await deps.artifacts.claimDispatch(renderJobId, dispatchId);
      } catch (error) {
        abandon();
        // A claim that cannot be taken fails closed: nothing is started, and
        // the caller sees the artifact failure's fixed message, never a path.
        throw error;
      }
      if (claim === "replay") {
        abandon();
        return;
      }

      // The deadline is the render's own, so it starts once a render may begin
      // and is never spent waiting for the claim.
      const deadline = setTimeout(() => {
        reason = "deadline";
        controller?.abort();
      }, deps.config.deadlineSeconds * 1000);

      running = (async () => {
        try {
          await execute(renderJobId, dispatchId);
        } finally {
          clearTimeout(deadline);
          active = null;
          controller = null;
          running = null;
        }
      })();
    },

    async cancel(renderJobId: string): Promise<void> {
      if (active?.render_job_id !== renderJobId) {
        return;
      }
      reason = "cancel";
      controller?.abort();
    },

    status(): { active: ActiveRender | null } {
      return { active };
    },

    whenIdle(): Promise<void> {
      return running ?? Promise.resolve();
    },
  };
}

function closingEvent(
  stage: Stage,
  error: unknown,
  reason: AbortReason | null,
): { status: RenderStatus; failure_code?: RenderFailureCode } {
  if (reason === "cancel") {
    return { status: "cancelled" };
  }
  if (reason === "deadline") {
    return { status: "failed", failure_code: "render_deadline_exceeded" };
  }
  if (stage === "preparing") {
    const missing = error instanceof ArtifactUnavailable || error instanceof ArtifactPathInvalid;
    return {
      status: "failed",
      failure_code: missing ? "render_asset_unavailable" : "render_bundle_invalid",
    };
  }
  return {
    status: "failed",
    failure_code: stage === "rendering" ? "render_engine_failed" : "render_output_invalid",
  };
}

/**
 * Run a step the render survives without, and say so when it did not work.
 *
 * Only the fixed identifier escapes: the caught value never reaches the sink,
 * so a path, a credential, or a process stream cannot ride out inside it.
 */
async function safely(
  deps: ExecutionDeps,
  code: RendererWarning,
  action: () => Promise<unknown>,
): Promise<void> {
  try {
    await action();
  } catch {
    try {
      deps.warn(code);
    } catch {
      // A sink that throws must not take the render down with it.
    }
  }
}

/** Compare the shared internal credential without revealing its length. */
export function credentialMatches(expected: string, provided: string | null): boolean {
  if (provided === null) {
    return false;
  }
  // Both sides become one 32-byte SHA-256 digest, so the compared width is
  // always the same however short or long a caller's header is, and neither
  // value is ever branched on, echoed, or logged.
  return timingSafeEqual(digest(expected), digest(provided));
}

function digest(value: string): Buffer {
  return createHash("sha256").update(value, "utf8").digest();
}

const DISPATCH_ROUTE = /^\/internal\/render-jobs\/([^/]+)\/(start|cancel)$/;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

export function createFetchHandler(
  execution: RendererExecution,
  credential: string,
): (request: Request) => Promise<Response> {
  return async (request: Request): Promise<Response> => {
    const url = new URL(request.url);
    // Every route, health included, proves it is the control plane first, and
    // every rejection is the same fixed reply whatever was wrong with it.
    const header = request.headers.get("Authorization");
    const presented = header?.startsWith("Bearer ") ? header.slice("Bearer ".length) : null;
    if (!credentialMatches(credential, presented)) {
      return json(401, { code: "renderer_unauthorized" });
    }

    if (request.method === "GET" && url.pathname === "/health") {
      return json(200, { status: "ok" });
    }

    const route = request.method === "POST" ? DISPATCH_ROUTE.exec(url.pathname) : null;
    if (!route) {
      return json(404, { code: "renderer_route_unknown" });
    }
    const [, renderJobId, action] = route as unknown as [string, string, "start" | "cancel"];
    if (!IDENTIFIER.test(renderJobId)) {
      return json(422, { code: "renderer_request_invalid" });
    }

    if (action === "cancel") {
      await execution.cancel(renderJobId);
      return json(202, { accepted: true });
    }

    const dispatchId = await dispatchIdentity(request);
    if (dispatchId === null) {
      return json(422, { code: "renderer_request_invalid" });
    }
    try {
      await execution.start(renderJobId, dispatchId);
    } catch (error) {
      if (error instanceof RendererBusy) {
        return json(409, { code: "render_busy" });
      }
      return json(422, { code: "renderer_request_invalid" });
    }
    return json(202, { accepted: true });
  };
}

/** A start carries one bounded dispatch identity and nothing else. */
async function dispatchIdentity(request: Request): Promise<string | null> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return null;
  }
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return null;
  }
  const keys = Object.keys(body);
  const dispatchId = (body as { dispatch_id?: unknown }).dispatch_id;
  if (keys.length !== 1 || typeof dispatchId !== "string" || !IDENTIFIER.test(dispatchId)) {
    return null;
  }
  return dispatchId;
}

if (import.meta.main) {
  const config = loadRendererConfig(process.env);
  const execution = createExecution({
    config,
    client: new ControlPlaneClient({
      baseUrl: config.controlPlaneUrl,
      credential: config.credential,
    }),
    artifacts: new RendererArtifactRoot(config.artifactRoot, { probe: probeWithFfprobe }),
    engine: createRemotionEngine(),
    now: () => new Date(),
    // One bounded identifier on the container's own stream, and nothing else.
    warn: (code) => console.warn(`renderer_degraded ${code}`),
  });

  Bun.serve({
    port: config.port,
    // The renderer is reachable only on the private network, never published.
    hostname: "0.0.0.0",
    fetch: createFetchHandler(execution, config.credential),
  });
}
