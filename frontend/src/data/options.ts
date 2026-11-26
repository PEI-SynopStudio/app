// Output options shared by project creation, the clip editor, project detail and the viewer.

export type AspectRatio = "9:16" | "1:1" | "4:5" | "16:9";

export const FORMATS: { value: AspectRatio; label: string; hint: string }[] = [
  { value: "9:16", label: "Vertical", hint: "Reels, TikTok, Shorts" },
  { value: "1:1", label: "Square", hint: "Feed posts" },
  { value: "4:5", label: "Portrait", hint: "Instagram and LinkedIn feed" },
  { value: "16:9", label: "Landscape", hint: "YouTube, presentations" },
];

export const FORMAT_RATIO: Record<AspectRatio, number> = {
  "9:16": 9 / 16,
  "1:1": 1,
  "4:5": 4 / 5,
  "16:9": 16 / 9,
};

/** Languages the AI transcribes from and translates into. */
export type Language = "pt-PT" | "en" | "es";

export const LANGUAGES: { value: Language; label: string }[] = [
  { value: "pt-PT", label: "Português (PT)" },
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
];

export function languageLabel(language: Language): string {
  return LANGUAGES.find((item) => item.value === language)?.label ?? language;
}

export type CaptionStyle = "classic" | "bold" | "boxed" | "minimal";

/**
 * Subtitles are always written in the language spoken in the video.
 * Translations are picked per clip, on the project page.
 */
export interface CaptionSettings {
  style: CaptionStyle;
}

// Placeholder looks until the real caption styles are designed.
export const CAPTION_STYLES: { value: CaptionStyle; label: string }[] = [
  { value: "classic", label: "Classic" },
  { value: "bold", label: "Bold" },
  { value: "boxed", label: "Boxed" },
  { value: "minimal", label: "Minimal" },
];

export const DEFAULT_CAPTIONS: CaptionSettings = { style: "classic" };

export function captionStyleLabel(style: CaptionStyle): string {
  return CAPTION_STYLES.find((item) => item.value === style)?.label ?? style;
}

/** Preview text in the editor, in the clip's language. */
export const CAPTION_SAMPLE: Record<Language, string> = {
  "pt-PT": "É assim que as legendas vão aparecer",
  en: "This is how your subtitles will look",
  es: "Así se verán tus subtítulos",
};

/** Short preview text for the style cards (the language isn't known yet when they're picked). */
export const CAPTION_SHORT = "Hello everyone";