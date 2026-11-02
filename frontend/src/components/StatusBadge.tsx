import type { ProjectStatus } from "../data/mock";

const LABEL: Record<ProjectStatus, string> = {
  draft: "Draft",
  archived: "Archived",
};

export function StatusBadge({ status }: { status: ProjectStatus }) {
  return <span className={`badge badge--${status}`}>{LABEL[status]}</span>;
}