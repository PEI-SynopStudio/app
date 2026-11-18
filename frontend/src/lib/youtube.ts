import { seedFrom } from "./utils";
const VIDEO_ID = /^[\w-]{11}$/;
const HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"]);
const ID_PATHS = new Set(["shorts", "embed", "live"]);

/**
 * Extracts the video id from the usual YouTube link formats, with or without "https://".
 * "youtu.be/aBcDeFgHiJk" · "youtube.com/watch?v=aBcDeFgHiJk" · ".../shorts/aBcDeFgHiJk" → "aBcDeFgHiJk"
 */
export function parseYouTubeId(input: string): string | null {
  const text = input.trim();
  if (!text) return null;

  let url: URL;
  try {
    url = new URL(/^https?:\/\//i.test(text) ? text : `https://${text}`);
  } catch {
    return null;
  }

  const host = url.hostname.toLowerCase();
  const [, first = "", second = ""] = url.pathname.split("/");
  let id: string | null = null;

  if (host === "youtu.be") id = first;
  else if (HOSTS.has(host)) {
    if (first === "watch") id = url.searchParams.get("v");
    else if (ID_PATHS.has(first)) id = second;
  }

  return id && VIDEO_ID.test(id) ? id : null;
}

/** Canonical link, without playlists or tracking parameters. */
export function youTubeWatchUrl(videoId: string): string {
  return `https://www.youtube.com/watch?v=${videoId}`;
}

export function youTubeThumbnail(videoId: string): string {
  return `https://i.ytimg.com/vi/${videoId}/mqdefault.jpg`;
}


/** The three stills YouTube keeps for every video (around ¼, ½ and ¾ of the way in). */
export function youTubeFrames(videoId: string): string[] {
  return [1, 2, 3].map((index) => `https://i.ytimg.com/vi/${videoId}/mq${index}.jpg`);
}

/**
 * The browser can't read a YouTube video's length without YouTube's own API.
 * TODO(api): GET /videos/youtube/:id → { duration }. Until then, a stable demo length (10–16 min).
 */
export function fetchYouTubeDuration(videoId: string): Promise<number> {
  const seconds = 600 + Math.round(seedFrom(videoId) * 36);
  return new Promise((resolve) => window.setTimeout(() => resolve(seconds), 400));
}