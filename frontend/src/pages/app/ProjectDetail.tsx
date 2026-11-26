import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ClipPlayer } from "../../components/ClipPlayer";
import { ConfirmDialog } from "../../components/Dialog";
import { IconArrowLeft, IconTrash } from "../../components/Icons";
import { StatusBadge } from "../../components/StatusBadge";
import { clipLength, getProject, type Clip, type Project, type ProjectStatus } from "../../data/mock";
import { captionStyleLabel, languageLabel, type AspectRatio } from "../../data/options";
import { cueAt, getTranscripts } from "../../data/transcripts";
import { usePageEnter } from "../../hooks/useMotion";
import { usePlayback } from "../../hooks/usePlayback";
import { formatDate, formatTime, plural } from "../../lib/utils";

// Vertical clips get narrow cards, landscape ones wide cards.
const CARD_MIN: Record<AspectRatio, string> = {
  "9:16": "200px",
  "4:5": "220px",
  "1:1": "240px",
  "16:9": "300px",
};

export function ProjectDetail() {
  const { projectId } = useParams();
  const project = getProject(projectId);
  if (!project) return <ProjectMissing />;
  return <ProjectView key={project.id} project={project} />;
}

function ProjectMissing() {
  return (
    <div className="page">
      <div className="empty">
        <p>This project does not exist or has been removed.</p>
        <Link to="/app" className="btn btn--ghost btn--sm">
          Back to Projects
        </Link>
      </div>
    </div>
  );
}

function ProjectView({ project }: { project: Project }) {
  const navigate = useNavigate();
  const pageRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<ProjectStatus>(project.status);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const { analyzed } = project;
  const isPartial = analyzed.start > 0 || analyzed.end < project.durationSec;

  usePageEnter(pageRef);

  function deleteProject() {
    // TODO(api): DELETE /projects/:id — removes the video, supporting files, transcripts and clips.
    navigate("/app");
  }

  return (
    <div className="page" ref={pageRef}>
      <header className="detail-header" data-enter>
        <Link to="/app" className="back-link">
          <IconArrowLeft /> Projects
        </Link>
        <div className="detail-header__row">
          <div>
            <h1 className="page-title">{project.title}</h1>
            <div className="detail-header__meta">
              <StatusBadge status={status} />
              <span>{formatTime(project.durationSec)}</span>
              {isPartial && (
                <>
                  <span aria-hidden="true">·</span>
                  <span>
                    AI range {formatTime(analyzed.start)}–{formatTime(analyzed.end)}
                  </span>
                </>
              )}
              <span aria-hidden="true">·</span>
              <span>{project.format}</span>
              <span aria-hidden="true">·</span>
              <span>Language: {languageLabel(project.language)}</span>
              <span aria-hidden="true">·</span>
              <span>{project.captions ? `Subtitles: ${captionStyleLabel(project.captions.style)}` : "No subtitles"}</span>
              <span aria-hidden="true">·</span>
              <span>Created on {formatDate(project.createdAt)}</span>
            </div>
          </div>
          <div className="header-actions">
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => setStatus((current) => (current === "archived" ? "draft" : "archived"))}
            >
              {status === "archived" ? "Restore" : "Archive"}
            </button>
            <button type="button" className="btn btn--danger-ghost" onClick={() => setIsDeleting(true)}>
              <IconTrash /> Delete
            </button>
          </div>
        </div>
        {project.description && <p className="page-subtitle">{project.description}</p>}
      </header>

      <section className="clips" aria-labelledby="clips-title">
        <div className="clips__header" data-enter>
          <h2 className="clips__title" id="clips-title">
            Generated clips
          </h2>
          <span className="clips__count">{plural(project.clips.length, "clip", "clips")}</span>
        </div>

        {project.clips.length === 0 ? (
          <div className="empty" data-enter>
            <p>Clips show up here once the video has been processed.</p>
          </div>
        ) : (
          <ol className="clip-grid" style={{ "--card-min": CARD_MIN[project.format] } as CSSProperties}>
            {project.clips.map((clip, index) => (
              <li key={clip.id} data-enter>
                <ClipCard
                  project={project}
                  clip={clip}
                  number={index + 1}
                  isCurrent={playingId === clip.id}
                  onPlay={() => setPlayingId(clip.id)}
                />
              </li>
            ))}
          </ol>
        )}
      </section>

      <ConfirmDialog
        open={isDeleting}
        onClose={() => setIsDeleting(false)}
        onConfirm={deleteProject}
        title="Delete this project?"
        description={
          <>
            <p>
              <strong>{project.title}</strong> and its {plural(project.clips.length, "clip", "clips")} will be
              permanently deleted, along with the uploaded video, supporting files and transcripts.
            </p>
            <p>This can't be undone.</p>
          </>
        }
        confirmLabel="Delete project"
      />
    </div>
  );
}

interface ClipCardProps {
  project: Project;
  clip: Clip;
  number: number;
  isCurrent: boolean; // the last clip someone pressed play on
  onPlay: () => void;
}

function ClipCard({ project, clip, number, isCurrent, onPlay }: ClipCardProps) {
  const length = clipLength(clip);
  const playback = usePlayback(0, length);
  const language = clip.subtitleLanguage ?? project.language;
  const subtitles = useMemo(() => getTranscripts(clip, language).subtitles, [clip, language]);
  const cue = project.captions ? cueAt(subtitles, playback.time) : undefined;
  const { isPlaying, pause } = playback;

  // Only one clip plays at a time: starting another one pauses this one.
  useEffect(() => {
    if (!isCurrent) pause();
  }, [isCurrent]);

  function toggle() {
    if (!isPlaying) onPlay();
    playback.toggle();
  }

  return (
    <article className="clip-card">
      <ClipPlayer
        variant="card"
        format={project.format}
        elapsed={playback.time}
        length={length}
        isPlaying={isPlaying}
        onToggle={toggle}
        caption={cue && project.captions ? { text: cue.text, variant: project.captions.style } : null}
      />
      <div className="clip-card__body">
        <span className="clip-card__index">Clip {String(number).padStart(2, "0")}</span>
        <h3 className="clip-card__title">
          <Link to={`/app/projects/${project.id}/clips/${clip.id}`} className="clip-card__link">
            {clip.title}
          </Link>
        </h3>
        <p className="clip-card__meta">
          <span>{formatTime(length)}</span>
          <span aria-hidden="true">·</span>
          <span>{plural(clip.scenes.length, "scene", "scenes")}</span>
          {language !== project.language && (
            <>
              <span aria-hidden="true">·</span>
              <span>{languageLabel(language)}</span>
            </>
          )}
        </p>
      </div>
    </article>
  );
}