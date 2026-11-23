import { useId, useState, type FormEvent } from "react";
import { FORMAT_RATIO, type AspectRatio } from "../../data/options";
import { formatTime } from "../../lib/utils";
import { Dialog } from "../Dialog";
import { IconCheck } from "../Icons";

type Quality = 720 | 1080 | 2160;
type FrameRate = 30 | 60;

const QUALITIES: { value: Quality; label: string }[] = [
  { value: 720, label: "720p" },
  { value: 1080, label: "1080p" },
  { value: 2160, label: "4K" },
];

const FRAME_RATES: FrameRate[] = [30, 60];

/** Output size in pixels: the short side is the chosen quality, kept even for the encoder. */
function frameSize(format: AspectRatio, quality: Quality): string {
  const ratio = FORMAT_RATIO[format];
  const even = (value: number) => Math.round(value / 2) * 2;
  const [width, height] = ratio < 1 ? [quality, even(quality / ratio)] : [even(quality * ratio), quality];
  return `${width} × ${height}`;
}

interface ExportDialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  format: AspectRatio;
  duration: number;
  hasCaptions: boolean;
}

export function ExportDialog({ open, onClose, title, format, duration, hasCaptions }: ExportDialogProps) {
  const id = useId();
  const [quality, setQuality] = useState<Quality>(1080);
  const [frameRate, setFrameRate] = useState<FrameRate>(30);
  const [isQueued, setIsQueued] = useState(false);

  function close() {
    setIsQueued(false);
    onClose();
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // TODO(api): POST /projects/:projectId/clips/:clipId/renders with { quality, frameRate } and follow its status.
    setIsQueued(true);
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Export video"
      description={isQueued ? undefined : "Renders the whole timeline into one MP4 file."}
    >
      {isQueued ? (
        <div className="dialog__form">
          <p className="export-done" role="status">
            <span className="export-done__icon" aria-hidden="true">
              <IconCheck />
            </span>
            <span>
              <strong>{title}</strong> is being rendered. We will let you know when the file is ready to download.
            </span>
          </p>
          <div className="dialog__actions">
            <button type="button" className="btn btn--primary" onClick={close}>
              Done
            </button>
          </div>
        </div>
      ) : (
        <form className="dialog__form" onSubmit={handleSubmit}>
          <div className="field">
            <p className="field__label" id={`${id}-quality`}>
              Resolution
            </p>
            <div className="chips" role="radiogroup" aria-labelledby={`${id}-quality`}>
              {QUALITIES.map((option) => (
                <label key={option.value} className="chip">
                  <input
                    className="sr-only"
                    type="radio"
                    name={`${id}-quality`}
                    checked={quality === option.value}
                    onChange={() => setQuality(option.value)}
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </div>

          <div className="field">
            <p className="field__label" id={`${id}-fps`}>
              Frame rate
            </p>
            <div className="chips" role="radiogroup" aria-labelledby={`${id}-fps`}>
              {FRAME_RATES.map((rate) => (
                <label key={rate} className="chip">
                  <input
                    className="sr-only"
                    type="radio"
                    name={`${id}-fps`}
                    checked={frameRate === rate}
                    onChange={() => setFrameRate(rate)}
                  />
                  {rate} fps
                </label>
              ))}
            </div>
          </div>

          <dl className="stat-grid">
            <div>
              <dt>Size</dt>
              <dd>{frameSize(format, quality)}</dd>
            </div>
            <div>
              <dt>Length</dt>
              <dd>{formatTime(duration)}</dd>
            </div>
            <div>
              <dt>File</dt>
              <dd>MP4 · H.264</dd>
            </div>
            <div>
              <dt>Subtitles</dt>
              <dd>{hasCaptions ? "Burned in" : "None"}</dd>
            </div>
          </dl>

          <div className="dialog__actions">
            <button type="button" className="btn btn--ghost" onClick={close}>
              Cancel
            </button>
            <button type="submit" className="btn btn--accent">
              Export video
            </button>
          </div>
        </form>
      )}
    </Dialog>
  );
}