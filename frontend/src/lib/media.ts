// Reads files imported into the editor. They stay in the browser (object URLs)
// until the API takes uploads.

import { IMAGE_LENGTH, createId, type AssetKind, type MediaAsset } from "./editor";

export const ACCEPTED_MEDIA = "video/*,audio/*,image/*";

function kindOf(file: File): AssetKind | null {
  const [type] = file.type.split("/");
  return type === "video" || type === "audio" || type === "image" ? type : null;
}

function readDuration(url: string, kind: "video" | "audio"): Promise<number> {
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