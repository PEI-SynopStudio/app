import { useId, type CSSProperties } from "react";
import { FORMATS, FORMAT_RATIO, type AspectRatio } from "../data/options";

interface FormatPickerProps {
  value: AspectRatio;
  onChange: (format: AspectRatio) => void;
}

export function FormatPicker({ value, onChange }: FormatPickerProps) {
  const name = useId();

  return (
    <div className="formats" role="radiogroup" aria-label="Format">
      {FORMATS.map((format) => (
        <label key={format.value} className="choice format-choice">
          <input
            className="sr-only"
            type="radio"
            name={name}
            value={format.value}
            checked={value === format.value}
            onChange={() => onChange(format.value)}
          />
          <span
            className="format-choice__shape"
            style={{ "--ratio": FORMAT_RATIO[format.value] } as CSSProperties}
            aria-hidden="true"
          />
          <span className="choice__label">
            {format.label} <span className="format-choice__ratio">{format.value}</span>
          </span>
          <span className="choice__hint">{format.hint}</span>
        </label>
      ))}
    </div>
  );
}