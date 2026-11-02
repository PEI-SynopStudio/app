export interface WaveRange {
  id: string;
  from: number; // índice da primeira barra (inclusive)
  to: number; // índice da última barra (inclusive)
}

/** 75 → "1:15" · 4368 → "1:12:48" */
export function formatTime(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = String(s % 60).padStart(2, "0");
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}`
    : `${minutes}:${seconds}`;
}


/** 75.4 → "1:15.4" — for editing, where tenths of a second matter. */
export function formatTimecode(totalSeconds: number): string {
  const tenths = Math.round(Math.max(0, totalSeconds) * 10);
  return `${formatTime(Math.floor(tenths / 10))}.${tenths % 10}`;
}

const dateFormat = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

export function formatDate(iso: string): string {
  return dateFormat.format(new Date(iso));
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 ** 2) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** Número estável (0–10) derivado de um texto — varia visuais sem aleatoriedade. */
export function seedFrom(text: string): number {
  let hash = 0;
  for (const char of text) hash = (hash * 31 + char.charCodeAt(0)) % 1000;
  return hash / 100;
}

/** Converte clipes (em segundos) em intervalos de barras de uma waveform. */
export function toRanges(
  clips: ReadonlyArray<{ id: string; start: number; end: number }>,
  duration: number,
  bars: number,
): WaveRange[] {
  return clips.map((clip) => {
    const from = Math.min(bars - 1, Math.floor((clip.start / duration) * bars));
    const to = Math.min(bars - 1, Math.max(from, Math.ceil((clip.end / duration) * bars) - 1));
    return { id: clip.id, from, to };
  });
}