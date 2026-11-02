import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useMotion } from "../hooks/useMotion";
import { DURATION, EASE, gsap } from "../lib/gsap";
import { Field } from "./Field";
import { IconClose } from "./Icons";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children: ReactNode;
}

/** Native <dialog>: the browser handles the focus trap, Esc and the top layer. */
export function Dialog({ open, onClose, title, description, children }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useMotion(
    ref,
    () => {
      if (!open) return;
      gsap.from(ref.current, {
        y: 16,
        scale: 0.98,
        autoAlpha: 0,
        duration: DURATION.base,
        ease: EASE.out,
        clearProps: "transform,opacity,visibility",
      });
    },
    [open],
  );

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby={`${id}-title`}
      aria-describedby={description ? `${id}-desc` : undefined}
      onClose={onClose}
      // A click on the dialog itself (not the panel) means the backdrop was clicked.
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="dialog__panel">
        <header className="dialog__header">
          <h2 className="dialog__title" id={`${id}-title`}>
            {title}
          </h2>
          <button type="button" className="dialog__close" aria-label="Close" onClick={onClose}>
            <IconClose />
          </button>
        </header>
        {description && (
          <div className="dialog__desc" id={`${id}-desc`}>
            {description}
          </div>
        )}
        {children}
      </div>
    </dialog>
  );
}

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  /** When set, the user must type it before confirming (for irreversible actions). */
  confirmPhrase?: string;
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel,
  confirmPhrase,
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState("");
  const ready = !confirmPhrase || typed.trim() === confirmPhrase;

  function close() {
    setTyped("");
    onClose();
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (ready) onConfirm();
  }

  return (
    <Dialog open={open} onClose={close} title={title} description={description}>
      <form className="dialog__form" onSubmit={handleSubmit}>
        {confirmPhrase && (
          <Field
            label={`Type "${confirmPhrase}" to confirm`}
            name="confirm"
            autoComplete="off"
            spellCheck={false}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
        )}
        <div className="dialog__actions">
          <button type="button" className="btn btn--ghost" onClick={close}>
            Cancel
          </button>
          <button type="submit" className="btn btn--danger" disabled={!ready}>
            {confirmLabel}
          </button>
        </div>
      </form>
    </Dialog>
  );
}