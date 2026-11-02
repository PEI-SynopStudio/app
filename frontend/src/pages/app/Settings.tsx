import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { ConfirmDialog } from "../../components/Dialog";
import { Field } from "../../components/Field";
import { IconCheck, IconTrash } from "../../components/Icons";
import { Switch } from "../../components/Switch";
import { currentUser, projects } from "../../data/mock";
import { useMotion, usePageEnter } from "../../hooks/useMotion";
import { DURATION, EASE, gsap } from "../../lib/gsap";
import { plural } from "../../lib/utils";

interface Prefs {
  clipsReady: boolean;
  weeklyDigest: boolean;
}

export function Settings() {
  const navigate = useNavigate();
  const pageRef = useRef<HTMLDivElement>(null);
  const [savedAt, setSavedAt] = useState(0);
  const [prefs, setPrefs] = useState<Prefs>({ clipsReady: true, weeklyDigest: false });
  const [deleteOpen, setDeleteOpen] = useState(false);

  usePageEnter(pageRef);

  // "Saved" confirmation: a small scale pop, no overshoot.
  useMotion(
    pageRef,
    () => {
      if (!savedAt) return;
      gsap.from("[data-saved]", { scale: 0.85, autoAlpha: 0, duration: DURATION.base, ease: EASE.out });
    },
    [savedAt],
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // TODO(api): save profile.
    setSavedAt(Date.now());
  }

  function toggle(key: keyof Prefs) {
    setPrefs((current) => ({ ...current, [key]: !current[key] }));
  }

  function deleteAccount() {
    // TODO(api): DELETE /me — then clear the session.
    navigate("/");
  }

  return (
    <div className="page page--narrow" ref={pageRef}>
      <header className="page-header" data-enter>
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-subtitle">Manage your profile and notifications.</p>
        </div>
      </header>

      <section className="settings-section" aria-labelledby="profile-title" data-enter>
        <div>
          <h2 className="settings-section__title" id="profile-title">
            Profile
          </h2>
          <p className="settings-section__desc">How you appear in SynopStudio.</p>
        </div>
        <form className="settings-section__body" onSubmit={handleSubmit}>
          <Field label="Name" name="name" autoComplete="name" defaultValue={currentUser.name} required />
          <Field
            label="Email"
            name="email"
            type="email"
            autoComplete="email"
            defaultValue={currentUser.email}
            required
          />
          <div className="settings-actions">
            <button type="submit" className="btn btn--primary">
              Save Changes
            </button>
            <p className="saved" role="status">
              {savedAt > 0 && (
                <span className="saved__inner" data-saved>
                  <IconCheck /> Changes saved
                </span>
              )}
            </p>
          </div>
        </form>
      </section>

      <section className="settings-section" aria-labelledby="notifications-title" data-enter>
        <div>
          <h2 className="settings-section__title" id="notifications-title">
            Notifications
          </h2>
          <p className="settings-section__desc">Choose what you receive by email.</p>
        </div>
        <div className="settings-section__body">
          <Switch
            checked={prefs.clipsReady}
            onChange={() => toggle("clipsReady")}
            label="Clips ready"
            hint="Get notified when a video has finished processing."
          />
          <Switch
            checked={prefs.weeklyDigest}
            onChange={() => toggle("weeklyDigest")}
            label="Weekly digest"
            hint="A weekly email with the activity of your projects."
          />
        </div>
      </section>

      <section className="settings-section" aria-labelledby="session-title" data-enter>
        <div>
          <h2 className="settings-section__title" id="session-title">
            Session
          </h2>
          <p className="settings-section__desc">Log out on this device.</p>
        </div>
        <div className="settings-section__body">
          <Link to="/" className="btn btn--ghost">
            Log out
          </Link>
        </div>
      </section>

      <section className="settings-section" aria-labelledby="delete-title" data-enter>
        <div>
          <h2 className="settings-section__title" id="delete-title">
            Delete account
          </h2>
          <p className="settings-section__desc">Permanently remove your account and everything in it.</p>
        </div>
        <div className="settings-section__body">
          <p className="settings-note">
            Your videos, supporting files, transcripts and clips are deleted from our servers. Billing and audit
            records are kept for 12 months for legal compliance.
          </p>
          <button type="button" className="btn btn--danger-ghost" onClick={() => setDeleteOpen(true)}>
            <IconTrash /> Delete account
          </button>
        </div>
      </section>

      <ConfirmDialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={deleteAccount}
        title="Delete your account?"
        description={
          <>
            <p>
              This permanently deletes <strong>{currentUser.email}</strong> and your{" "}
              {plural(projects.length, "project", "projects")}. Download any clips you want to keep first.
            </p>
            <p>This can't be undone.</p>
          </>
        }
        confirmLabel="Delete account"
        confirmPhrase="DELETE"
      />
    </div>
  );
}