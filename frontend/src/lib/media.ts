// Reads files imported into the editor. They stay in the browser (object URLs)
// until the API takes uploads.

import { IMAGE_LENGTH, createId, type AssetKind, type MediaAsset } from "./editor";

export const ACCEPTED_MEDIA = "video/*,audio/*,image/*";

function kindOf(file: File): AssetKind | null {
  const [type] = file.type.split("/");
  return type === "video" || type === "audio" || type === "image" ? type : null;
}

export function readDuration(url: string, kind: "video" | "audio"): Promise<number> {
  return new Promise((resolve) => {
    const element = document.createElement(kind);
    element.preload = "metadata";
    element.onloadedmetadata = () => resolve(Number.isFinite(element.duration) ? element.duration : 0);
    element.onerror = () => resolve(0);
    element.src = url;
  });
}

/** Null when the file is not media the browser can play. */
export async function readMediaFile(file: File): Promise<MediaAsset | null> {
  const kind = kindOf(file);
  if (!kind) return null;
  const url = URL.createObjectURL(file);
  const duration = kind === "image" ? IMAGE_LENGTH : await readDuration(url, kind);
  if (duration <= 0) {
    URL.revokeObjectURL(url);
    return null;
  }
  return { id: createId("asset"), kind, name: file.name, duration, source: "upload", url, size: file.size };
}

const FRAME_WIDTH = 160;

/**
 * Draws `count` evenly spaced stills of a video (small JPEG data URLs), one at a time,
 * calling `onFrames` with the list so far. Returns a function that stops it.
 */
export function readVideoFrames(
  url: string,
  duration: number,
  count: number,
  onFrames: (frames: string[]) => void,
): () => void {
  const video = document.createElement("video");
  const canvas = document.createElement("canvas");
  const frames: string[] = [];

  // The middle of each slice, so a black fade-in doesn't become the first still.
  const seekNext = () => {
    video.currentTime = ((frames.length + 0.5) / count) * duration;
  };

  video.muted = true;
  video.preload = "auto";
  video.onloadeddata = () => {
    canvas.width = FRAME_WIDTH;
    canvas.height = Math.round((FRAME_WIDTH * video.videoHeight) / Math.max(1, video.videoWidth));
    seekNext();
  };
  video.onseeked = () => {
    canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
    frames.push(canvas.toDataURL("image/jpeg", 0.7));
    onFrames([...frames]);
    if (frames.length < count) seekNext();
  };
  video.src = url;

  return () => {
    video.onloadeddata = null;
    video.onseeked = null;
    video.removeAttribute("src");
    video.load();
  };
}