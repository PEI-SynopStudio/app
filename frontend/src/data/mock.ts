// Demo data until the frontend is connected to the API (/projects).

import type { TimeRange } from "../lib/utils";
import type { AspectRatio, CaptionSettings, Language } from "./options";

export type ProjectStatus = "draft" | "archived";

export interface Clip {
  id: string;
  title: string;
  scenes: TimeRange[]; // parts of the original video, in the order they play in the clip
  subtitleLanguage?: Language; // auto-translated subtitles and transcripts; unset = the spoken language
}

export interface Project {
  id: string;
  title: string;
  description?: string;
  status: ProjectStatus;
  durationSec: number;
  analyzed: TimeRange; // the part of the video the AI watched, picked at creation
  language: Language; // spoken in the video, picked by the user at creation
  format: AspectRatio;
  captions: CaptionSettings | null; // null = no subtitles
  createdAt: string;
  updatedAt: string;
  clips: Clip[];
}

/** A scene with its place in the clip: `at` seconds from the clip start. */
export interface PlacedScene extends TimeRange {
  at: number;
}

export interface SharedClip {
  project: Project;
  clip: Clip;
  sharedBy: string;
}

// Who shared a clip, until the API resolves share links (Viewers have no account).
const MOCK_SHARED_BY = "Demo User";

function clip(
  id: string,
  title: string,
  scenes: [start: number, length: number][],
  subtitleLanguage?: Language,
): Clip {
  return { id, title, scenes: scenes.map(([start, length]) => ({ start, end: start + length })), subtitleLanguage };
}

export const projects: Project[] = [
  {
    id: "entrevista-ep12",
    title: "Interview — Episode 12",
    description: "Long conversation about launching products with small teams.",
    status: "draft",
    durationSec: 4368,
    analyzed: { start: 0, end: 4368 },
    language: "en",
    format: "9:16",
    captions: { style: "bold" },
    createdAt: "2026-10-28T10:12:00Z",
    updatedAt: "2026-10-30T16:40:00Z",
    clips: [
      clip("ep12-1", "The Question That Changed Everything", [[312, 14], [340, 16], [1204, 12]], "pt-PT"),
      clip("ep12-2", "The Error No One Sees", [[1268, 20], [1301, 15]]),
      clip("ep12-3", "Three Habits of Fast Launchers", [[2410, 18], [2466, 17], [2530, 16]]),
      clip("ep12-4", "Final Advice", [[3790, 28]]),
    ],
  },
  {
    id: "podcast-tec-31",
    title: "Tech Podcast #31",
    status: "draft",
    durationSec: 3125,
    analyzed: { start: 0, end: 3125 },
    language: "pt-PT",
    format: "9:16",
    captions: { style: "classic" },
    createdAt: "2026-10-24T09:00:00Z",
    updatedAt: "2026-10-29T11:05:00Z",
    clips: [
      clip("tec31-1", "Why AI Won't Replace You", [[145, 12], [171, 18]]),
      clip("tec31-2", "The Ideal Stack in 2026", [[820, 15], [861, 14], [902, 16]]),
      clip("tec31-3", "Monolith or Microservices?", [[1510, 21], [1588, 17]]),
      clip("tec31-4", "The Underestimated Tool", [[2260, 25]]),
      clip("tec31-5", "Predictions for the Next Year", [[2890, 11], [2925, 12], [2988, 10]]),
    ],
  },
  {
    id: "aula-sd",
    title: "Open Lecture — Distributed Systems",
    description: "Full recording of this semester's open lecture.",
    status: "draft",
    durationSec: 5400,
    analyzed: { start: 300, end: 4800 },
    language: "pt-PT",
    format: "16:9",
    captions: { style: "boxed" },
    createdAt: "2026-10-15T14:30:00Z",
    updatedAt: "2026-10-26T18:20:00Z",
    clips: [
      clip("sd-1", "Consensus Explained in 1 Minute", [[600, 24], [655, 19], [1130, 15]]),
      clip("sd-2", "The CAP Theorem in Practice", [[2350, 26], [2412, 18]]),
      clip("sd-3", "When the Network Fails", [[4100, 22], [4171, 18]]),
    ],
  },
  {
    id: "keynote-2026",
    title: "Launch Keynote",
    status: "archived",
    durationSec: 2710,
    analyzed: { start: 0, end: 2710 },
    language: "en",
    format: "1:1",
    captions: null,
    createdAt: "2026-09-30T17:00:00Z",
    updatedAt: "2026-10-05T10:00:00Z",
    clips: [
      clip("kn-1", "The Opening", [[60, 22]]),
      clip("kn-2", "Live Demo", [[420, 12], [451, 18]]),
      clip("kn-3", "Yearly Numbers", [[905, 15], [940, 12]]),
      clip("kn-4", "Roadmap", [[1440, 20], [1502, 15]]),
      clip("kn-5", "Partners", [[1980, 24]]),
      clip("kn-6", "The Closing", [[2500, 13], [2610, 16]]),
    ],
  },
  {
    id: "webinar-onboarding",
    title: "Onboarding Webinar",
    status: "archived",
    durationSec: 1980,
    analyzed: { start: 120, end: 1620 },
    language: "en",
    format: "4:5",
    captions: { style: "minimal" },
    createdAt: "2026-09-12T15:00:00Z",
    updatedAt: "2026-09-20T09:30:00Z",
    clips: [
      clip("wb-1", "First Steps", [[300, 22], [348, 18]]),
      clip("wb-2", "Productivity Tips", [[1200, 20], [1260, 16]]),
    ],
  },
  {
    id: "vlog-lisboa",
    title: "Vlog — Trip to Lisbon",
    status: "draft",
    durationSec: 1460,
    analyzed: { start: 0, end: 1460 },
    language: "pt-PT",
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
    if (found) return { project, clip: found, sharedBy: MOCK_SHARED_BY };
  }
  return undefined;
}

export function clipLength(item: Clip): number {
  return item.scenes.reduce((total, scene) => total + scene.end - scene.start, 0);
}

/** Lays the scenes end to end, as they play in the clip. */
export function placeScenes(item: Clip): PlacedScene[] {
  let at = 0;
  return item.scenes.map((scene) => {
    const placed = { ...scene, at };
    at += scene.end - scene.start;
    return placed;
  });
}

/** Every scene of these clips, tagged with its clip id (for waveform highlights). */
export function sceneRanges(clips: Clip[]) {
  return clips.flatMap((item) => item.scenes.map((scene) => ({ id: item.id, ...scene })));
}