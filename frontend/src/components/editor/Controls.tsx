import { useId, type CSSProperties, type ReactNode } from "react";

/** Paints the filled part of a range track (read by .range in studio.css). */
export function rangeFill(value: number, min: number, max: number): CSSProperties {
  const percent = max > min ? ((value - min) / (max - min)) * 100 : 0;
  return { "--value": `${percent}%` } as CSSProperties;
}

interface ToolButtonProps {
  label: string;
  onClick: () => void;
  children: ReactNode;
  disabled?: boolean;
  pressed?: boolean;
  small?: boolean;
}

/** Icon-only button: the label is both the accessible name and the tooltip. */
export function ToolButton({ label, onClick, children, disabled, pressed, small }: ToolButtonProps) {
  return (
    <button
      type="button"
      className={small ? "tool-btn tool-btn--sm" : "tool-btn"}
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

interface RangeFieldProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (value: number) => string;
  onChange: (value: number) => void; // live, while dragging
  onSettle: () => void; // once the drag or key press is over
}

export function RangeField({ label, value, min, max, step, format, onChange, onSettle }: RangeFieldProps) {
  const id = useId();
  return (
    <div className="field">
      <div className="control-row">
        <label className="field__label" htmlFor={id}>
          {label}
        </label>
        <output className="control-value" htmlFor={id}>
          {format(value)}
        </output>
      </div>
      <input
        id={id}
        className="range"
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        style={rangeFill(value, min, max)}
        onChange={(event) => onChange(Number(event.target.value))}
        onPointerUp={onSettle}
        onKeyUp={onSettle}
        onBlur={onSettle}
      />
    </div>
  );
}

interface SegmentedProps<T extends string | number> {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}

export function Segmented<T extends string | number>({ label, value, options, onChange }: SegmentedProps<T>) {
  const id = useId();
  return (
    <div className="field">
      <p className="field__label" id={id}>
        {label}
      </p>
      <div className="segmented segmented--fill" role="group" aria-labelledby={id}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            className="segmented__btn"
            aria-pressed={value === option.value}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}