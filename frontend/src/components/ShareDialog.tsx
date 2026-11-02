import { useId, useState, type FormEvent } from "react";
import { Link } from "react-router";
import type { Clip, Project } from "../data/mock";
import { formatTime } from "../lib/utils";
import { Dialog } from "./Dialog";
import { Field } from "./Field";
import { IconCheck, IconClose, IconLink } from "./Icons";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface ShareDialogProps {
  open: boolean;
  onClose: () => void;
  project: Project;
  clip: Clip;
}

export function ShareDialog({ open, onClose, project, clip }: ShareDialogProps) {
  const linkId = useId();
  const [email, setEmail] = useState("");
  const [invited, setInvited] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // TODO(api): use a random share token created by the API instead of the clip id.
  const path = `/view/${clip.id}`;
  const link = `${window.location.origin}${path}`;

  function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = email.trim().toLowerCase();
    if (!EMAIL.test(next)) {
      setError("Enter a valid email address.");
      return;
    }
    if (invited.includes(next)) {
      setError("This person already has access.");
      return;
    }
    // TODO(api): POST /clips/:id/invites — emails the viewer link; no account needed to watch.
    setInvited((current) => [...current, next]);
    setEmail("");
    setError(null);
  }

  function revoke(person: string) {
    // TODO(api): DELETE /clips/:id/invites/:email
    setInvited((current) => current.filter((item) => item !== person));
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Couldn't copy the link. Select it in the field and copy it manually.");
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Share clip"
      description={
        <p>
          Invite people to watch <strong>{clip.title}</strong>. They don't need an account and can only view
          this clip.
        </p>
      }
    >
      <form className="share-invite" noValidate onSubmit={invite}>
        <Field
          label="Invite by email"
          name="email"
          type="email"
          autoComplete="off"
          placeholder="name@example.com"
          value={email}
          onChange={(event) => {
            setEmail(event.target.value);
            setError(null);
          }}
          aria-invalid={error ? true : undefined}
        />
        <button type="submit" className="btn btn--primary">
          Invite
        </button>
      </form>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {invited.length > 0 && (
        <ul className="share-people" aria-label="People with access">
          {invited.map((person) => (
            <li key={person} className="share-person">
              <span className="share-person__avatar" aria-hidden="true">
                {person[0].toUpperCase()}
              </span>
              <span className="share-person__email">{person}</span>
              <span className="share-person__role">Can view</span>
              <button
                type="button"
                className="share-person__remove"
                aria-label={`Remove access for ${person}`}
                onClick={() => revoke(person)}
              >
                <IconClose />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="field">
        <label className="field__label" htmlFor={linkId}>
          Viewer link
        </label>
        <div className="share-link">
          <input id={linkId} className="input" readOnly value={link} onFocus={(event) => event.currentTarget.select()} />
          <button type="button" className="btn btn--ghost" onClick={copyLink}>
            {copied ? (
              <>
                <IconCheck /> Copied
              </>
            ) : (
              <>
                <IconLink /> Copy
              </>
            )}
          </button>
        </div>
        <p className="field__hint">
          Anyone with this link can watch this {formatTime(clip.end - clip.start)} clip from “{project.title}”.{" "}
          <Link to={path} target="_blank" rel="noreferrer">
            Preview
          </Link>
        </p>
      </div>
    </Dialog>
  );
}