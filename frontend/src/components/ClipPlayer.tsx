import type { CSSProperties } from "react";
import { FORMAT_RATIO, type AspectRatio, type CaptionStyle } from "../data/options";
import { formatTime } from "../lib/utils";
import { Caption } from "./Caption";
import { IconPause, IconPlay } from "./Icons";
import "../styles/player.css";

interface ClipPlayerProps {
  format: AspectRatio;
  elapsed: number; // seconds since the clip start
  length: number; // clip length in seconds
  isPlaying: boolean;
  onToggle: () => void;
  caption?: { text: string; variant: CaptionStyle } | null;
}

/** The clip in its final format. Placeholder visuals until there is a real video. */
export function ClipPlayer({ format, elapsed, length, isPlaying, onToggle, caption }: ClipPlayerProps) {
  const progress = length > 0 ? elapsed / length : 0;

  return (
    <div className={isPlaying ? "clip-player is-playing" : "clip-player"}>
      <div className="clip-player__frame" style={{ "--ratio": FORMAT_RATIO[format] } as CSSProperties}>
        <button
          type="button"
          className="clip-player__play"
          aria-label={isPlaying ? "Pause" : "Play"}
          onClick={onToggle}
        >
          {isPlaying ? <IconPause /> : <IconPlay />}
        </button>
        {caption && <Caption text={caption.text} variant={caption.variant} />}
        <span className="clip-player__time">
          {formatTime(elapsed)} / {formatTime(length)}
        </span>
        <span className="clip-player__progress" aria-hidden="true">
          <span style={{ transform: `scaleX(${progress})` }} />
        </span>
      </div>
    </div>
  );
}