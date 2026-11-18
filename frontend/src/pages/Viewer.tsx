import { useMemo, useRef } from "react";
import { Link, useParams } from "react-router";
import { ClipPlayer } from "../components/ClipPlayer";
import { Logo } from "../components/Logo";
import { TranscriptPanel } from "../components/TranscriptPanel";
import { clipLength, getSharedClip, type SharedClip } from "../data/mock";
import { cueAt, getTranscripts } from "../data/transcripts";
import { usePageEnter } from "../hooks/useMotion";
import { usePlayback } from "../hooks/usePlayback";
import { formatTime } from "../lib/utils";
import "../styles/viewer.css";

export function Viewer() {
  const { shareId } = useParams();
  const shared = getSharedClip(shareId);
  const pageRef = useRef<HTMLDivElement>(null);

  usePageEnter(pageRef);

  return (
    <div className="viewer" ref={pageRef}>
      <header className="viewer-header">
        <div className="container viewer-header__inner">
          <Logo />
          <Link to="/signup" className="btn btn--primary btn--sm">
            Create your own clips
          </Link>
        </div>
      </header>

      <main className="container viewer__main">
        {shared ? (
          <SharedClipView {...shared} />
        ) : (
          <div className="viewer__missing" data-enter>
            <h1 className="viewer__title">This link doesn't work</h1>
            <p>The clip may have been deleted, or its owner stopped sharing it.</p>
            <Link to="/" className="btn btn--primary">
              Go to SynopStudio
            </Link>
          </div>
        )}
      </main>
    </div>
  );
}

function SharedClipView({ project, clip, sharedBy }: SharedClip) {
  const length = clipLength(clip);
  const playback = usePlayback(0, length);
  // The language the owner picked for this clip on the project page.
  const language = clip.subtitleLanguage ?? project.language;
  const transcripts = useMemo(() => getTranscripts(clip, language), [clip, language]);
  const cue = project.captions ? cueAt(transcripts.subtitles, playback.time) : undefined;

  return (
    <div className="viewer__layout">
      <div className="viewer__player" data-enter>
        <ClipPlayer
          format={project.format}
          elapsed={playback.time}
          length={length}
          isPlaying={playback.isPlaying}
          onToggle={playback.toggle}
          caption={cue && project.captions ? { text: cue.text, variant: project.captions.style } : null}
        />
      </div>

      <div className="viewer__info" data-enter>
        <p className="eyebrow">Shared with you by {sharedBy}</p>
        <h1 className="viewer__title">{clip.title}</h1>
        <p className="viewer__meta">
          <span>{formatTime(length)}</span>
          <span aria-hidden="true">·</span>
          <span>{project.format}</span>
        </p>

        {/* The Terms forbid hiding that a clip is AI-generated. The source video and its timestamps stay private. */}
        <div className="viewer__source">
          <span className="viewer__ai">AI-edited clip</span>
          <p>Made with SynopStudio.</p>
        </div>

        <TranscriptPanel
          transcripts={transcripts}
          time={playback.time}
          onSeek={playback.seek}
          language={language}
          originalLanguage={project.language}
          fileName={clip.title}
        />

        <div className="viewer__cta">
          <p>Turn your own long videos into clips like this one.</p>
          <Link to="/signup" className="btn btn--ghost">
            Try SynopStudio
          </Link>
        </div>
      </div>
    </div>
  );
}