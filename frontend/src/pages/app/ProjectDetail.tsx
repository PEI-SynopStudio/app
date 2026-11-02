import { useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ConfirmDialog } from "../../components/Dialog";
import { IconArrowLeft, IconPlay, IconScissors, IconShare, IconTrash } from "../../components/Icons";
import { ShareDialog } from "../../components/ShareDialog";
import { StatusBadge } from "../../components/StatusBadge";
import { Waveform } from "../../components/Waveform";
import { getProject, type Project, type ProjectStatus } from "../../data/mock";
import { FORMAT_RATIO, captionLanguageLabel } from "../../data/options";
import { usePageEnter } from "../../hooks/useMotion";
import { DURATION, EASE, gsap, prefersReducedMotion, useGSAP } from "../../lib/gsap";
import { formatDate, formatTime, plural, seedFrom, toRanges } from "../../lib/utils";

const BARS = 96;
const CROP_HEIGHT = 0.86; // .player__crop height, relative to the 16:9 stage

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
  const [activeId, setActiveId] = useState<string | null>(project.clips[0]?.id ?? null);
  const [dialog, setDialog] = useState<"delete" | "share" | null>(null);
  const ranges = useMemo(() => toRanges(project.clips, project.durationSec, BARS), [project]);
  const active = project.clips.find((clip) => clip.id === activeId) ?? null;
  const activeIndex = active ? project.clips.indexOf(active) : -1;
  const activeNumber = String(activeIndex + 1).padStart(2, "0");

  // How far the crop can slide sideways without leaving the 16:9 stage (in % of its own width).
  const ratio = FORMAT_RATIO[project.format];
  const reach = Math.max(0, ((16 / 9 - CROP_HEIGHT * ratio) / 2 / (CROP_HEIGHT * ratio)) * 100 * 0.5);

  usePageEnter(pageRef);

  // This is state, not decoration: always runs. With reduced motion it jumps straight to the end.
  useGSAP(
    () => {
      if (!active) return;
      const duration = prefersReducedMotion() ? 0 : DURATION.slow;

      // The playhead travels to the start of the clip.
      gsap.to("[data-playhead]", {
        xPercent: (active.start / project.durationSec) * 100,
        duration,
        ease: EASE.inOut,
        overwrite: "auto",
      });

      // The output frame "reframes" towards the clip's point of interest.
      gsap.to("[data-crop]", {
        xPercent: gsap.utils.mapRange(0, 1, -reach, reach, seedFrom(active.id) % 1),
        duration,
        ease: EASE.inOut,
        overwrite: "auto",
      });

      // The active clip stands out on the waveform; the others step back.
      gsap.to(".wave__bar.is-pick", {
        opacity: (_index: number, el: Element) => (el.getAttribute("data-range") === active.id ? 1 : 0.35),
        duration: duration / 2,
        overwrite: "auto",
      });
    },
    { scope: pageRef, dependencies: [activeId] },
  );

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
              <span aria-hidden="true">·</span>
              <span>{project.format}</span>
              <span aria-hidden="true">·</span>
              <span>
                {project.captions ? `Subtitles: ${captionLanguageLabel(project.captions.language)}` : "No subtitles"}
              </span>
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
            <button type="button" className="btn btn--danger-ghost" onClick={() => setDialog("delete")}>
              <IconTrash /> Delete
            </button>
          </div>
        </div>
        {project.description && <p className="page-subtitle">{project.description}</p>}
      </header>

      <div className="detail">
        <section className="detail__main" aria-label="Preview">
          <div className="player surface-dark" data-enter>
            <div className="player__stage">
              <div className="player__crop" style={{ aspectRatio: ratio }} data-crop>
                <span className="player__play" aria-hidden="true">
                  <IconPlay />
                </span>
              </div>
              {active && (
                <div className="player__caption">
                  <span>
                    {activeNumber} · {active.title}
                  </span>
                  <span className="player__time">
                    {formatTime(active.start)} – {formatTime(active.end)}
                  </span>
                </div>
              )}
            </div>
          </div>

          {active && (
            <div className="clip-actions" data-enter>
              <span className="clip-actions__label">Clip {activeNumber} selected</span>
              <div className="clip-actions__buttons">
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => setDialog("share")}>
                  <IconShare /> Share
                </button>
                <Link to={`/app/projects/${project.id}/clips/${active.id}`} className="btn btn--primary btn--sm">
                  <IconScissors /> Edit clip
                </Link>
              </div>
            </div>
          )}

          <div className="timeline" data-enter>
            <div className="timeline__track">
              <div className="timeline__wave">
                <Waveform bars={BARS} ranges={ranges} seed={seedFrom(project.id)} />
                {active && (
                  <div className="timeline__scan" data-playhead>
                    <span className="timeline__playhead" />
                  </div>
                )}
              </div>
            </div>
            <div className="timeline__labels">
              <span>0:00</span>
              <span>{formatTime(project.durationSec)}</span>
            </div>
          </div>
        </section>

        <section className="clips" aria-labelledby="clips-title" data-enter>
          <div className="clips__header">
            <h2 className="clips__title" id="clips-title">
              Generated Clips
            </h2>
            <span className="clips__count">{plural(project.clips.length, "clip", "clips")}</span>
          </div>

          {project.clips.length === 0 ? (
            <div className="empty">
              <p>There are no clips for this video yet.</p>
            </div>
          ) : (
            <ol className="clip-list">
              {project.clips.map((clip, index) => {
                const isActive = clip.id === activeId;
                return (
                  <li key={clip.id}>
                    <button
                      type="button"
                      className={isActive ? "clip-row is-active" : "clip-row"}
                      aria-pressed={isActive}
                      onClick={() => setActiveId(clip.id)}
                    >
                      <span className="clip-row__index">{String(index + 1).padStart(2, "0")}</span>
                      <span className="clip-row__body">
                        <span className="clip-row__title">{clip.title}</span>
                        <span className="clip-row__meta">
                          {formatTime(clip.start)} – {formatTime(clip.end)} · {formatTime(clip.end - clip.start)}
                        </span>
                      </span>
                      <span className="clip-row__score" title="Relevance score">
                        {clip.score}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          )}
        </section>
      </div>

      <ConfirmDialog
        open={dialog === "delete"}
        onClose={() => setDialog(null)}
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

      {active && (
        <ShareDialog
          key={active.id}
          open={dialog === "share"}
          onClose={() => setDialog(null)}
          project={project}
          clip={active}
        />
      )}
    </div>
  );
}