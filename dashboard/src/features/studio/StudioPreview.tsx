import { Player } from "@remotion/player";
import { useEffect, useState, type ComponentProps, type ReactNode } from "react";
import { Maximize, Minimize, Pause, Play, Volume2, VolumeX } from "lucide-react";

import type { ControlPlaneClient, EditDocument } from "@/api/control-plane";
import type { PreviewSources } from "./AdvancedTimelineComposition";
import { getPlayerConfig, previewComposition } from "./preview";
import type { PlayerTimelineRef } from "./usePlayerTimeline";

type Props = {
  document?: EditDocument;
  embedded?: boolean;
  client?: Pick<ControlPlaneClient, "getEditDocument">;
  projectId?: string;
  documentId?: string;
  onBack?: () => void;
  /** Same-origin preview paths, kept out of the document so they never persist. */
  previewSources?: PreviewSources;
  /** Receives the Player React commits, and null when it goes away. */
  onPlayer?: (player: PlayerTimelineRef | null) => void;
  onPreviewUnavailable?: (assetId: string) => void;
  /** Drawn over the canvas itself (Story's safe zone); the player then keeps the canvas's shape. */
  overlay?: ReactNode;
};

export function StudioPreview({
  document,
  embedded = false,
  client,
  projectId,
  documentId,
  onBack,
  previewSources,
  onPlayer,
  onPreviewUnavailable,
  overlay,
}: Props) {
  const [loadedDocument, setLoadedDocument] = useState<EditDocument | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (document || !client || !projectId || !documentId) return;
    let active = true;
    setLoadedDocument(null);
    setFailed(false);
    void client
      .getEditDocument(projectId, documentId)
      .then((value) => active && setLoadedDocument(value))
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
  }, [attempt, client, document, documentId, projectId]);

  const currentDocument = document ?? loadedDocument;

  // Remotion types the Player ref by its own PlayerRef; this view only drives the
  // timeline subset of it. A callback ref reports the instance React committed.
  const ref = onPlayer as unknown as ComponentProps<typeof Player>["ref"];

  const preview = currentDocument ? (
    <div
      className="min-h-0 flex-1 overflow-auto rounded border border-border bg-black p-4"
      // With an overlay the canvas box is sized from this box's own width and height.
      style={overlay === undefined ? undefined : { containerType: "size" }}
    >
      {embedded ? <span className="studio-preview-badge">{currentDocument.canvas.width === 1080 && currentDocument.canvas.height === 1920 ? "9:16" : `${currentDocument.canvas.width}:${currentDocument.canvas.height}`} · {currentDocument.canvas.width}×{currentDocument.canvas.height}</span> : null}
      {overlay === undefined ? player() : (
        <div
          className="relative mx-auto"
          style={{
            aspectRatio: `${currentDocument.canvas.width} / ${currentDocument.canvas.height}`,
            // The largest canvas-shaped box that fits, so the overlay sits on the canvas exactly.
            width: `min(100cqw, calc(100cqh * ${currentDocument.canvas.width} / ${currentDocument.canvas.height}))`,
          }}
        >
          {player()}
          {overlay}
        </div>
      )}
    </div>
  ) : (
    <p className="text-sm text-muted-foreground">Loading Studio preview…</p>
  );

  function player() {
    if (!currentDocument) return null;
    return (
      <Player
        ref={ref}
        // The Player ties component and inputProps together through one generic;
        // previewComposition already pairs them correctly.
        {...(previewComposition(currentDocument, previewSources, onPreviewUnavailable) as {
          component: never;
          inputProps: never;
        })}
        controls
        spaceKeyToPlayOrPause
        renderPlayPauseButton={({ playing }) => playing ? <Pause size={15} /> : <Play size={15} />}
        renderMuteButton={({ muted }) => muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
        renderFullscreenButton={({ isFullscreen }) => isFullscreen ? <Minimize size={14} /> : <Maximize size={14} />}
        className="mx-auto max-h-full max-w-full"
        style={{ width: "100%", height: "100%" }}
        {...getPlayerConfig(currentDocument)}
      />
    );
  }

  if (embedded) return <section className="flex min-h-0 flex-1 flex-col" aria-label="Studio preview">{preview}<p className="studio-preview-hint">Space to play/pause · Click scenes to jump</p></section>;

  return (
    <section className="flex min-h-0 flex-1 flex-col gap-4 p-4" aria-label="Studio preview">
      <div className="flex items-center justify-between">
        <button type="button" className="text-sm text-muted-foreground underline" onClick={onBack}>
          Back to Content Set
        </button>
        <span className="font-mono text-xs text-muted-foreground">Read-only preview</span>
      </div>
      {failed ? (
        <div role="alert" className="space-y-3 text-sm text-destructive">
          <p>Could not load Studio preview.</p>
          <button type="button" className="underline" onClick={() => setAttempt((value) => value + 1)}>
            Retry
          </button>
        </div>
      ) : (
        preview
      )}
    </section>
  );
}
