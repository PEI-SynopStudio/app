// Output options shared by project creation, the clip editor and the viewer.

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

export type CaptionLanguage = "pt-PT" | "en" | "es";
export type CaptionStyle = "classic" | "bold" | "boxed" | "minimal";

export interface CaptionSettings {
  language: CaptionLanguage;
  style: CaptionStyle;
}

export const CAPTION_LANGUAGES: { value: CaptionLanguage; label: string }[] = [
  { value: "pt-PT", label: "Português (PT)" },
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
];

// Placeholder looks until the real caption styles are designed.
export const CAPTION_STYLES: { value: CaptionStyle; label: string }[] = [
  { value: "classic", label: "Classic" },
  { value: "bold", label: "Bold" },
  { value: "boxed", label: "Boxed" },
  { value: "minimal", label: "Minimal" },
];

export const DEFAULT_CAPTIONS: CaptionSettings = { language: "en", style: "classic" };

/** Preview text in the player. */
export const CAPTION_SAMPLE: Record<CaptionLanguage, string> = {
  "pt-PT": "É assim que as legendas vão aparecer",
  en: "This is how your subtitles will look",
  es: "Así se verán tus subtítulos",
};

/** Short preview text for the style cards. */
export const CAPTION_SHORT: Record<CaptionLanguage, string> = {
  "pt-PT": "Olá a todos",
  en: "Hello everyone",
  es: "Hola a todos",
};

export function captionLanguageLabel(language: CaptionLanguage): string {
  return CAPTION_LANGUAGES.find((item) => item.value === language)?.label ?? language;
}