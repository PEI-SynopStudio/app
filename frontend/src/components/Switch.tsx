interface SwitchProps {
  checked: boolean;
  onChange: () => void;
  label: string;
  hint: string;
}

export function Switch({ checked, onChange, label, hint }: SwitchProps) {
  return (
    <label className="switch">
      <input type="checkbox" role="switch" className="sr-only" checked={checked} onChange={onChange} />
      <span className="switch__track" aria-hidden="true">
        <span className="switch__thumb" />
      </span>
      <span className="switch__text">
        <span className="switch__label">{label}</span>
        <span className="switch__hint">{hint}</span>
      </span>
    </label>
  );
}