// Calls the backend on this origin under /api (vite.config.ts proxy; Traefik in production).
// The session is an httpOnly cookie the browser sends by itself: no token is read or stored here.

import { currentPath, loginPageUrl, PATHS } from "./paths";

export const API_PREFIX = "/api";

export const HTTP_STATUS = {
  noContent: 204,
  unauthorized: 401,
  forbidden: 403,
  conflict: 409,
} as const;

const JSON_CONTENT_TYPE = "application/json";
const CONTENT_TYPE_HEADER = "Content-Type";
const ACCEPT_HEADER = "Accept";

export type QueryParams = Record<string, string | number | boolean | undefined>;

export interface ApiRequest extends RequestInit {
  /** Sent as JSON; use body instead for FormData or upload chunks. */
  json?: unknown;
  query?: QueryParams;
  /** "redirect" (default): a 401 sends the browser to the login page. "throw": the caller handles it. */
  onUnauthorized?: "redirect" | "throw";
}

/** An answer outside 2xx. detail is FastAPI's "detail": a message, a code, or the 422 validation list. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `The request failed (status ${status}).`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** The browser-side URL of a backend route, with its query; undefined values are left out. */
export function apiUrl(path: string, query: QueryParams = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const search = params.toString();
  return search ? `${API_PREFIX}${path}?${search}` : `${API_PREFIX}${path}`;
}

/** Calls a backend route and returns its JSON (undefined for 204); throws ApiError outside 2xx. */
export async function apiFetch<T>(path: string, request: ApiRequest = {}): Promise<T> {
  const { json, query, onUnauthorized = "redirect", headers: initHeaders, ...init } = request;
  const headers = new Headers(initHeaders);
  headers.set(ACCEPT_HEADER, JSON_CONTENT_TYPE);
  if (json !== undefined) {
    headers.set(CONTENT_TYPE_HEADER, JSON_CONTENT_TYPE);
    init.body = JSON.stringify(json);
  }

  const response = await fetch(apiUrl(path, query), { ...init, headers, credentials: "same-origin" });
  if (response.status === HTTP_STATUS.unauthorized && onUnauthorized === "redirect") redirectToLogin();
  if (!response.ok) throw new ApiError(response.status, await readDetail(response));
  if (response.status === HTTP_STATUS.noContent) return undefined as T;
  return (await response.json()) as T;
}

/** FastAPI puts the reason in "detail"; null when the body is not JSON (a proxy error page, say). */
async function readDetail(response: Response): Promise<unknown> {
  try {
    const body: unknown = await response.json();
    return typeof body === "object" && body !== null && "detail" in body ? body.detail : null;
  } catch {
    return null;
  }
}

/** The session ended mid-task: sign in again and come back here. Never from the login page itself (no loop). */
function redirectToLogin(): void {
  if (window.location.pathname === PATHS.login) return;
  window.location.assign(loginPageUrl(currentPath(), { expired: true }));
}
