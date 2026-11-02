// Clip editor model: the timeline document and the pure maths behind it.
// No React in here, so the API can store and replay the same shape later.

import type { Clip, Project } from "../data/mock";
import type { AspectRatio, CaptionSettings } from "../data/options";

export type TrackKind = "video" | "overlay" | "text" | "audio";

export interface Track {
  id: string;
  kind: TrackKind;
  label: string;
  muted?: boolean;
  hidden?: boolean;
}

export type AssetKind = "video" | "image" | "audio";

export interface MediaAsset {
  id: string;
  kind: AssetKind;
  name: string;
  duration: number; // seconds; for images, the default length on the timeline
  source: "project" | "upload"; // "project" = a piece of the recording already on the server
  offset?: number; // where a project asset starts inside the recording
  url?: string; // object URL of an upload, until the API hosts it
  size?: number; // bytes
}

export type TransitionType = "fade" | "dissolve" | "slide-left" | "slide-up" | "zoom" | "wipe";

export interface Transition {
  type: TransitionType;
  duration: number; // seconds
}

export type TextColor = "light" | "ink" | "accent";
export type TextPosition = "top" | "center" | "bottom";
export type TextBackground = "none" | "dark" | "light" | "accent";
export type TextWeight = 500 | 600 | 700;

export interface TextLayer {
  content: string;
  size: number; // percentage of the frame width
  weight: TextWeight;
  color: TextColor;
  position: TextPosition;
  background: TextBackground;
}

export interface TimelineItem {
  id: string;
  trackId: string;
  kind: "media" | "text";
  start: number; // seconds on the timeline
  duration: number;
  assetId?: string;
  inPoint?: number; // seconds cut from the head of the asset
  text?: TextLayer;
  transitionIn?: Transition;
  transitionOut?: Transition;
  volume?: number; // 0–1
  opacity?: number; // 0–1
  fit?: "cover" | "contain";
}

export interface EditorDoc {
  format: AspectRatio;
  captions: CaptionSettings | null;
  tracks: Track[];
  items: TimelineItem[];
}

/** What an item shows: the kind of its asset, or text. */
export type ItemContent = AssetKind | "text";

export const MIN_LENGTH = 0.2; // shortest item, seconds
export const MAX_INSERT = 60; // long media comes in as one minute; the edge drags out to the rest
export const IMAGE_LENGTH = 4;
export const TEXT_LENGTH = 3;
export const TRANSITION_LENGTH = 0.5;
export const SNAP_PX = 8;
export const ZOOM_LEVELS = [12, 24, 48, 80, 140, 240]; // pixels per second
export const DEFAULT_ZOOM = 3;

const EPSILON = 0.001;
const SOURCE_ID = "source";

/** Top of the list is drawn on top of the frame. */
export const DEFAULT_TRACKS: Track[] = [
  { id: "track-text", kind: "text", label: "Text" },
  { id: "track-overlay", kind: "overlay", label: "Overlay" },
  { id: "track-video", kind: "video", label: "Video" },
  { id: "track-audio", kind: "audio", label: "Audio" },
];

const TRACK_ACCEPTS: Record<TrackKind, ItemContent[]> = {
  video: ["video", "image"],
  overlay: ["video", "image"],
  text: ["text"],
  audio: ["audio"],
};

export const TRANSITIONS: { value: TransitionType; label: string; hint: string }[] = [
  { value: "fade", label: "Fade", hint: "In from black" },
  { value: "dissolve", label: "Dissolve", hint: "Blends with the layer below" },
  { value: "slide-left", label: "Slide", hint: "Pushes in from the right" },
  { value: "slide-up", label: "Rise", hint: "Pushes in from below" },
  { value: "zoom", label: "Zoom", hint: "Scales into place" },
  { value: "wipe", label: "Wipe", hint: "Reveals left to right" },
];

/** Audio has no picture, so its only transition is a volume fade. */
export const AUDIO_TRANSITIONS = TRANSITIONS.filter((transition) => transition.value === "fade");

export const TEXT_PRESETS: { id: string; label: string; layer: TextLayer }[] = [
  {
    id: "title",
    label: "Title",
    layer: { content: "Your title", size: 10, weight: 700, color: "light", position: "center", background: "none" },
  },
  {
    id: "subtitle",
    label: "Subtitle",
    layer: { content: "A short subtitle", size: 6, weight: 500, color: "light", position: "center", background: "none" },
  },
  {
    id: "lower-third",
    label: "Lower third",
    layer: { content: "Name Surname · Role", size: 4.5, weight: 600, color: "ink", position: "bottom", background: "light" },
  },
  {
    id: "callout",
    label: "Callout",
    layer: { content: "Key takeaway", size: 5.5, weight: 700, color: "ink", position: "top", background: "accent" },
  },
];

export const TEXT_COLORS: { value: TextColor; label: string }[] = [
  { value: "light", label: "White" },
  { value: "ink", label: "Ink" },
  { value: "accent", label: "Orange" },
];

// Drag payloads. The content kind is part of the type because drop targets can read
// the types (not the data) while a drag is still over them.
export const DRAG_TYPES: Record<ItemContent, string> = {
  video: "application/x-synop-video",
  image: "application/x-synop-image",
  audio: "application/x-synop-audio",
  text: "application/x-synop-text",
};
export const DRAG_TRANSITION = "application/x-synop-transition";

let lastId = 0;

export function createId(prefix: string): string {
  lastId += 1;
  return `${prefix}-${Date.now().toString(36)}-${lastId}`;
}

export function itemEnd(item: TimelineItem): number {
  return item.start + item.duration;
}

export function contentEnd(items: TimelineItem[]): number {
  return items.reduce((end, item) => Math.max(end, itemEnd(item)), 0);
}

export function itemContent(item: TimelineItem, assets: Record<string, MediaAsset>): ItemContent | null {
  if (item.kind === "text") return "text";
  const asset: MediaAsset | undefined = item.assetId ? assets[item.assetId] : undefined;
  return asset?.kind ?? null;
}

export function canPlace(track: Track, content: ItemContent | null): boolean {
  return content !== null && TRACK_ACCEPTS[track.kind].includes(content);
}

export function draggedContent(types: readonly string[]): ItemContent | null {
  const contents = Object.keys(DRAG_TYPES) as ItemContent[];
  return contents.find((content) => types.includes(DRAG_TYPES[content])) ?? null;
}

export function isTransitionType(value: string): value is TransitionType {
  return TRANSITIONS.some((transition) => transition.value === value);
}

export function insertLength(asset: MediaAsset): number {
  return asset.kind === "image" ? IMAGE_LENGTH : Math.min(asset.duration, MAX_INSERT);
}

/** How long the item can get: video and audio stop at the end of their file. */
export function maxLength(item: TimelineItem, asset: MediaAsset | undefined): number {
  if (item.kind === "text" || !asset || asset.kind === "image") return Infinity;
  return asset.duration - (item.inPoint ?? 0);
}

/** True when [start, start + duration) would overlap another item on the track. */
export function collides(
  items: TimelineItem[],
  trackId: string,
  start: number,
  duration: number,
  ignoreId?: string,
): boolean {
  const end = start + duration;
  return items.some(
    (other) =>
      other.trackId === trackId && other.id !== ignoreId && other.start < end - EPSILON && itemEnd(other) > start + EPSILON,
  );
}

/** First start at or after `from` where an item of this length fits on the track. */
export function findFreeStart(items: TimelineItem[], trackId: string, from: number, duration: number): number {
  const others = items.filter((item) => item.trackId === trackId).sort((a, b) => a.start - b.start);
  let start = Math.max(0, from);
  for (const other of others) {
    if (itemEnd(other) <= start + EPSILON) continue;
    if (other.start >= start + duration - EPSILON) break;
    start = itemEnd(other);
  }
  return start;
}

/** The neighbours on each side, which a trim cannot pass. */
export function trimBounds(items: TimelineItem[], item: TimelineItem): { min: number; max: number } {
  let min = 0;
  let max = Infinity;
  for (const other of items) {
    if (other.trackId !== item.trackId || other.id === item.id) continue;
    if (itemEnd(other) <= item.start + EPSILON) min = Math.max(min, itemEnd(other));
    else if (other.start >= itemEnd(item) - EPSILON) max = Math.min(max, other.start);
  }
  return { min, max };
}

export function snapPoints(items: TimelineItem[], playhead: number): number[] {
  const points = [0, playhead];
  for (const item of items) points.push(item.start, itemEnd(item));
  return points;
}

export function snapTime(value: number, points: number[], threshold: number): number {
  let best = value;
  let distance = threshold;
  for (const point of points) {
    const gap = Math.abs(point - value);
    if (gap < distance) {
      best = point;
      distance = gap;
    }
  }
  return best;
}

/** Snaps a moving item by whichever of its two edges is closer to a point. */
export function snapStart(start: number, duration: number, points: number[], threshold: number): number {
  let best = start;
  let distance = threshold;
  for (const point of points) {
    for (const candidate of [point, point - duration]) {
      const gap = Math.abs(candidate - start);
      if (gap < distance) {
        best = candidate;
        distance = gap;
      }
    }
  }
  return best;
}

export function splitItem(item: TimelineItem, at: number, rightId: string): [TimelineItem, TimelineItem] | null {
  const offset = at - item.start;
  if (offset < MIN_LENGTH || item.duration - offset < MIN_LENGTH) return null;
  const left: TimelineItem = { ...item, duration: offset, transitionOut: undefined };
  const right: TimelineItem = {
    ...item,
    id: rightId,
    start: at,
    duration: item.duration - offset,
    inPoint: item.kind === "media" ? (item.inPoint ?? 0) + offset : undefined,
    transitionIn: undefined,
  };
  return [left, right];
}

/** The item under the playhead on a track (items on one track never overlap). */
export function itemAt(items: TimelineItem[], trackId: string, time: number): TimelineItem | undefined {
  return items.find((item) => item.trackId === trackId && time >= item.start && time < itemEnd(item));
}

// ---------- Transitions ----------

function easeInOut(p: number): number {
  return p < 0.5 ? 4 * p ** 3 : 1 - (-2 * p + 2) ** 3 / 2;
}

/** 0 → 1 while the transition runs, 1 outside it. `elapsed` counts from the edge it sits on. */
function progress(transition: Transition | undefined, elapsed: number, length: number): number {
  if (!transition) return 1;
  const duration = Math.min(transition.duration, length);
  if (duration <= 0 || elapsed >= duration) return 1;
  return easeInOut(Math.max(0, elapsed) / duration);
}

export interface LayerLook {
  opacity: number;
  transform?: string;
  clipPath?: string;
  filter?: string;
}

/** How a layer looks at `time`, with its in and out transitions applied. */
export function layerLook(item: TimelineItem, time: number): LayerLook {
  let opacity = item.opacity ?? 1;
  let x = 0;
  let y = 0;
  let scale = 1;
  let brightness = 1;
  let clipLeft = 0;
  let clipRight = 0;

  // direction 1 = entering, -1 = leaving (slides exit on the opposite side)
  const apply = (transition: Transition, p: number, direction: 1 | -1) => {
    const rest = 1 - p;
    switch (transition.type) {
      case "fade":
        brightness *= p;
        break;
      case "dissolve":
        opacity *= p;
        break;
      case "slide-left":
        x += direction * rest * 100;
        break;
      case "slide-up":
        y += direction * rest * 100;
        break;
      case "zoom":
        scale *= 1 + direction * rest * 0.2;
        opacity *= p;
        break;
      case "wipe":
        if (direction === 1) clipRight = rest * 100;
        else clipLeft = rest * 100;
        break;
    }
  };

  if (item.transitionIn) apply(item.transitionIn, progress(item.transitionIn, time - item.start, item.duration), 1);
  if (item.transitionOut) apply(item.transitionOut, progress(item.transitionOut, itemEnd(item) - time, item.duration), -1);

  return {
    opacity,
    transform: x || y || scale !== 1 ? `translate(${x}%, ${y}%) scale(${scale})` : undefined,
    clipPath: clipLeft || clipRight ? `inset(0 ${clipRight}% 0 ${clipLeft}%)` : undefined,
    filter: brightness < 1 ? `brightness(${brightness})` : undefined,
  };
}

/** Volume at `time`: any transition on a sound also fades it. */
export function itemGain(item: TimelineItem, time: number): number {
  const fadeIn = progress(item.transitionIn, time - item.start, item.duration);
  const fadeOut = progress(item.transitionOut, itemEnd(item) - time, item.duration);
  return (item.volume ?? 1) * fadeIn * fadeOut;
}

// ---------- Starting point ----------

/** The recording and every clip the AI cut from it, ready to reuse in the edit. */
export function projectAssets(project: Project): MediaAsset[] {
  const recording: MediaAsset = {
    id: SOURCE_ID,
    kind: "video",
    name: "Full recording",
    duration: project.durationSec,
    source: "project",
    offset: 0,
  };
  const clips = project.clips.map(
    (clip): MediaAsset => ({
      id: `clip-${clip.id}`,
      kind: "video",
      name: clip.title,
      duration: clip.end - clip.start,
      source: "project",
      offset: clip.start,
    }),
  );
  return [recording, ...clips];
}

/** A new edit starts from the AI cut: the clip's range of the recording on the video track. */
export function createDoc(project: Project, clip: Clip): EditorDoc {
  return {
    format: project.format,
    captions: project.captions,
    tracks: DEFAULT_TRACKS,
    items: [
      {
        id: "item-main",
        trackId: "track-video",
        kind: "media",
        assetId: SOURCE_ID,
        start: 0,
        duration: clip.end - clip.start,
        inPoint: clip.start,
        volume: 1,
        opacity: 1,
        fit: "cover",
      },
    ],
  };
}