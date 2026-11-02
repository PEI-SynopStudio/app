import type { ReactNode } from "react";

interface FormSectionProps {
  id: string;
  title: string;
  description?: string;
  optional?: boolean;
  children: ReactNode;
}

export function FormSection({ id, title, description, optional = false, children }: FormSectionProps) {
  const titleId = `${id}-title`;

  return (
    <section className="form__group" aria-labelledby={titleId} data-enter>
      <header className="form__heading">
        <h2 className="form__title" id={titleId}>
          {title}
          {optional && <span className="form__optional">Optional</span>}
        </h2>
        {description && <p className="form__desc">{description}</p>}
      </header>
      {children}
    </section>
  );
}