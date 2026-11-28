import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { useCurrentUser } from "../../auth/useCurrentUser";
import { ConfirmDialog } from "../../components/Dialog";
import { Field } from "../../components/Field";
import { IconTrash } from "../../components/Icons";
import { Switch } from "../../components/Switch";
import { usePageEnter } from "../../hooks/useMotion";
import { ApiError, HTTP_STATUS } from "../../lib/api";
import {
  deleteAccount,
  openAccountPage,
  REAUTHENTICATION_REQUIRED,
  reauthenticate,
  signOut,
  signOutEverywhere,
} from "../../lib/auth";
import { confirmDeletePath, isConfirmDeleteReturn, QUERY } from "../../lib/paths";

interface Prefs {
  clipsReady: boolean;
  weeklyDigest: boolean;
}

const SIGN_OUT_FAILED = "We couldn't log you out. Check your connection and try again.";
const DELETE_BUSY = "A video is still being processed. Try again when it finishes.";
const DELETE_FAILED = "We couldn't delete your account. Please try again in a moment.";

export function Settings() {
  const user = useCurrentUser();
  const pageRef = useRef<HTMLDivElement>(null);
  const [params, setParams] = useSearchParams();
  const [prefs, setPrefs] = useState<Prefs>({ clipsReady: true, weeklyDigest: false });
  // Back from the fresh sign-in that deleting asks for: the dialog opens again and the user confirms again.
  const [deleteOpen, setDeleteOpen] = useState(() => isConfirmDeleteReturn(params));
  const [busy, setBusy] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  usePageEnter(pageRef);

  // Drop the flag from the address, so a reload doesn't open the dialog again.
  useEffect(() => {
    if (!isConfirmDeleteReturn(params)) return;
    setParams(
      (current) => {
        current.delete(QUERY.confirmDelete);
        return current;
      },
      { replace: true },
    );
  }, [params, setParams]);

  function toggle(key: keyof Prefs) {
    setPrefs((current) => ({ ...current, [key]: !current[key] }));
  }

  // On success the browser leaves the page, so busy stays set.
  async function handleSignOut(everywhere: boolean) {
    if (busy) return;
    setBusy(true);
    setSessionError(null);
    try {
      await (everywhere ? signOutEverywhere() : signOut());
    } catch {
      setSessionError(SIGN_OUT_FAILED);
      setBusy(false);
    }
  }

  // Delete the account; without a recent sign-in, ask for the password and come back here to confirm again.
  // Source: backend DELETE /auth/me; MS3 §1.4.3; T4.25.
  async function handleDelete() {
    if (busy) return;
    setBusy(true);
    setDeleteError(null);
    try {
      await deleteAccount();
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === HTTP_STATUS.forbidden &&
        error.detail === REAUTHENTICATION_REQUIRED
      ) {
        reauthenticate(confirmDeletePath());
        return;
      }
      setDeleteOpen(false);
      setDeleteError(error instanceof ApiError && error.status === HTTP_STATUS.conflict ? DELETE_BUSY : DELETE_FAILED);
      setBusy(false);
    }
  }

  return (
    <div className="page page--narrow" ref={pageRef}>
      <header className="page-header" data-enter>
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-subtitle">Manage your profile, session and account.</p>
        </div>
      </header>

      <section className="settings-section" aria-labelledby="profile-title" data-enter>
        <div>
          <h2 className="settings-section__title" id="profile-title">
            Profile
          </h2>
          <p className="settings-section__desc">Your name, email and password are managed on your account page.</p>
        </div>
        <div className="settings-section__body">
          <Field label="Name" name="name" value={user.name} readOnly />
          <Field label="Email" name="email" type="email" value={user.email} readOnly />
          <div className="settings-actions">
            <button type="button" className="btn btn--primary" onClick={openAccountPage}>
              Edit on account page
            </button>
          </div>
        </div>
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
          <p className="settings-section__desc">Log out on this device, or on every device where you're signed in.</p>
        </div>
        <div className="settings-section__body">
          {sessionError && (
            <p className="form-error" role="alert">
              {sessionError}
            </p>
          )}
          <div className="settings-actions">
            <button type="button" className="btn btn--ghost" disabled={busy} onClick={() => handleSignOut(false)}>
              Log out
            </button>
            <button type="button" className="btn btn--ghost" disabled={busy} onClick={() => handleSignOut(true)}>
              Log out of all devices
            </button>
          </div>
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
          {deleteError && (
            <p className="form-error" role="alert">
              {deleteError}
            </p>
          )}
          <button
            type="button"
            className="btn btn--danger-ghost"
            disabled={busy}
            onClick={() => setDeleteOpen(true)}
          >
            <IconTrash /> Delete account
          </button>
        </div>
      </section>

      <ConfirmDialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={handleDelete}
        title="Delete your account?"
        description={
          <>
            <p>
              This permanently deletes <strong>{user.email}</strong> and all your projects. Download any clips you
              want to keep first.
            </p>
            <p>For your security, you may be asked to enter your password again. This can't be undone.</p>
          </>
        }
        confirmLabel="Delete account"
        confirmPhrase="DELETE"
      />
    </div>
  );
}
