// Demo data until the frontend is connected to the API (/projects).

import type { AspectRatio, CaptionSettings } from "./options";

export type ProjectStatus = "draft" | "archived";

export interface Clip {
  id: string;
  title: string;
  start: number; // seconds
  end: number; // seconds
  score: number; // relevance 0–100
}

export interface Project {
  id: string;
  title: string;
  description?: string;
  status: ProjectStatus;
  durationSec: number;
  format: AspectRatio;
  captions: CaptionSettings | null; // null = no subtitles
  createdAt: string;
  updatedAt: string;
  clips: Clip[];
}

export interface SharedClip {
  project: Project;
  clip: Clip;
  sharedBy: string;
}

export const currentUser = {
  name: "Demo User",
  email: "demo@example.com",
};

function clip(id: string, title: string, start: number, length: number, score: number): Clip {
  return { id, title, start, end: start + length, score };
}

export const projects: Project[] = [
  {
    id: "entrevista-ep12",
    title: "Interview — Episode 12",
    description: "Long conversation about launching products with small teams.",
    status: "draft",
    durationSec: 4368,
    format: "9:16",
    captions: { language: "en", style: "bold" },
    createdAt: "2026-10-28T10:12:00Z",
    updatedAt: "2026-10-30T16:40:00Z",
    clips: [
      clip("ep12-1", "The Question That Changed Everything", 312, 42, 94),
      clip("ep12-2", "The Error No One Sees", 1268, 35, 88),
      clip("ep12-3", "Three Habits of Fast Launchers", 2410, 51, 91),
      clip("ep12-4", "Final Advice", 3790, 28, 82),
    ],
  },
  {
    id: "podcast-tec-31",
    title: "Tech Podcast #31",
    status: "draft",
    durationSec: 3125,
    format: "9:16",
    captions: { language: "pt-PT", style: "classic" },
    createdAt: "2026-10-24T09:00:00Z",
    updatedAt: "2026-10-29T11:05:00Z",
    clips: [
      clip("tec31-1", "Why AI Won't Replace You", 145, 30, 90),
      clip("tec31-2", "The Ideal Stack in 2026", 820, 45, 85),
      clip("tec31-3", "Monolith or Microservices?", 1510, 38, 93),
      clip("tec31-4", "The Underestimated Tool", 2260, 25, 79),
      clip("tec31-5", "Predictions for the Next Year", 2890, 33, 84),
    ],
  },
  {
    id: "aula-sd",
    title: "Open Lecture — Distributed Systems",
    description: "Full recording of this semester's open lecture.",
    status: "draft",
    durationSec: 5400,
    format: "16:9",
    captions: { language: "pt-PT", style: "boxed" },
    createdAt: "2026-10-15T14:30:00Z",
    updatedAt: "2026-10-26T18:20:00Z",
    clips: [
      clip("sd-1", "Consensus Explained in 1 Minute", 600, 58, 92),
      clip("sd-2", "The CAP Theorem in Practice", 2350, 44, 87),
      clip("sd-3", "When the Network Fails", 4100, 40, 81),
    ],
  },
  {
    id: "keynote-2026",
    title: "Launch Keynote",
    status: "archived",
    durationSec: 2710,
    format: "1:1",
    captions: null,
    createdAt: "2026-09-30T17:00:00Z",
    updatedAt: "2026-10-05T10:00:00Z",
    clips: [
      clip("kn-1", "The Opening", 60, 22, 86),
      clip("kn-2", "Live Demo", 420, 30, 95),
      clip("kn-3", "Yearly Numbers", 905, 27, 80),
      clip("kn-4", "Roadmap", 1440, 35, 83),
      clip("kn-5", "Partners", 1980, 24, 72),
      clip("kn-6", "The Closing", 2500, 29, 78),
    ],
  },
  {
    id: "webinar-onboarding",
    title: "Onboarding Webinar",
    status: "archived",
    durationSec: 1980,
    format: "4:5",
    captions: { language: "en", style: "minimal" },
    createdAt: "2026-09-12T15:00:00Z",
    updatedAt: "2026-09-20T09:30:00Z",
    clips: [
      clip("wb-1", "First Steps", 300, 40, 81),
      clip("wb-2", "Productivity Tips", 1200, 36, 77),
    ],
  },
  {
    id: "vlog-lisboa",
    title: "Vlog — Trip to Lisbon",
    status: "draft",
    durationSec: 1460,
    format: "9:16",
    captions: null,
    createdAt: "2026-10-30T20:10:00Z",
    updatedAt: "2026-10-30T20:10:00Z",
    clips: [],
  },
];

export function getProject(id: string | undefined): Project | undefined {
  return projects.find((project) => project.id === id);
}

export function getClip(projectId: string | undefined, clipId: string | undefined) {
  const project = getProject(projectId);
  const found = project?.clips.find((item) => item.id === clipId);
  return project && found ? { project, clip: found } : undefined;
}

/** Viewer links. TODO(api): resolve a share token instead of the clip id. */
export function getSharedClip(shareId: string | undefined): SharedClip | undefined {
  for (const project of projects) {
    const found = project.clips.find((item) => item.id === shareId);
    if (found) return { project, clip: found, sharedBy: currentUser.name };
  }
  return undefined;
}