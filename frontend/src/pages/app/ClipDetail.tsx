import { useId, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { ClipPlayer } from "../../components/ClipPlayer";
import { IconArrowLeft, IconScissors, IconShare } from "../../components/Icons";
import { ShareDialog } from "../../components/ShareDialog";
import { TranscriptPanel } from "../../components/TranscriptPanel";
import { clipLength, getClip, placeScenes, type Clip, type Project } from "../../data/mock";
import { LANGUAGES, type Language } from "../../data/options";
import { cueAt, getTranscripts } from "../../data/transcripts";
import { usePageEnter } from "../../hooks/useMotion";
import { usePlayback } from "../../hooks/usePlayback";
import { formatClock, formatTime, plural } from "../../lib/utils";

export function ClipDetail() {
  const { projectId, clipId } = useParams();
  const found = getClip(projectId, clipId);
  if (!found) return <ClipMissing projectId={projectId} />;
  return <ClipView key={found.clip.id} project={found.project} clip={found.clip} />;
}

function ClipMissing({ projectId }: { projectId?: string }) {
  return (
    <div className="page">
      <div className="empty">
        <p>This clip does not exist or has been removed.</p>
        <Link to={projectId ? `/app/projects/${projectId}` : "/app"} className="btn btn--ghost btn--sm">
          Back to project
        </Link>
      </div>
    </div>
  );
}

function ClipView({ project, clip }: { project: Project; clip: Clip }) {
  const pageRef = useRef<HTMLDivElement>(null);
  const languageId = useId();
  const [language, setLanguage] = useState<Language>(clip.subtitleLanguage ?? project.language);
  const [isSharing, setIsSharing] = useState(false);
  const length = clipLength(clip);
  const playback = usePlayback(0, length);
  const scenes = useMemo(() => placeScenes(clip), [clip]);
  // Subtitles and transcripts use the spoken language unless a translation was picked.
  const transcripts = useMemo(() => getTranscripts(clip, language), [clip, language]);
  const cue = project.captions ? cueAt(transcripts.subtitles, playback.time) : undefined;
  const activeScene = scenes.findIndex(
    (scene) => playback.time >= scene.at && playback.time < scene.at + scene.end - scene.start,
  );
  const number = String(project.clips.indexOf(clip) + 1).padStart(2, "0");
  const languageOptions = useMemo(
    () => [...LANGUAGES].sort((a, b) => Number(b.value === project.language) - Number(a.value === project.language)),
    [project.language],
  );
  const percent = (seconds: number) => `${(seconds / project.durationSec) * 100}%`;

  usePageEnter(pageRef);

  function changeLanguage(next: Language) {
    // TODO(api): PATCH /clips/:id { subtitleLanguage } — the AI translates; the viewer link shows the same language.
    setLanguage(next);
  }

  return (
    <div className="page" ref={pageRef}>
      <header className="detail-header" data-enter>
        <Link to={`/app/projects/${project.id}`} className="back-link">
          <IconArrowLeft /> {project.title}
        </Link>
        <div className="detail-header__row">
          <div>
            <h1 className="page-title">{clip.title}</h1>
            <div className="detail-header__meta">
              <span>Clip {number}</span>
              <span aria-hidden="true">·</span>
              <span>{formatTime(length)}</span>
              <span aria-hidden="true">·</span>
              <span>{plural(scenes.length, "scene", "scenes")}</span>
              <span aria-hidden="true">·</span>
              <span>{project.format}</span>
            </div>
          </div>
          <div className="header-actions">
            <button type="button" className="btn btn--ghost" onClick={() => setIsSharing(true)}>
              <IconShare /> Share
            </button>
            <Link to={`/app/projects/${project.id}/clips/${clip.id}/edit`} className="btn btn--primary">
              <IconScissors /> Edit clip
            </Link>
          </div>
        </div>
      </header>

      <div className="clip-detail">
        <section className="clip-detail__player" aria-label="Clip preview">
          <div data-enter>
            <ClipPlayer
              format={project.format}
              elapsed={playback.time}
              length={length}
              isPlaying={playback.isPlaying}
              onToggle={playback.toggle}
              caption={cue && project.captions ? { text: cue.text, variant: project.captions.style } : null}
            />
          </div>

          <div className="clip-language" data-enter>
            <label className="clip-language__label" htmlFor={languageId}>
              Subtitles and transcripts
            </label>
            <select
              id={languageId}
              className="input clip-language__select"
              value={language}
              onChange={(event) => {
                const next = LANGUAGES.find((option) => option.value === event.target.value)?.value;
                if (next) changeLanguage(next);
              }}
            >
              {languageOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label} {option.value === project.language ? "(original)" : "(auto-translated)"}
                </option>
              ))}
            </select>
          </div>
        </section>

        <section className="clips clip-detail__scenes" aria-labelledby="scenes-title" data-enter>
          <div className="clips__header">
            <h2 className="clips__title" id="scenes-title">
              Scenes
            </h2>
            <span className="clips__count">{plural(scenes.length, "scene", "scenes")}</span>
          </div>
          <p className="clips__hint">
            Where each part of this clip comes from in the original video ({formatTime(project.durationSec)}).
          </p>

          <ol className="clip-list">
            {scenes.map((scene, index) => {
              const end = scene.at + scene.end - scene.start;
              const isActive = index === activeScene;
              const description = transcripts.audiovisual[index]?.text;
              return (
                <li key={`${scene.start}-${index}`}>
                  <button
                    type="button"
                    className={isActive ? "clip-row is-active" : "clip-row"}
                    aria-current={isActive || undefined}
                    onClick={() => playback.seek(scene.at)}
                  >
                    <span className="clip-row__index">{String(index + 1).padStart(2, "0")}</span>
                    <span className="clip-row__body">
                      <span className="clip-row__title">
                        {formatClock(scene.start)} – {formatClock(scene.end)} in the original
                      </span>
                      <span className="clip-row__meta">
                        {formatClock(scene.at)} – {formatClock(end)} in the clip
                      </span>
                      {description && <span className="clip-row__desc">{description}</span>}
                      <span className="clip-row__track" aria-hidden="true">
                        <span style={{ left: percent(scene.start), width: percent(scene.end - scene.start) }} />
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </section>

        <div className="clip-detail__transcript">
          <TranscriptPanel
            transcripts={transcripts}
            time={playback.time}
            onSeek={playback.seek}
            language={language}
            originalLanguage={project.language}
            fileName={clip.title}
          />
        </div>
      </div>

      <ShareDialog open={isSharing} onClose={() => setIsSharing(false)} project={project} clip={clip} />
    </div>
  );
}