import { useId, useRef } from "react";
import {
  CAPTION_LANGUAGES,
  CAPTION_SHORT,
  CAPTION_STYLES,
  DEFAULT_CAPTIONS,
  type CaptionSettings,
} from "../data/options";
import { useMotion } from "../hooks/useMotion";
import { DURATION, gsap } from "../lib/gsap";
import { Caption } from "./Caption";
import { Switch } from "./Switch";

interface CaptionOptionsProps {
  value: CaptionSettings | null; // null = no subtitles
  onChange: (captions: CaptionSettings | null) => void;
}

export function CaptionOptions({ value, onChange }: CaptionOptionsProps) {
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const lastChoice = useRef<CaptionSettings>(value ?? DEFAULT_CAPTIONS);
  const hasToggled = useRef(false);
  const enabled = value !== null;

  // Turning subtitles on: the options slide in (not on first render — the page entrance covers that).
  useMotion(
    rootRef,
    () => {
      if (!enabled || !hasToggled.current) return;
      gsap.from("[data-caption-options]", { y: 8, autoAlpha: 0, duration: DURATION.base });
    },
    [enabled],
  );

  function toggle() {
    hasToggled.current = true;
    // Turning them back on restores the last language and style.
    onChange(enabled ? null : lastChoice.current);
  }

  function update(patch: Partial<CaptionSettings>) {
    if (!value) return;
    const next = { ...value, ...patch };
    lastChoice.current = next;
    onChange(next);
  }

  return (
    <div className="captions" ref={rootRef}>
      <Switch
        checked={enabled}
        onChange={toggle}
        label="Add subtitles"
        hint="Burned into the clips and timed to the speech."
      />

      {value && (
        <div className="captions__options" data-caption-options>
          <div className="field">
            <p className="field__label" id={`${id}-language`}>
              Language
            </p>
            <div className="chips" role="radiogroup" aria-labelledby={`${id}-language`}>
              {CAPTION_LANGUAGES.map((language) => (
                <label key={language.value} className="chip">
                  <input
                    className="sr-only"
                    type="radio"
                    name={`${id}-language`}
                    value={language.value}
                    checked={value.language === language.value}
                    onChange={() => update({ language: language.value })}
                  />
                  {language.label}
                </label>
              ))}
            </div>
          </div>

          <div className="field">
            <p className="field__label" id={`${id}-style`}>
              Style
            </p>
            <div className="style-choices" role="radiogroup" aria-labelledby={`${id}-style`}>
              {CAPTION_STYLES.map((style) => (
                <label key={style.value} className="choice style-choice">
                  <input
                    className="sr-only"
                    type="radio"
                    name={`${id}-style`}
                    value={style.value}
                    checked={value.style === style.value}
                    onChange={() => update({ style: style.value })}
                  />
                  <span className="style-choice__preview" aria-hidden="true">
                    <Caption text={CAPTION_SHORT[value.language]} variant={style.value} />
                  </span>
                  <span className="choice__label">{style.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}