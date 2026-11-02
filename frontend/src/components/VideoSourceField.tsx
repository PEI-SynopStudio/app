import { useRef, useState, type ChangeEvent, type ComponentType, type DragEvent, type Ref } from "react";
import { useMotion } from "../hooks/useMotion";
import { DURATION, gsap } from "../lib/gsap";
import { formatBytes } from "../lib/utils";
import { parseYouTubeId, youTubeThumbnail, youTubeWatchUrl } from "../lib/youtube";
import { Field } from "./Field";
import { IconFilm, IconLink, IconUpload, type IconProps } from "./Icons";

export type VideoSource =
  | { kind: "file"; file: File }
  | { kind: "youtube"; url: string; videoId: string };

type Mode = VideoSource["kind"];

const MODES: { value: Mode; label: string; icon: ComponentType<IconProps> }[] = [
  { value: "file", label: "Upload file", icon: IconUpload },
  { value: "youtube", label: "YouTube link", icon: IconLink },
];

function toSource(mode: Mode, file: File | null, url: string): VideoSource | null {
  if (mode === "file") return file ? { kind: "file", file } : null;
  const videoId = parseYouTubeId(url);
  return videoId ? { kind: "youtube", url: youTubeWatchUrl(videoId), videoId } : null;
}

function sourceKey(source: VideoSource | null): string {
  if (!source) return "";
  return source.kind === "file" ? `${source.file.name}:${source.file.size}` : source.videoId;
}

interface VideoSourceFieldProps {
  onChange: (source: VideoSource | null) => void;
  error: string | null;
  onError: (message: string | null) => void;
  ref?: Ref<HTMLDivElement>;
}

/** Video picker with two sources: a local file or a YouTube link. Keeps both, so switching tabs loses nothing. */
export function VideoSourceField({ onChange, error, onError, ref }: VideoSourceFieldProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const hasSwitched = useRef(false);
  const [mode, setMode] = useState<Mode>("file");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [isDragging, setIsDragging] = useState(false);

  const source = toSource(mode, file, url);
  const key = sourceKey(source);

  // Switching tabs: the new panel slides in (not on first render — the page entrance covers that).
  useMotion(
    panelRef,
    () => {
      if (!hasSwitched.current) return;
      gsap.from("[data-source-panel]", { y: 8, autoAlpha: 0, duration: DURATION.base });
    },
    [mode],
  );

  // When a video arrives, its summary row slides in.
  useMotion(
    panelRef,
    () => {
      if (!key) return;
      gsap.from("[data-file-row]", { y: 8, autoAlpha: 0, duration: DURATION.base });
    },
    [key],
  );

  function switchMode(next: Mode) {
    if (next === mode) return;
    hasSwitched.current = true;
    setMode(next);
    setIsDragging(false);
    onError(null);
    onChange(toSource(next, file, url));
  }

  function pickFile(next: File | undefined) {
    if (!next) return;
    if (!next.type.startsWith("video/")) {
      onError("The selected file is not a video. Please choose a valid video file.");
      return;
    }
    onError(null);
    setFile(next);
    onChange({ kind: "file", file: next });
  }

  function removeFile() {
    setFile(null);
    if (inputRef.current) inputRef.current.value = "";
    onChange(null);
  }

  function handleDragOver(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsDragging(true);
  }

  function handleDragLeave(event: DragEvent<HTMLLabelElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setIsDragging(false);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsDragging(false);
    pickFile(event.dataTransfer.files[0]);
  }

  function handleUrlChange(event: ChangeEvent<HTMLInputElement>) {
    const next = event.target.value;
    const nextSource = toSource("youtube", file, next);
    setUrl(next);
    onChange(nextSource);
    if (nextSource) onError(null);
  }

  // Only complains once the user leaves the field, not on every keystroke.
  function handleUrlBlur() {
    if (url.trim() && !parseYouTubeId(url)) onError("This doesn't look like a YouTube video link.");
  }

  function clearUrl() {
    setUrl("");
    onChange(null);
  }

  return (
    <div className="source" ref={ref}>
      <div className="segmented" role="group" aria-label="Video source">
        {MODES.map(({ value, label, icon: Icon }) => (
          <button
            key={value}
            type="button"
            className="segmented__btn"
            aria-pressed={mode === value}
            onClick={() => switchMode(value)}
          >
            <Icon /> {label}
          </button>
        ))}
      </div>

      <div ref={panelRef}>
        {mode === "file" ? (
          <div className="source__body" data-source-panel>
            <label
              className={isDragging ? "dropzone is-dragging" : "dropzone"}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <input
                ref={inputRef}
                className="sr-only"
                type="file"
                accept="video/*"
                onChange={(event) => pickFile(event.target.files?.[0])}
              />
              <span className="dropzone__icon">
                <IconUpload />
              </span>
              <span className="dropzone__title">{file ? "Change video" : "Drag the video here"}</span>
              <span className="dropzone__hint">
                or <u>choose a file</u> · MP4, MOV or WebM
              </span>
            </label>

            {file && (
              <div className="file-row" data-file-row>
                <span className="file-row__icon">
                  <IconFilm />
                </span>
                <div className="file-row__info">
                  <p className="file-row__name">{file.name}</p>
                  <p className="file-row__meta">{formatBytes(file.size)}</p>
                </div>
                <button type="button" className="btn btn--ghost btn--sm" onClick={removeFile}>
                  Remove
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="source__body" data-source-panel>
            <Field
              label="YouTube link"
              name="youtubeUrl"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              placeholder="https://www.youtube.com/watch?v=…"
              value={url}
              onChange={handleUrlChange}
              onBlur={handleUrlBlur}
              aria-invalid={error ? true : undefined}
              hint="Public or unlisted videos only. Make sure you're allowed to use the content."
            />

            {source?.kind === "youtube" && (
              <div className="file-row" data-file-row>
                <img
                  className="file-row__thumb"
                  src={youTubeThumbnail(source.videoId)}
                  alt=""
                  width={64}
                  height={36}
                  loading="lazy"
                  referrerPolicy="no-referrer"
                />
                <div className="file-row__info">
                  <p className="file-row__name">YouTube video</p>
                  <p className="file-row__meta">youtube.com/watch?v={source.videoId}</p>
                </div>
                <button type="button" className="btn btn--ghost btn--sm" onClick={clearUrl}>
                  Remove
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}