// Demo transcripts until the API returns the real ones.
// Times are in seconds from the start of the clip.

import { formatClock, seedFrom } from "../lib/utils";
import { clipLength, placeScenes, type Clip } from "./mock";
import type { Language } from "./options";

export type TranscriptKind = "general" | "subtitles" | "audiovisual";

export interface TranscriptLine {
  start: number;
  end: number;
  text: string;
  speaker?: string; // general transcript only
}

export type ClipTranscripts = Record<TranscriptKind, TranscriptLine[]>;

export const TRANSCRIPT_KINDS: { value: TranscriptKind; label: string; hint: string }[] = [
  { value: "general", label: "General", hint: "Every line with its time range and who said it." },
  { value: "subtitles", label: "Subtitles", hint: "The final subtitles, exactly as they appear on the clip." },
  {
    value: "audiovisual",
    label: "Audio description",
    hint: "What happens on screen in each scene, described for blind and low-vision viewers.",
  },
];

interface Bank {
  speakers: [string, string];
  lines: [0 | 1, string][];
  scenes: string[];
}

const BANKS: Record<Language, Bank> = {
  en: {
    speakers: ["Speaker 1", "Speaker 2"],
    lines: [
      [0, "So, what was the moment you realised it had to change?"],
      [1, "Honestly, it was when we stopped guessing and started asking our users."],
      [1, "We had a list of features nobody had actually asked for."],
      [0, "And how did the team react to that?"],
      [1, "At first, not well. Nobody likes to throw work away."],
      [1, "But two weeks later we shipped something people really used."],
      [0, "That's the part most teams skip."],
      [1, "Exactly. Talk to people first, build second."],
    ],
    scenes: [
      "Two people sit facing each other at a wooden table, with microphones between them.",
      "Close-up of the guest, who smiles while answering.",
      "The host leans forward and nods.",
      "Wide shot of the studio, with warm lights in the background.",
      "The guest gestures with both hands to make a point.",
    ],
  },
  "pt-PT": {
    speakers: ["Orador 1", "Orador 2"],
    lines: [
      [0, "Então, qual foi o momento em que percebeste que tinha de mudar?"],
      [1, "Sinceramente, foi quando deixámos de adivinhar e começámos a perguntar aos utilizadores."],
      [1, "Tínhamos uma lista de funcionalidades que ninguém tinha pedido."],
      [0, "E como é que a equipa reagiu a isso?"],
      [1, "Ao início, mal. Ninguém gosta de deitar trabalho fora."],
      [1, "Mas duas semanas depois lançámos algo que as pessoas usavam mesmo."],
      [0, "É essa a parte que a maioria das equipas salta."],
      [1, "Exatamente. Primeiro falar com as pessoas, depois construir."],
    ],
    scenes: [
      "Duas pessoas sentadas frente a frente numa mesa de madeira, com microfones entre elas.",
      "Grande plano do convidado, que sorri enquanto responde.",
      "O apresentador inclina-se para a frente e acena com a cabeça.",
      "Plano geral do estúdio, com luzes quentes ao fundo.",
      "O convidado gesticula com as duas mãos para sublinhar uma ideia.",
    ],
  },
  es: {
    speakers: ["Hablante 1", "Hablante 2"],
    lines: [
      [0, "Entonces, ¿cuál fue el momento en que te diste cuenta de que tenía que cambiar?"],
      [1, "Sinceramente, fue cuando dejamos de adivinar y empezamos a preguntar a los usuarios."],
      [1, "Teníamos una lista de funciones que nadie había pedido."],
      [0, "¿Y cómo reaccionó el equipo?"],
      [1, "Al principio, mal. A nadie le gusta tirar trabajo a la basura."],
      [1, "Pero dos semanas después lanzamos algo que la gente usaba de verdad."],
      [0, "Esa es la parte que la mayoría de los equipos se salta."],
      [1, "Exacto. Primero hablar con la gente, después construir."],
    ],
    scenes: [
      "Dos personas sentadas frente a frente en una mesa de madera, con micrófonos entre ellas.",
      "Primer plano del invitado, que sonríe mientras responde.",
      "El presentador se inclina hacia delante y asiente.",
      "Plano general del estudio, con luces cálidas al fondo.",
      "El invitado gesticula con ambas manos para remarcar una idea.",
    ],
  },
};

const PAUSE = 0.3; // silence between spoken lines
const WORDS_PER_CUE = 7; // subtitles stay short enough to read at a glance

/** Splits a spoken line into subtitle cues, sharing its time between them. */
function toCues(line: TranscriptLine): TranscriptLine[] {
  const words = line.text.split(" ");
  const parts = Math.ceil(words.length / WORDS_PER_CUE);
  const size = Math.ceil(words.length / parts);
  const span = (line.end - line.start) / parts;
  return Array.from({ length: parts }, (_, index) => ({
    start: line.start + index * span,
    end: line.start + (index + 1) * span,
    text: words.slice(index * size, (index + 1) * size).join(" "),
  }));
}

export function getTranscripts(clip: Clip, language: Language): ClipTranscripts {
  const bank = BANKS[language];
  const length = clipLength(clip);
  const first = Math.floor(seedFrom(clip.id) * 10); // each clip starts somewhere else in the conversation

  const lineCount = Math.min(bank.lines.length, Math.max(2, Math.round(length / 5)));
  const slot = length / lineCount;
  const general = Array.from({ length: lineCount }, (_, index): TranscriptLine => {
    const [speaker, text] = bank.lines[(first + index) % bank.lines.length];
    return { start: index * slot, end: (index + 1) * slot - PAUSE, speaker: bank.speakers[speaker], text };
  });

  const audiovisual = placeScenes(clip).map(
    (scene, index): TranscriptLine => ({
      start: scene.at,
      end: scene.at + scene.end - scene.start,
      text: bank.scenes[(first + index) % bank.scenes.length],
    }),
  );

  return { general, subtitles: general.flatMap(toCues), audiovisual };
}

/** The line on screen at `time`, if any. */
export function cueAt(lines: TranscriptLine[], time: number): TranscriptLine | undefined {
  return lines.find((line) => time >= line.start && time < line.end);
}

/** "[00:41 - 01:02]" — how every transcript line is stamped. */
export function rangeLabel(line: TranscriptLine): string {
  return `[${formatClock(line.start)} - ${formatClock(line.end)}]`;
}

/** Same layout as the panel: the stamp (and who speaks), then what is said or seen. */
export function transcriptText(lines: TranscriptLine[]): string {
  return lines.map((line) => `${rangeLabel(line)}${line.speaker ? ` ${line.speaker}` : ""}\n${line.text}`).join("\n\n");
}

function srtTime(seconds: number): string {
  const total = Math.round(seconds * 1000);
  const pad = (value: number, size = 2) => String(value).padStart(size, "0");
  const hours = Math.floor(total / 3_600_000);
  const minutes = Math.floor(total / 60_000) % 60;
  const secs = Math.floor(total / 1000) % 60;
  return `${pad(hours)}:${pad(minutes)}:${pad(secs)},${pad(total % 1000, 3)}`;
}

/** Standard subtitle file, ready for YouTube, Premiere, etc. */
export function toSrt(lines: TranscriptLine[]): string {
  return lines
    .map((line, index) => `${index + 1}\n${srtTime(line.start)} --> ${srtTime(line.end)}\n${line.text}\n`)
    .join("\n");
}