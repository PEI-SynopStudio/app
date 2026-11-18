import { useEffect, useId, useRef, useState } from "react";
import { languageLabel, type Language } from "../data/options";
import {
  TRANSCRIPT_KINDS,
  rangeLabel,
  toSrt,
  transcriptText,
  type ClipTranscripts,
  type TranscriptKind,
} from "../data/transcripts";
import { prefersReducedMotion } from "../lib/gsap";
import { formatClock } from "../lib/utils";
import { IconCheck, IconCopy, IconDownload } from "./Icons";
import "../styles/transcript.css";

interface TranscriptPanelProps {
  transcripts: ClipTranscripts;
  time: number; // playback position, seconds from the clip start
  onSeek: (time: number) => void;
  language: Language;
  originalLanguage: Language; // spoken in the video
  fileName: string; // downloads are named after it
}

function slug(text: string): string {
  const base = text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return base || "clip";
}

/** The three AI transcripts of a clip. The line being played is highlighted; times seek the player. */
export function TranscriptPanel({ transcripts, time, onSeek, language, originalLanguage, fileName }: TranscriptPanelProps) {
  const id = useId();
  const listRef = useRef<HTMLOListElement>(null);
  const [kind, setKind] = useState<TranscriptKind>("general");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lines = transcripts[kind];
  const current = TRANSCRIPT_KINDS.find((item) => item.value === kind) ?? TRANSCRIPT_KINDS[0];
  const activeIndex = lines.findIndex((line) => time >= line.start && time < line.end);

  // Keeps the current line visible inside the list, without scrolling the page.
  useEffect(() => {
    const list = listRef.current;
    const item = activeIndex >= 0 ? list?.children[activeIndex] : undefined;
    if (!list || !(item instanceof HTMLElement)) return;
    const top = item.offsetTop;
    if (top < list.scrollTop || top + item.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTo({ top: top - 8, behavior: prefersReducedMotion() ? "auto" : "smooth" });
    }
  }, [activeIndex, kind]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(transcriptText(lines));
      setError(null);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Couldn't copy the text. Use the download instead.");
    }
  }

  function download() {
    const isSrt = kind === "subtitles";
    const content = isSrt ? toSrt(lines) : transcriptText(lines);
    const url = URL.createObjectURL(new Blob([content], { type: isSrt ? "application/x-subrip" : "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${slug(fileName)}-${kind}.${isSrt ? "srt" : "txt"}`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  return (
    <section className="transcript" aria-labelledby={`${id}-title`} data-enter>
      <header className="transcript__head">
        <div>
          <h2 className="transcript__title" id={`${id}-title`}>
            Transcript
          </h2>
          <p className="transcript__lang">
            {languageLabel(language)}
            {language === originalLanguage
              ? " · original language"
              : ` · auto-translated from ${languageLabel(originalLanguage)}`}
          </p>
        </div>
        <div className="transcript__actions">
          <button type="button" className="btn btn--ghost btn--sm" onClick={copy}>
            {copied ? (
              <>
                <IconCheck /> Copied
              </>
            ) : (
              <>
                <IconCopy /> Copy
              </>
            )}
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={download}>
            <IconDownload /> {kind === "subtitles" ? "SRT" : "TXT"}
          </button>
        </div>
      </header>

      <div className="transcript__tabs" role="group" aria-label="Transcript type">
        {TRANSCRIPT_KINDS.map((item) => (
          <button
            key={item.value}
            type="button"
            className="transcript__tab"
            aria-pressed={kind === item.value}
            onClick={() => setKind(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <p className="transcript__hint">{current.hint}</p>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <ol className="transcript__list" ref={listRef}>
        {lines.map((line, index) => {
          const isActive = index === activeIndex;
          return (
            <li
              key={`${kind}-${index}`}
              className={isActive ? "transcript__line is-active" : "transcript__line"}
              aria-current={isActive || undefined}
            >
              <p className="transcript__stamp">
                <button
                  type="button"
                  className="transcript__time"
                  aria-label={`Play from ${formatClock(line.start)}`}
                  onClick={() => onSeek(line.start)}
                >
                  {rangeLabel(line)}
                </button>
                {line.speaker && <span className="transcript__speaker">{line.speaker}</span>}
              </p>
              <p className="transcript__text">{line.text}</p>
            </li>
          );
        })}
      </ol>

      <p className="transcript__note">Generated by AI. It may contain mistakes.</p>
    </section>
  );
}