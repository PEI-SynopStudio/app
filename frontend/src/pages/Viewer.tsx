import { useRef } from "react";
import { Link, useParams } from "react-router";
import { ClipPlayer } from "../components/ClipPlayer";
import { Logo } from "../components/Logo";
import { getSharedClip, type SharedClip } from "../data/mock";
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
  const length = clip.end - clip.start;
  const playback = usePlayback(0, length);

  return (
    <div className="viewer__layout">
      <div data-enter>
        <ClipPlayer
          format={project.format}
          elapsed={playback.time}
          length={length}
          isPlaying={playback.isPlaying}
          onToggle={playback.toggle}
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

        {/* The Terms forbid hiding that a clip is AI-generated or where it comes from. */}
        <div className="viewer__source">
          <span className="viewer__ai">AI-generated clip</span>
          <p>
            Cut from “{project.title}”, {formatTime(clip.start)} – {formatTime(clip.end)}.
          </p>
        </div>

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