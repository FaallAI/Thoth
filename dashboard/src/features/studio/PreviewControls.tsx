import { useEffect, useRef, useState } from "react";
import { Maximize, Pause, Play, Volume2, VolumeX } from "lucide-react";

import { useLocale } from "@/lib/locale";
import { formatTimecode } from "./timeline_domain";
import type { PlayerTimelineRef } from "./usePlayerTimeline";

export const canvasRatio = (canvas: { width: number; height: number }) =>
  canvas.width === 1080 && canvas.height === 1920 ? "9:16" : `${canvas.width}:${canvas.height}`;

type Props = {
  player: PlayerTimelineRef | null;
  frame: number;
  durationInFrames: number;
  fps: number;
  playing: boolean;
  canvas: { width: number; height: number };
  onPlay: () => void;
  onPause: () => void;
  onFullscreenChange: (fullscreen: boolean) => void;
};

type PlayerEvent = { detail?: { isFullscreen?: boolean; isMuted?: boolean } };

const icon =
  "inline-flex size-6 items-center justify-center rounded text-muted-ink hover:text-ink disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-copper";

/** The bar under the wide Timeline's preview, in place of the controls inside the video. */
export function PreviewControls({ player, frame, durationInFrames, fps, playing, canvas, onPlay, onPause, onFullscreenChange }: Props) {
  const { t } = useLocale();
  const [muted, setMuted] = useState(false);

  const report = useRef(onFullscreenChange);
  report.current = onFullscreenChange;
  useEffect(() => {
    if (!player) return;
    const onFullscreen = (event: unknown) => report.current(Boolean((event as PlayerEvent).detail?.isFullscreen));
    // The Player applies mute on its next render, so its event is the only true report.
    const onMute = (event: unknown) => setMuted(Boolean((event as PlayerEvent).detail?.isMuted));
    player.addEventListener("fullscreenchange", onFullscreen);
    player.addEventListener("mutechange", onMute);
    // The bar can appear while the Player is already fullscreen, and removal fires no event.
    report.current(Boolean(player.isFullscreen?.()));
    return () => {
      player.removeEventListener("fullscreenchange", onFullscreen);
      player.removeEventListener("mutechange", onMute);
      report.current(false);
    };
  }, [player]);

  const toggleMute = () => {
    if (muted) player?.unmute?.();
    else player?.mute?.();
  };
  const fullscreen = () => {
    try {
      player?.requestFullscreen?.();
    } catch (error) {
      // No fullscreen support: the bar and the preview stay as they were. The Player does not
      // return the browser's promise, so a refusal after this point reaches only the console.
      console.warn("Studio preview could not enter fullscreen", error);
    }
  };

  return (
    // Not a div: pen-studio.css dissolves any div holding the Player's own Play button.
    <footer className="studio-preview-bar">
      <span>
        {formatTimecode(frame, fps)} / {formatTimecode(durationInFrames, fps)}
      </span>
      <button
        type="button"
        className={`${icon} text-ink`}
        aria-label={t(playing ? "studio.preview.pause" : "studio.preview.play")}
        onClick={playing ? onPause : onPlay}
      >
        {playing ? <Pause aria-hidden="true" size={14} /> : <Play aria-hidden="true" size={14} />}
      </button>
      <span className="flex items-center justify-self-end gap-2">
        <span>
          {canvasRatio(canvas)} · {canvas.width}×{canvas.height}
        </span>
        <button
          type="button"
          className={icon}
          disabled={!player}
          aria-label={t(muted ? "studio.preview.unmute" : "studio.preview.mute")}
          onClick={toggleMute}
        >
          {muted ? <VolumeX aria-hidden="true" size={14} /> : <Volume2 aria-hidden="true" size={14} />}
        </button>
        <button type="button" className={icon} disabled={!player || document.fullscreenEnabled === false} aria-label={t("studio.preview.fullscreen")} onClick={fullscreen}>
          <Maximize aria-hidden="true" size={14} />
        </button>
      </span>
    </footer>
  );
}
