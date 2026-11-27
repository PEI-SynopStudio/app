// Sign-in, sign-up and sign-out through the backend, which talks to Keycloak (OpenID Connect with PKCE).
// The browser only ever holds the httpOnly session cookie; going to a Keycloak page is a full navigation.
// Source: backend/app/api/auth.py; architecture §2 (Keycloak); MS3 §1.1.6, §1.4.1.

import { ApiError, apiFetch, apiUrl, HTTP_STATUS } from "./api";
import { PATHS, QUERY } from "./paths";

export const AUTH_ROUTES = {
  login: "/auth/login",
  register: "/auth/register",
  me: "/auth/me",
  logout: "/auth/logout",
  logoutAll: "/auth/logout-all",
  account: "/auth/account",
} as const;

const REAUTH_PARAM = "reauth";

/** Detail of the 403 that asks for a fresh sign-in before deleting the account (REAUTHENTICATION_REQUIRED_CODE). */
export const REAUTHENTICATION_REQUIRED = "reauthentication_required";

/** Close code of the progress WebSocket when there is no session (WS_CLOSE_NOT_AUTHENTICATED). */
export const WS_CLOSE_NOT_AUTHENTICATED = 4401;

export const AGE_GROUPS = {
  adult: "adult",
  minorWithGuardianConsent: "minor_with_guardian_consent",
} as const;

export type AgeGroup = (typeof AGE_GROUPS)[keyof typeof AGE_GROUPS];

/** The signed-in account (backend UserResponse); name and email are changed on the Keycloak account page. */
export interface User {
  id: string;
  email: string;
  name: string;
  is_admin: boolean;
  age_group: AgeGroup;
  created_at: string;
}

// One message per backend LoginErrorCode, shown on the login page after ?error=<code>.
const LOGIN_ERROR_MESSAGES: Record<string, string> = {
  login_failed: "We couldn't sign you in. Please try again.",
  login_cancelled: "Sign-in was cancelled.",
  age_group_missing: "Your account has no age group, so it can't be used yet. Please contact us.",
  identity_provider_unavailable: "Sign-in is unavailable right now. Please try again in a few minutes.",
};
const LOGIN_ERROR_FALLBACK = LOGIN_ERROR_MESSAGES.login_failed;

export const SESSION_EXPIRED_MESSAGE = "Your session has ended. Sign in again to continue.";

/** The message for an ?error= code, or null without one; unknown codes get the generic message. */
export function loginErrorMessage(code: string | null): string | null {
  if (!code) return null;
  return LOGIN_ERROR_MESSAGES[code] ?? LOGIN_ERROR_FALLBACK;
}

/** The signed-in user, or null without a session; any other failure throws ApiError. */
export async function fetchCurrentUser(): Promise<User | null> {
  try {
    return await apiFetch<User>(AUTH_ROUTES.me, { onUnauthorized: "throw" });
  } catch (error) {
    if (error instanceof ApiError && error.status === HTTP_STATUS.unauthorized) return null;
    throw error;
  }
}

// Leave the app for the Keycloak sign-in page; the backend brings the browser back to next.
// Source: backend GET /auth/login.
export function signIn(next: string = PATHS.app): void {
  window.location.assign(apiUrl(AUTH_ROUTES.login, { [QUERY.next]: next }));
}

// Leave the app for the Keycloak sign-up page (name, email, password, age group, terms).
// Source: backend GET /auth/register; MS3 §1.4.1.
export function signUp(next: string = PATHS.app): void {
  window.location.assign(apiUrl(AUTH_ROUTES.register, { [QUERY.next]: next }));
}

// Ask for the password again, then come back to next (before deleting the account).
// Source: backend GET /auth/login?reauth=true; T4.25.
export function reauthenticate(next: string): void {
  window.location.assign(apiUrl(AUTH_ROUTES.login, { [QUERY.next]: next, [REAUTH_PARAM]: true }));
}

/** The Keycloak account page, where name, email and password are changed. */
export function openAccountPage(): void {
  window.location.assign(apiUrl(AUTH_ROUTES.account));
}

// Delete the account and all its projects (videos, documents, transcripts, clips); audit records are kept.
// Throws ApiError: 403 REAUTHENTICATION_REQUIRED asks for reauthenticate() first, 409 while a job of the account runs.
// Source: backend DELETE /auth/me; MS3 §1.4.3; T4.25.
export async function deleteAccount(): Promise<void> {
  await apiFetch<void>(AUTH_ROUTES.me, { method: "DELETE" });
  window.location.assign(PATHS.home);
}

/** Ends this session here and at Keycloak, then reloads so nothing of this user stays in memory. */
export async function signOut(): Promise<void> {
  await apiFetch<void>(AUTH_ROUTES.logout, { method: "POST", onUnauthorized: "throw" });
  window.location.assign(PATHS.home);
}

/** Ends every session of the account (all browsers and devices); a session already gone counts as signed out. */
export async function signOutEverywhere(): Promise<void> {
  try {
    await apiFetch<void>(AUTH_ROUTES.logoutAll, { method: "POST", onUnauthorized: "throw" });
  } catch (error) {
    if (!(error instanceof ApiError && error.status === HTTP_STATUS.unauthorized)) throw error;
  }
  window.location.assign(PATHS.home);
}
