import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useMotion } from "../hooks/useMotion";
import { DURATION, gsap } from "../lib/gsap";
import { readDuration, readVideoFrames } from "../lib/media";
import { formatClock, parseClock, type TimeRange } from "../lib/utils";
import { fetchYouTubeDuration, youTubeFrames } from "../lib/youtube";
import type { VideoSource } from "./VideoSourceField";

const FRAME_COUNT = 10;
const MIN_LENGTH = 30; // seconds: less than this leaves the AI too little to cut clips from

interface VideoRangeFieldProps {
  source: VideoSource;
  value: TimeRange | null; // null = the whole video
  onChange: (range: TimeRange) => void;
}

/** Which part of the video the AI watches, like a trim: drag the handles or type the times. */
export function VideoRangeField(props: VideoRangeFieldProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const { source } = props;
  const key =
    source.kind === "file" ? `${source.file.name}:${source.file.size}:${source.file.lastModified}` : source.videoId;

  // A new video slides in and is read from scratch.
  useMotion(
    rootRef,
    () => {
      gsap.from(rootRef.current, { y: 8, autoAlpha: 0, duration: DURATION.base });
    },
    [key],
  );

  return (
    <div ref={rootRef}>
      <RangePicker key={key} {...props} />
    </div>
  );
}

function RangePicker({ source, value, onChange }: VideoRangeFieldProps) {
  const id = useId();
  const labelId = `${id}-label`;
  const file = source.kind === "file" ? source.file : null;
  const videoId = source.kind === "youtube" ? source.videoId : null;
  const [duration, setDuration] = useState<number | null>(null); // null = still reading it
  const [frames, setFrames] = useState<string[]>(() => (videoId ? youTubeFrames(videoId) : []));

  useEffect(() => {
    let cancelled = false;

    if (videoId) {
      void fetchYouTubeDuration(videoId).then((seconds) => {
        if (!cancelled) setDuration(Math.floor(seconds));
      });
      return () => {
        cancelled = true;
      };
    }

    if (!file) return;
    const url = URL.createObjectURL(file);
    let stopFrames = () => {};
    void readDuration(url, "video").then((seconds) => {
      if (cancelled) return;
      setDuration(Math.floor(seconds));
      if (seconds > 0) stopFrames = readVideoFrames(url, seconds, FRAME_COUNT, setFrames);
    });
    return () => {
      cancelled = true;
      stopFrames();
      URL.revokeObjectURL(url);
    };
  }, [file, videoId]);

  const label = (
    <p className="field__label" id={labelId}>
      Range to analyze
    </p>
  );

  if (duration === null) {
    return (
      <div className="field range-field" aria-busy="true">
        {label}
        <div className="range-field__strip">
          <div className="range-field__frames" />
        </div>
        <p className="field__hint">Reading the video…</p>
      </div>
    );
  }

  if (duration === 0) {
    return (
      <div className="field range-field">
        {label}
        <p className="field__hint">This browser can't read the video's length, so the AI will analyze all of it.</p>
      </div>
    );
  }

  const total = duration;
  const minLength = Math.min(MIN_LENGTH, total);
  const range = value ?? { start: 0, end: total };
  const percent = (seconds: number) => `${(seconds / total) * 100}%`;

  const setStart = (seconds: number) => {
    onChange({ start: Math.round(Math.min(Math.max(seconds, 0), range.end - minLength)), end: range.end });
  };

  const setEnd = (seconds: number) => {
    onChange({ start: range.start, end: Math.round(Math.max(Math.min(seconds, total), range.start + minLength)) });
  };

  return (
    <div className="field range-field">
      {label}
      <div className="range-field__strip" role="group" aria-labelledby={labelId}>
        <div className="range-field__frames">
          {frames.map((frame, index) => (
            <img key={index} src={frame} alt="" draggable={false} referrerPolicy="no-referrer" />
          ))}
        </div>
        <div className="range-field__overlay" aria-hidden="true">
          <span className="range-field__shade range-field__shade--start" style={{ width: percent(range.start) }} />
          <span className="range-field__shade range-field__shade--end" style={{ left: percent(range.end) }} />
          <span
            className="range-field__window"
            style={{ left: percent(range.start), width: percent(range.end - range.start) }}
          />
        </div>
        <input
          className="range-field__input"
          type="range"
          min={0}
          max={total}
          step={1}
          value={range.start}
          aria-label="Start"
          aria-valuetext={formatClock(range.start)}
          onChange={(event) => setStart(Number(event.target.value))}
        />
        <input
          className="range-field__input"
          type="range"
          min={0}
          max={total}
          step={1}
          value={range.end}
          aria-label="End"
          aria-valuetext={formatClock(range.end)}
          onChange={(event) => setEnd(Number(event.target.value))}
        />
      </div>

      <div className="range-field__times">
        <TimeInput label="Start" value={range.start} onCommit={setStart} />
        <output className="range-field__length">
          {formatClock(range.end - range.start)} <span>selected</span>
        </output>
        <TimeInput label="End" value={range.end} onCommit={setEnd} />
      </div>
      <p className="field__hint">The AI only watches this part. A shorter range is processed faster.</p>
    </div>
  );
}

interface TimeInputProps {
  label: string;
  value: number; // seconds
  onCommit: (seconds: number) => void;
}

/** A typed time ("1:02:03", "02:03" or seconds), applied on Enter or when leaving the field. Esc undoes it. */
function TimeInput({ label, value, onCommit }: TimeInputProps) {
  const [draft, setDraft] = useState<string | null>(null); // null = not editing: shows `value`

  function commit() {
    const seconds = draft === null ? null : parseClock(draft);
    if (seconds !== null) onCommit(seconds);
    setDraft(null);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault(); // don't submit the form
      commit();
    } else if (event.key === "Escape") {
      setDraft(null);
    }
  }

  return (
    <label className="range-field__time">
      <span className="sr-only">{label}</span>
      <input
        className="input"
        autoComplete="off"
        spellCheck={false}
        value={draft ?? formatClock(value)}
        onFocus={(event) => event.currentTarget.select()}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={handleKeyDown}
      />
    </label>
  );
}