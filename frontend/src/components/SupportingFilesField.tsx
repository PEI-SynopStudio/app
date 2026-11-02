import { useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { useMotion } from "../hooks/useMotion";
import { DURATION, gsap } from "../lib/gsap";
import { formatBytes, plural } from "../lib/utils";
import { IconFile } from "./Icons";

const ACCEPTED = ["pdf", "ppt", "pptx", "odp", "doc", "docx", "odt", "txt", "md"];
const ACCEPT_ATTR = ACCEPTED.map((ext) => `.${ext}`).join(",");
const MAX_FILES = 10;
const MAX_MB = 50;

function extension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot + 1).toLowerCase();
}

function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

interface SupportingFilesFieldProps {
  files: File[];
  onChange: (files: File[]) => void;
}

/** Optional documents (slides, reports, notes) that give the AI context about the video. */
export function SupportingFilesField({ files, onChange }: SupportingFilesFieldProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fresh, setFresh] = useState<string[]>([]);

  // Only the rows that just arrived slide in; the ones already listed stay put.
  useMotion(
    rootRef,
    () => {
      if (fresh.length === 0) return;
      gsap.from("[data-fresh]", { y: 8, autoAlpha: 0, duration: DURATION.base, stagger: 0.04 });
    },
    [fresh],
  );

  function addFiles(list: FileList | null) {
    if (!list || list.length === 0) return;
    const known = new Set(files.map(fileKey));
    const added: File[] = [];
    let skipped = 0;

    for (const file of Array.from(list)) {
      const key = fileKey(file);
      if (known.has(key)) continue;
      const valid = ACCEPTED.includes(extension(file.name)) && file.size <= MAX_MB * 1024 ** 2;
      if (!valid || files.length + added.length >= MAX_FILES) {
        skipped += 1;
        continue;
      }
      known.add(key);
      added.push(file);
    }

    setError(
      skipped > 0
        ? `${plural(skipped, "file was", "files were")} skipped. Use PDF, slides, documents or text files up to ${MAX_MB} MB (${MAX_FILES} files at most).`
        : null,
    );
    if (added.length === 0) return;
    setFresh(added.map(fileKey));
    onChange([...files, ...added]);
  }

  function handleInput(event: ChangeEvent<HTMLInputElement>) {
    addFiles(event.target.files);
    event.target.value = ""; // lets the same file be picked again after removing it
  }

  function removeFile(key: string) {
    setError(null);
    onChange(files.filter((file) => fileKey(file) !== key));
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
    addFiles(event.dataTransfer.files);
  }

  return (
    <div className="supporting" ref={rootRef}>
      <label
        className={isDragging ? "dropzone dropzone--compact is-dragging" : "dropzone dropzone--compact"}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <input className="sr-only" type="file" multiple accept={ACCEPT_ATTR} onChange={handleInput} />
        <span className="dropzone__icon">
          <IconFile />
        </span>
        <span className="dropzone__text">
          <span className="dropzone__title">Add slides, reports or notes</span>
          <span className="dropzone__hint">
            Drag files here or <u>browse</u> · PDF, PPTX, DOCX, TXT or MD · up to {MAX_MB} MB each
          </span>
        </span>
      </label>

      {files.length > 0 && (
        <ul className="file-list">
          {files.map((file) => {
            const key = fileKey(file);
            return (
              <li key={key} className="file-row" data-fresh={fresh.includes(key) || undefined}>
                <span className="file-row__icon file-row__icon--ext" aria-hidden="true">
                  {extension(file.name).toUpperCase()}
                </span>
                <div className="file-row__info">
                  <p className="file-row__name">{file.name}</p>
                  <p className="file-row__meta">{formatBytes(file.size)}</p>
                </div>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  aria-label={`Remove ${file.name}`}
                  onClick={() => removeFile(key)}
                >
                  Remove
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}