import { useId, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
}

export function Field({ label, hint, id, ...props }: FieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const hintId = hint ? `${inputId}-hint` : undefined;

  return (
    <div className="field">
      <label className="field__label" htmlFor={inputId}>
        {label}
      </label>
      <input id={inputId} className="input" aria-describedby={hintId} {...props} />
      {hint && (
        <p id={hintId} className="field__hint">
          {hint}
        </p>
      )}
    </div>
  );
}

interface TextareaFieldProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  hint?: string;
}

export function TextareaField({ label, hint, id, ...props }: TextareaFieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const hintId = hint ? `${inputId}-hint` : undefined;

  return (
    <div className="field">
      <label className="field__label" htmlFor={inputId}>
        {label}
      </label>
      <textarea id={inputId} className="input input--textarea" aria-describedby={hintId} {...props} />
      {hint && (
        <p id={hintId} className="field__hint">
          {hint}
        </p>
      )}
    </div>
  );
}

interface CheckboxFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "children"> {
  children: ReactNode;
}

/** Links inside the label stay clickable without toggling the box. */
export function CheckboxField({ children, id, ...props }: CheckboxFieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;

  return (
    <div className="checkbox">
      <input id={inputId} type="checkbox" className="checkbox__input" {...props} />
      <label className="checkbox__label" htmlFor={inputId}>
        {children}
      </label>
    </div>
  );
}