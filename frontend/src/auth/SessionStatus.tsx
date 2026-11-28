import { isRouteErrorResponse, useRouteError } from "react-router";
import { Logo } from "../components/Logo";
import { ApiError } from "../lib/api";

/** Shown on the first load while the session is checked. */
export function SessionPending() {
  return (
    <div className="not-found" role="status" aria-live="polite">
      <Logo />
      <p className="not-found__text">Checking your session…</p>
    </div>
  );
}

/** Shown when a guarded page fails: the session check (backend down, no network) or the page itself. */
export function SessionError() {
  const error = useRouteError();
  // fetch rejects with a TypeError when the network or the proxy is down.
  const sessionFailed = error instanceof ApiError || error instanceof TypeError || isRouteErrorResponse(error);

  return (
    <div className="not-found" role="alert">
      <Logo />
      <p className="not-found__text">
        {sessionFailed
          ? "We couldn't check your session. Please try again in a moment."
          : "Something went wrong on this page."}
      </p>
      <button type="button" className="btn btn--primary" onClick={() => window.location.reload()}>
        Try again
      </button>
    </div>
  );
}
