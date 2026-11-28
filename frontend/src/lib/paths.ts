// Frontend pages and query parameters that sign-in uses; the backend sends the browser back to them.
// Source: backend/app/core/config.py (FRONTEND_LOGIN_PATH, FRONTEND_DEFAULT_NEXT_PATH, NEXT_QUERY_PARAM, LOGIN_ERROR_QUERY_PARAM).

export const PATHS = {
  home: "/",
  login: "/login",
  signup: "/signup",
  app: "/app",
  settings: "/app/settings",
} as const;

export const QUERY = {
  /** Where to go after signing in. */
  next: "next",
  /** A LoginErrorCode the backend adds after a failed sign-in. */
  error: "error",
  /** Set by the frontend when the session ended mid-task. */
  expired: "expired",
  /** Set when coming back from the fresh sign-in that deleting the account asks for. */
  confirmDelete: "confirmDelete",
} as const;

const FLAG_ON = "1";

/** The page the user is on, with its query: where to come back to after signing in. */
export function currentPath(): string {
  const { pathname, search } = window.location;
  return pathname + search;
}

/** The login page; next is where to go after signing in, expired shows the "session ended" notice. */
export function loginPageUrl(next?: string, { expired = false } = {}): string {
  const params = new URLSearchParams();
  if (next) params.set(QUERY.next, next);
  if (expired) params.set(QUERY.expired, FLAG_ON);
  const query = params.toString();
  return query ? `${PATHS.login}?${query}` : PATHS.login;
}

/** Whether the login page was opened because the session ended. */
export function isExpiredLogin(params: URLSearchParams): boolean {
  return params.get(QUERY.expired) === FLAG_ON;
}

/** Settings with the delete dialog open again: where the fresh sign-in before deleting the account comes back. */
export function confirmDeletePath(): string {
  return `${PATHS.settings}?${QUERY.confirmDelete}=${FLAG_ON}`;
}

/** Whether Settings was opened on the way back from that fresh sign-in. */
export function isConfirmDeleteReturn(params: URLSearchParams): boolean {
  return params.get(QUERY.confirmDelete) === FLAG_ON;
}

/** next if it is a page of this app, else the app home: never another origin, never a sign-in page (no loop). */
export function safeNextPath(next: string | null): string {
  if (!next?.startsWith(PATHS.home)) return PATHS.app;
  // The URL parser strips tabs and newlines and reads "//host" as a host, the same way the browser does.
  const url = new URL(next, window.location.origin);
  if (url.origin !== window.location.origin) return PATHS.app;
  if (url.pathname === PATHS.login || url.pathname === PATHS.signup) return PATHS.app;
  return url.pathname + url.search + url.hash;
}
