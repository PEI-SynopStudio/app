import { useRef, useState, type ChangeEvent } from "react";
import { Link } from "react-router";
import { IconPlus, IconSearch } from "../../components/Icons";
import { StatusBadge } from "../../components/StatusBadge";
import { Waveform } from "../../components/Waveform";
import { projects, type Project, type ProjectStatus } from "../../data/mock";
import { usePageEnter } from "../../hooks/useMotion";
import { DURATION, EASE, Flip, gsap, prefersReducedMotion, useGSAP } from "../../lib/gsap";
import { formatDate, formatTime, plural, seedFrom, toRanges } from "../../lib/utils";

type Filter = "all" | ProjectStatus;

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "draft", label: "Drafts" },
  { value: "archived", label: "Archived" },
];

const THUMB_BARS = 36;

function matches(project: Project, filter: Filter, query: string) {
  const byStatus = filter === "all" || project.status === filter;
  const q = query.trim().toLowerCase();
  return byStatus && (q === "" || project.title.toLowerCase().includes(q));
}

function countBy(filter: Filter) {
  return projects.filter((project) => filter === "all" || project.status === filter).length;
}

export function Projects() {
  const pageRef = useRef<HTMLDivElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const layoutState = useRef<ReturnType<typeof Flip.getState> | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  usePageEnter(pageRef);

  const visible = projects.filter((project) => matches(project, filter, query));

  // FLIP: o layout é capturado antes da mudança; depois do render, os cartões deslizam
  // das posições antigas para as novas e os que entram aparecem com fade + escala.
  const { contextSafe } = useGSAP(
    () => {
      const state = layoutState.current;
      layoutState.current = null;
      if (!state || prefersReducedMotion()) return;
      Flip.from(state, {
        targets: gsap.utils.toArray<HTMLElement>("[data-flip-id]", gridRef.current),
        duration: DURATION.base,
        ease: EASE.inOut,
        onEnter: (elements) =>
          gsap.fromTo(
            elements,
            { autoAlpha: 0, scale: 0.96 },
            { autoAlpha: 1, scale: 1, duration: DURATION.base, ease: EASE.out },
          ),
      });
    },
    { scope: gridRef, dependencies: [filter, query] },
  );

  const captureLayout = contextSafe(() => {
    layoutState.current = Flip.getState(gsap.utils.toArray<HTMLElement>("[data-flip-id]", gridRef.current));
  });

  function changeFilter(next: Filter) {
    if (next === filter) return;
    captureLayout();
    setFilter(next);
  }

  function changeQuery(event: ChangeEvent<HTMLInputElement>) {
    captureLayout();
    setQuery(event.target.value);
  }

  function clearFilters() {
    captureLayout();
    setFilter("all");
    setQuery("");
  }

  return (
    <div className="page" ref={pageRef}>
      <header className="page-header" data-enter>
        <div>
          <h1 className="page-title">Projects</h1>
          <p className="page-subtitle">{plural(projects.length, "project", "projects")} in your library</p>
        </div>
        <Link to="/app/new" className="btn btn--primary">
          <IconPlus /> New Project
        </Link>
      </header>

      <div className="toolbar" data-enter>
        <div className="segmented" role="group" aria-label="Filter by status">
          {FILTERS.map((item) => (
            <button
              key={item.value}
              type="button"
              className="segmented__btn"
              aria-pressed={filter === item.value}
              onClick={() => changeFilter(item.value)}
            >
              {item.label}
              <span className="segmented__count">{countBy(item.value)}</span>
            </button>
          ))}
        </div>

        <label className="search">
          <span className="sr-only">Search projects</span>
          <IconSearch />
          <input className="input" type="search" placeholder="Search…" value={query} onChange={changeQuery} />
        </label>
      </div>

      <div className="project-grid" ref={gridRef}>
        {visible.map((project) => (
          <ProjectCard key={project.id} project={project} />
        ))}
      </div>

      {visible.length === 0 && (
        <div className="empty">
          <p>No projects match your search.</p>
          <button type="button" className="btn btn--ghost btn--sm" onClick={clearFilters}>
            Clear filters
          </button>
        </div>
      )}
    </div>
  );
}

function ProjectCard({ project }: { project: Project }) {
  return (
    <Link to={`/app/projects/${project.id}`} className="project-card" data-flip-id={project.id} data-enter>
      <div className="project-card__thumb surface-dark">
        <Waveform
          bars={THUMB_BARS}
          ranges={toRanges(project.clips, project.durationSec, THUMB_BARS)}
          seed={seedFrom(project.id)}
        />
        <span className="project-card__duration">{formatTime(project.durationSec)}</span>
      </div>
      <div className="project-card__body">
        <h2 className="project-card__title">{project.title}</h2>
        <div className="project-card__meta">
          <span>{plural(project.clips.length, "clip", "clips")}</span>
          <span aria-hidden="true">·</span>
          <span>{formatDate(project.updatedAt)}</span>
          <StatusBadge status={project.status} />
        </div>
      </div>
    </Link>
  );
}