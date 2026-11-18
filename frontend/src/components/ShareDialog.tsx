import { useId, useState } from "react";
import { Link } from "react-router";
import { clipLength, type Clip, type Project } from "../data/mock";
import { formatTime } from "../lib/utils";
import { Dialog } from "./Dialog";
import { IconCheck, IconLink } from "./Icons";

interface ShareDialogProps {
  open: boolean;
  onClose: () => void;
  project: Project;
  clip: Clip;
}

/** Sharing is link-only: whoever has the link can watch this one clip, no account needed. */
export function ShareDialog({ open, onClose, project, clip }: ShareDialogProps) {
  const linkId = useId();
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // TODO(api): use a random share token created by the API instead of the clip id.
  const path = `/view/${clip.id}`;
  const link = `${window.location.origin}${path}`;

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(link);
      setError(null);
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
          Anyone with the link can watch <strong>{clip.title}</strong>, with its subtitles and transcripts. No
          account needed.
        </p>
      }
    >
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
          Only this {formatTime(clipLength(clip))} clip is shared, not the rest of “{project.title}”.{" "}
          <Link to={path} target="_blank" rel="noreferrer">
            Preview
          </Link>
        </p>
      </div>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}